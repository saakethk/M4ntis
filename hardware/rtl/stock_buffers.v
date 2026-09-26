`timescale 1ns/1ps

// BUF[0..4]: 5 independent 30-entry circular buffers of 16-bit signed
// prices (spec sections 1/5). head[b] points at buffer b's most recent
// entry and only moves on an advance (UPDATEALLSTOCKBUFFERS).
//
// Tick staging (spec 6.2): a TICK doesn't touch the buffer, it parks a
// price in that buffer's staging reg and sets its pending flag. Advance
// only fires once all 5 flags are set; it writes every staged price into
// slot head+1, moves all 5 heads together, and clears the flags.
//
// The tick port is shaped like one decoded UART TICK message -- a
// 1-cycle tick_valid strobe with buf_id + price -- so Stage 6's TICK
// decoder can drive it directly. Until then the testbench drives it.
//   - a second tick for an already-pending buffer replaces the staged
//     price (latest wins)
//   - a tick landing in the same cycle as an advance is kept for the
//     next round, not lost
//   - tick_buf_id 5-7 is ignored
//
// Single read port, (buf_id, days_before) -> BUF[buf_id][head - days],
// wrapped mod 30. days_before = 0 is GETSTOCKPRICE. days_before >= 30
// aliases mod 30 (only 30 days exist). rd_buf_id 5-7 reads 0.
//
// Each buffer's mem has exactly one write port and an async read, so it
// maps to LUTRAM -- which is why contents aren't cleared on rst_n (only
// heads and staging are). The initial block zero-fills at configuration
// time; Vivado honours that for RAM init.

module stock_buffers (
    input  wire        clk,
    input  wire        rst_n,

    input  wire        tick_valid,
    input  wire [2:0]  tick_buf_id,
    input  wire [15:0] tick_price,
    output wire [4:0]  tick_pending,
    output wire        all_ticks_pending,

    input  wire        advance,

    input  wire [2:0]  rd_buf_id,
    input  wire [4:0]  rd_days_before,
    output reg  [15:0] rd_data
);

    localparam NUM_BUFS = 5;
    localparam DEPTH    = 30;

    wire [24:0] heads_flat;
    wire [79:0] rdata_flat;

    assign all_ticks_pending = &tick_pending;

    wire advance_fire = advance && all_ticks_pending;

    reg [4:0] rd_head;
    always @(*) begin
        case (rd_buf_id)
            3'd0:    rd_head = heads_flat[4:0];
            3'd1:    rd_head = heads_flat[9:5];
            3'd2:    rd_head = heads_flat[14:10];
            3'd3:    rd_head = heads_flat[19:15];
            3'd4:    rd_head = heads_flat[24:20];
            default: rd_head = 5'd0;
        endcase
    end

    wire [4:0] days_mod = (rd_days_before >= 5'd30) ? (rd_days_before - 5'd30) : rd_days_before;
    wire [4:0] rd_idx   = (rd_head >= days_mod) ? (rd_head - days_mod)
                                                : (rd_head + (5'd30 - days_mod));

    genvar b;
    generate
        for (b = 0; b < NUM_BUFS; b = b + 1) begin : g_buf
            reg [15:0] mem [0:DEPTH-1];
            reg [4:0]  head;
            reg [15:0] staged_price;
            reg        staged_valid;

            wire       tick_hit  = tick_valid && (tick_buf_id == b);
            wire [4:0] next_head = (head == DEPTH - 1) ? 5'd0 : (head + 5'd1);

            integer i;
            initial begin
                for (i = 0; i < DEPTH; i = i + 1)
                    mem[i] = 16'd0;
            end

            always @(posedge clk) begin
                if (advance_fire)
                    mem[next_head] <= staged_price;
            end

            always @(posedge clk or negedge rst_n) begin
                if (!rst_n) begin
                    head         <= 5'd0;
                    staged_price <= 16'd0;
                    staged_valid <= 1'b0;
                end else begin
                    if (advance_fire) begin
                        head         <= next_head;
                        staged_valid <= 1'b0;
                    end
                    // after the advance on purpose: a same-cycle tick wins
                    if (tick_hit) begin
                        staged_price <= tick_price;
                        staged_valid <= 1'b1;
                    end
                end
            end

            assign heads_flat[b*5 +: 5]   = head;
            assign rdata_flat[b*16 +: 16] = mem[rd_idx];
            assign tick_pending[b]        = staged_valid;
        end
    endgenerate

    always @(*) begin
        case (rd_buf_id)
            3'd0:    rd_data = rdata_flat[15:0];
            3'd1:    rd_data = rdata_flat[31:16];
            3'd2:    rd_data = rdata_flat[47:32];
            3'd3:    rd_data = rdata_flat[63:48];
            3'd4:    rd_data = rdata_flat[79:64];
            default: rd_data = 16'd0;
        endcase
    end

endmodule
