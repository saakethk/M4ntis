`timescale 1ns/1ps

// The CPU plus its UART link to the host (spec section 6).
//
// Serial: UART_RXD / UART_TXD, named as in Urbana.xdc (A16 / B16,
// LVCMOS33), 8N1 at BAUD. CLK_HZ must be the frequency clk actually runs
// at -- it sets the bit timing (50 MHz / 115200 -> 434 clocks per bit).
//
// Reset domains: rst_n resets everything. The CPU side (control unit,
// registers, buffers, VAR, BALANCE, divider) additionally resets while
// uart_protocol holds cpu_hold during a LOAD_PROGRAM; the UART side
// doesn't, and prog_mem is never reset.
//
// tick_valid/tick_buf_id/tick_price is a direct tick-injection port for
// testbenches (Stages 3-5 drive it). A board top ties it low; ticks then
// come only from UART TICK messages. Both feed the same stock_buffers
// staging interface -- a UART tick wins if both land on one cycle.
//
// dbg_* outputs are status for LEDs.

module tradecpu_core #(
    parameter CLK_HZ              = 50000000,   // clk50 from tradecpu_top's MMCM
    parameter BAUD                = 115200,
    parameter UART_TIMEOUT_CYCLES = CLK_HZ / 10      // 100 ms
) (
    input  wire        clk,
    input  wire        rst_n,

    input  wire        tick_valid,
    input  wire [2:0]  tick_buf_id,
    input  wire [15:0] tick_price,

    input  wire        UART_RXD,
    output wire        UART_TXD,

    output wire [4:0]  dbg_tick_pending,
    output reg  [4:0]  dbg_advance_count,
    output wire        dbg_prog_loaded,
    output wire        dbg_loading,
    output wire        dbg_proto_error,
    output wire        dbg_rx_msg_toggle,
    output wire        dbg_tx_msg_toggle
);

    // rounded, so a clock that isn't an exact multiple of the baud still
    // gets the nearest divisor
    localparam CLKS_PER_BIT = (CLK_HZ + BAUD / 2) / BAUD;

    wire        rf_we;
    wire [2:0]  rf_waddr;
    wire [31:0] rf_wdata;
    wire [2:0]  rf_raddr1;
    wire [2:0]  rf_raddr2;
    wire [31:0] rf_rdata1;
    wire [31:0] rf_rdata2;

    wire [4:0]  alu_opcode;
    wire [31:0] alu_in1;
    wire [31:0] alu_in2;
    wire [31:0] alu_result;

    wire [2:0]  buf_rd_id;
    wire [4:0]  buf_rd_days_before;
    wire [15:0] buf_rd_data;
    wire [4:0]  buf_tick_pending;
    wire        buf_all_ticks_pending;
    wire        buf_advance;

    wire        div_start;
    wire [31:0] div_dividend;
    wire [31:0] div_divisor;
    wire        div_done;
    wire [31:0] div_quotient;

    wire [3:0]  var_id;
    wire        var_we;
    wire [31:0] var_wdata;
    wire [31:0] var_rdata;

    wire        bal_update_en;
    wire [31:0] bal_amount;
    wire        bal_set_en;
    wire [31:0] bal_set_value;
    wire [31:0] bal_value;

    wire [7:0]  rx_data;
    wire        rx_valid;
    wire        rx_frame_err;
    wire [7:0]  tx_data;
    wire        tx_start;
    wire        tx_busy;

    wire        pm_we;
    wire [8:0]  pm_waddr;
    wire [31:0] pm_wdata;
    wire        cpu_hold;

    wire        uart_tick_valid;
    wire [2:0]  uart_tick_buf_id;
    wire [15:0] uart_tick_price;

    wire        msg_valid;
    wire        msg_ready;
    wire        msg_kind;
    wire [31:0] msg_data;

    // cpu_hold is a flop output, so this is a clean reset
    wire cpu_rst_n = rst_n & ~cpu_hold;

    wire        bs_tick_valid  = uart_tick_valid | tick_valid;
    wire [2:0]  bs_tick_buf_id = uart_tick_valid ? uart_tick_buf_id : tick_buf_id;
    wire [15:0] bs_tick_price  = uart_tick_valid ? uart_tick_price  : tick_price;

    assign dbg_tick_pending = buf_tick_pending;
    assign dbg_loading      = cpu_hold;

    // how many times UPDATEALLSTOCKBUFFERS has advanced (mod 32)
    always @(posedge clk or negedge cpu_rst_n) begin
        if (!cpu_rst_n)
            dbg_advance_count <= 5'd0;
        else if (buf_advance)
            dbg_advance_count <= dbg_advance_count + 5'd1;
    end

    // ---------------- CPU ----------------

    register_file u_register_file (
        .clk    (clk),
        .rst_n  (cpu_rst_n),
        .we     (rf_we),
        .waddr  (rf_waddr),
        .wdata  (rf_wdata),
        .raddr1 (rf_raddr1),
        .raddr2 (rf_raddr2),
        .rdata1 (rf_rdata1),
        .rdata2 (rf_rdata2)
    );

    alu u_alu (
        .opcode (alu_opcode),
        .in1    (alu_in1),
        .in2    (alu_in2),
        .result (alu_result)
    );

    stock_buffers u_stock_buffers (
        .clk               (clk),
        .rst_n             (cpu_rst_n),
        .tick_valid        (bs_tick_valid),
        .tick_buf_id       (bs_tick_buf_id),
        .tick_price        (bs_tick_price),
        .tick_pending      (buf_tick_pending),
        .all_ticks_pending (buf_all_ticks_pending),
        .advance           (buf_advance),
        .rd_buf_id         (buf_rd_id),
        .rd_days_before    (buf_rd_days_before),
        .rd_data           (buf_rd_data)
    );

    var_store u_var_store (
        .clk    (clk),
        .rst_n  (cpu_rst_n),
        .var_id (var_id),
        .we     (var_we),
        .wdata  (var_wdata),
        .rdata  (var_rdata)
    );

    balance_reg u_balance_reg (
        .clk       (clk),
        .rst_n     (cpu_rst_n),
        .update_en (bal_update_en),
        .amount    (bal_amount),
        .set_en    (bal_set_en),
        .set_value (bal_set_value),
        .balance   (bal_value)
    );

    // stand-in for the Divider Generator IP, see divider.v
    divider u_divider (
        .clk      (clk),
        .rst_n    (cpu_rst_n),
        .start    (div_start),
        .dividend (div_dividend),
        .divisor  (div_divisor),
        .done     (div_done),
        .quotient (div_quotient)
    );

    control_unit u_control_unit (
        .clk        (clk),
        .rst_n      (cpu_rst_n),
        .rf_we      (rf_we),
        .rf_waddr   (rf_waddr),
        .rf_wdata   (rf_wdata),
        .rf_raddr1  (rf_raddr1),
        .rf_raddr2  (rf_raddr2),
        .rf_rdata1  (rf_rdata1),
        .rf_rdata2  (rf_rdata2),
        .alu_opcode (alu_opcode),
        .alu_in1    (alu_in1),
        .alu_in2    (alu_in2),
        .alu_result (alu_result),
        .buf_rd_id             (buf_rd_id),
        .buf_rd_days_before    (buf_rd_days_before),
        .buf_rd_data           (buf_rd_data),
        .buf_all_ticks_pending (buf_all_ticks_pending),
        .buf_advance           (buf_advance),
        .div_start             (div_start),
        .div_dividend          (div_dividend),
        .div_divisor           (div_divisor),
        .div_done              (div_done),
        .div_quotient          (div_quotient),
        .var_id                (var_id),
        .var_we                (var_we),
        .var_wdata             (var_wdata),
        .var_rdata             (var_rdata),
        .bal_update_en         (bal_update_en),
        .bal_amount            (bal_amount),
        .bal_set_en            (bal_set_en),
        .bal_set_value         (bal_set_value),
        .bal_value             (bal_value),
        .pm_we                 (pm_we),
        .pm_waddr              (pm_waddr),
        .pm_wdata              (pm_wdata),
        .msg_valid             (msg_valid),
        .msg_ready             (msg_ready),
        .msg_kind              (msg_kind),
        .msg_data              (msg_data)
    );

    // ---------------- UART link ----------------

    uart_rx #(
        .CLKS_PER_BIT (CLKS_PER_BIT)
    ) u_uart_rx (
        .clk       (clk),
        .rst_n     (rst_n),
        .rxd       (UART_RXD),
        .data      (rx_data),
        .valid     (rx_valid),
        .frame_err (rx_frame_err)
    );

    uart_tx #(
        .CLKS_PER_BIT (CLKS_PER_BIT)
    ) u_uart_tx (
        .clk   (clk),
        .rst_n (rst_n),
        .start (tx_start),
        .data  (tx_data),
        .txd   (UART_TXD),
        .busy  (tx_busy)
    );

    uart_protocol #(
        .TIMEOUT_CYCLES (UART_TIMEOUT_CYCLES)
    ) u_uart_protocol (
        .clk           (clk),
        .rst_n         (rst_n),
        .rx_data       (rx_data),
        .rx_valid      (rx_valid),
        .rx_frame_err  (rx_frame_err),
        .tx_data       (tx_data),
        .tx_start      (tx_start),
        .tx_busy       (tx_busy),
        .pm_we         (pm_we),
        .pm_waddr      (pm_waddr),
        .pm_wdata      (pm_wdata),
        .cpu_hold      (cpu_hold),
        .tick_valid    (uart_tick_valid),
        .tick_buf_id   (uart_tick_buf_id),
        .tick_price    (uart_tick_price),
        .msg_valid     (msg_valid),
        .msg_ready     (msg_ready),
        .msg_kind      (msg_kind),
        .msg_data      (msg_data),
        .prog_loaded   (dbg_prog_loaded),
        .proto_error   (dbg_proto_error),
        .rx_msg_toggle (dbg_rx_msg_toggle),
        .tx_msg_toggle (dbg_tx_msg_toggle)
    );

endmodule
