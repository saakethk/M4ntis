`timescale 1ns/1ps

// Spec section 6 wire protocol, between uart_rx/uart_tx and the CPU.
// All multi-byte fields little-endian.
//
// Host -> FPGA (decoded from uart_rx bytes):
//   LOAD_PROGRAM  01 | len_lo len_hi | len bytes of instruction words
//     - cpu_hold goes high on the 0x01 byte and holds the CPU (but not
//       this module, and not prog_mem) in reset for the whole message.
//     - every 4 bytes are assembled into one word (first byte = bits 7:0)
//       and written to prog_mem[0], [1], ... through pm_we/pm_waddr/
//       pm_wdata. Bytes arrive ~8680 clocks apart and each word write
//       takes one cycle, so a 4-byte assembly register is all the
//       buffering the RX side needs.
//     - after the last byte cpu_hold drops: the CPU restarts at pc 0 with
//       registers, VAR, BALANCE, buffer heads and staged ticks cleared.
//       len = 0 is a valid "restart the current program".
//     - words past 511 are dropped, and a len that isn't a multiple of 4
//       drops the trailing partial word; both set proto_error. The bytes
//       are still consumed so the stream stays aligned.
//   TICK          02 | buf_id | price_lo price_hi
//     - one 1-cycle tick_valid pulse with tick_buf_id/tick_price, i.e.
//       exactly the stock_buffers staging interface from Stage 3.
//     - buf_id > 4 is dropped (checked on the whole byte, so e.g. 8 can't
//       alias to buffer 0) and sets proto_error.
//   Any other first byte is ignored and sets proto_error.
//
// Resync: the spec has no sync byte, so if a message stalls part-way for
// TIMEOUT_CYCLES with no new byte (100 ms by default), the partial message
// is dropped and the decoder goes back to waiting for a type byte
// (proto_error set). A LOAD_PROGRAM dropped this way leaves the CPU held
// in reset -- prog_mem is only partly written -- until the next complete
// LOAD_PROGRAM. A UART framing error also sets proto_error.
//
// FPGA -> host:
//   DECISION_EVENT 03 | buf_id | action | qty_lo qty_hi       (EMITDECISION)
//   EMIT_BALANCE   04 | b0 b1 b2 b3  (int32, b0 = bits 7:0)   (EMITBALANCE)
//     - the CPU hands over one message at a time with a
//       msg_valid/msg_ready handshake (msg_kind 0 = decision,
//       1 = balance). Both kinds share one 8-deep FIFO, so they go out in
//       the order the program issued them. Each is serialized as 5 bytes;
//       when the FIFO is full msg_ready drops and the CPU stalls until
//       there's room, so none are lost.
//
// Status outputs (for LEDs): prog_loaded, proto_error (sticky until
// reset), rx_msg_toggle (flips per complete TICK/LOAD_PROGRAM),
// tx_msg_toggle (flips per DECISION_EVENT sent -- not per EMIT_BALANCE:
// a strategy that reports balance after every trade would otherwise
// flip it twice per trade and the LED would look stuck).

module uart_protocol #(
    parameter TIMEOUT_CYCLES = 10000000
) (
    input  wire        clk,
    input  wire        rst_n,

    input  wire [7:0]  rx_data,
    input  wire        rx_valid,
    input  wire        rx_frame_err,

    output wire [7:0]  tx_data,
    output wire        tx_start,
    input  wire        tx_busy,

    output reg         pm_we,
    output reg  [8:0]  pm_waddr,
    output reg  [31:0] pm_wdata,
    output reg         cpu_hold,

    output reg         tick_valid,
    output reg  [2:0]  tick_buf_id,
    output reg  [15:0] tick_price,

    input  wire        msg_valid,
    output wire        msg_ready,
    input  wire        msg_kind,
    input  wire [31:0] msg_data,

    output reg         prog_loaded,
    output reg         proto_error,
    output reg         rx_msg_toggle,
    output reg         tx_msg_toggle
);

    localparam MSG_LOAD_PROGRAM   = 8'h01;
    localparam MSG_TICK           = 8'h02;
    localparam MSG_DECISION_EVENT = 8'h03;
    localparam MSG_EMIT_BALANCE   = 8'h04;

    localparam R_IDLE    = 3'd0;
    localparam R_LEN_LO  = 3'd1;
    localparam R_LEN_HI  = 3'd2;
    localparam R_DATA    = 3'd3;
    localparam R_TICK_ID = 3'd4;
    localparam R_TICK_LO = 3'd5;
    localparam R_TICK_HI = 3'd6;

    localparam PROG_WORDS = 512;

    // ---------------- receive side ----------------

    reg [2:0]  rstate;
    reg [15:0] len_left;
    reg [1:0]  byte_idx;
    reg [23:0] word_buf;     // first 3 bytes of the word being assembled
    reg [14:0] word_addr;    // wide enough for 65535/4 words, never wraps
    reg [7:0]  tick_id_byte;
    reg [7:0]  tick_lo;
    reg [31:0] idle_cnt;

    wire [15:0] len_rx = {rx_data, len_left[7:0]};

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            rstate        <= R_IDLE;
            len_left      <= 16'd0;
            byte_idx      <= 2'd0;
            word_buf      <= 24'd0;
            word_addr     <= 15'd0;
            tick_id_byte  <= 8'd0;
            tick_lo       <= 8'd0;
            idle_cnt      <= 32'd0;
            pm_we         <= 1'b0;
            pm_waddr      <= 9'd0;
            pm_wdata      <= 32'd0;
            cpu_hold      <= 1'b0;
            tick_valid    <= 1'b0;
            tick_buf_id   <= 3'd0;
            tick_price    <= 16'd0;
            prog_loaded   <= 1'b0;
            proto_error   <= 1'b0;
            rx_msg_toggle <= 1'b0;
        end else begin
            pm_we      <= 1'b0;
            tick_valid <= 1'b0;

            if (rx_frame_err)
                proto_error <= 1'b1;

            if (rx_valid) begin
                idle_cnt <= 32'd0;

                case (rstate)
                    R_IDLE: begin
                        if (rx_data == MSG_LOAD_PROGRAM) begin
                            cpu_hold    <= 1'b1;
                            prog_loaded <= 1'b0;
                            rstate      <= R_LEN_LO;
                        end else if (rx_data == MSG_TICK) begin
                            rstate <= R_TICK_ID;
                        end else begin
                            proto_error <= 1'b1;
                        end
                    end

                    R_LEN_LO: begin
                        len_left[7:0] <= rx_data;
                        rstate        <= R_LEN_HI;
                    end

                    R_LEN_HI: begin
                        len_left  <= len_rx;
                        byte_idx  <= 2'd0;
                        word_addr <= 15'd0;
                        if (len_rx[1:0] != 2'd0 || len_rx > PROG_WORDS * 4)
                            proto_error <= 1'b1;
                        if (len_rx == 16'd0) begin
                            cpu_hold      <= 1'b0;
                            prog_loaded   <= 1'b1;
                            rx_msg_toggle <= ~rx_msg_toggle;
                            rstate        <= R_IDLE;
                        end else begin
                            rstate <= R_DATA;
                        end
                    end

                    R_DATA: begin
                        word_buf <= {rx_data, word_buf[23:8]};
                        byte_idx <= byte_idx + 2'd1;
                        if (byte_idx == 2'd3) begin
                            if (word_addr < PROG_WORDS) begin
                                pm_we    <= 1'b1;
                                pm_waddr <= word_addr[8:0];
                                pm_wdata <= {rx_data, word_buf};
                            end
                            word_addr <= word_addr + 15'd1;
                        end
                        len_left <= len_left - 16'd1;
                        if (len_left == 16'd1) begin
                            cpu_hold      <= 1'b0;
                            prog_loaded   <= 1'b1;
                            rx_msg_toggle <= ~rx_msg_toggle;
                            rstate        <= R_IDLE;
                        end
                    end

                    R_TICK_ID: begin
                        tick_id_byte <= rx_data;
                        rstate       <= R_TICK_LO;
                    end

                    R_TICK_LO: begin
                        tick_lo <= rx_data;
                        rstate  <= R_TICK_HI;
                    end

                    R_TICK_HI: begin
                        if (tick_id_byte <= 8'd4) begin
                            tick_valid    <= 1'b1;
                            tick_buf_id   <= tick_id_byte[2:0];
                            tick_price    <= {rx_data, tick_lo};
                            rx_msg_toggle <= ~rx_msg_toggle;
                        end else begin
                            proto_error <= 1'b1;
                        end
                        rstate <= R_IDLE;
                    end

                    default: rstate <= R_IDLE;
                endcase
            end else if (rstate != R_IDLE) begin
                // mid-message with no byte: give up after the timeout.
                // cpu_hold is left as-is, so an abandoned LOAD_PROGRAM keeps
                // the CPU held.
                if (idle_cnt == TIMEOUT_CYCLES - 1) begin
                    idle_cnt    <= 32'd0;
                    proto_error <= 1'b1;
                    rstate      <= R_IDLE;
                end else begin
                    idle_cnt <= idle_cnt + 32'd1;
                end
            end else begin
                idle_cnt <= 32'd0;
            end
        end
    end

    // ---------------- transmit side ----------------

    // one queued message: {kind, data[31:0]}
    //   kind 0 (decision): data = {12'd0, buf_id[2:0], action, quantity[15:0]}
    //   kind 1 (balance):  data = the 32-bit value
    wire        fifo_full, fifo_empty;
    wire [32:0] fifo_rd_data;
    wire        fifo_rd_en;

    reg         tx_active;
    reg [2:0]   tx_idx;
    reg         tx_kind;
    reg [31:0]  tx_rec;

    assign msg_ready  = !fifo_full;
    assign fifo_rd_en = !tx_active && !fifo_empty;

    sync_fifo #(
        .WIDTH  (33),
        .ADDR_W (3)
    ) u_msg_fifo (
        .clk     (clk),
        .rst_n   (rst_n),
        .wr_en   (msg_valid),
        .wr_data ({msg_kind, msg_data}),
        .full    (fifo_full),
        .rd_en   (fifo_rd_en),
        .rd_data (fifo_rd_data),
        .empty   (fifo_empty)
    );

    // both message kinds are 5 bytes: type byte + 4 payload bytes
    wire [7:0] decision_byte = (tx_idx == 3'd0) ? MSG_DECISION_EVENT :
                               (tx_idx == 3'd1) ? {5'd0, tx_rec[19:17]} :
                               (tx_idx == 3'd2) ? {7'd0, tx_rec[16]} :
                               (tx_idx == 3'd3) ? tx_rec[7:0] :
                                                  tx_rec[15:8];

    wire [7:0] balance_byte  = (tx_idx == 3'd0) ? MSG_EMIT_BALANCE :
                               (tx_idx == 3'd1) ? tx_rec[7:0] :
                               (tx_idx == 3'd2) ? tx_rec[15:8] :
                               (tx_idx == 3'd3) ? tx_rec[23:16] :
                                                  tx_rec[31:24];

    assign tx_data  = tx_kind ? balance_byte : decision_byte;
    assign tx_start = tx_active && !tx_busy;

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            tx_active     <= 1'b0;
            tx_idx        <= 3'd0;
            tx_kind       <= 1'b0;
            tx_rec        <= 32'd0;
            tx_msg_toggle <= 1'b0;
        end else if (!tx_active) begin
            if (!fifo_empty) begin
                tx_kind   <= fifo_rd_data[32];
                tx_rec    <= fifo_rd_data[31:0];
                tx_idx    <= 3'd0;
                tx_active <= 1'b1;
            end
        end else if (!tx_busy) begin
            // tx_start is high this cycle: uart_tx takes tx_data now
            if (tx_idx == 3'd4) begin
                tx_active <= 1'b0;
                if (!tx_kind)
                    tx_msg_toggle <= ~tx_msg_toggle;
            end
            tx_idx <= tx_idx + 3'd1;
        end
    end

endmodule
