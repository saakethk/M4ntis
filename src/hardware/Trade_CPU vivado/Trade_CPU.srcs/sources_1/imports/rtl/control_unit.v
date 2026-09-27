`timescale 1ns/1ps

// Stage 1 opcodes (NOP/ADD/SUB/MUL/CMP_GT/CMP_LT), Stage 2's
// LOAD_IMM/JMP/JMP_IF, Stage 3's buffer ops, Stage 4's DIV and
// GETSUMPRICEBEFORE, Stage 5's VAR/BALANCE ops, and Stage 6's
// EMITDECISION / EMITBALANCE.
//
// prog_mem has one write port (pm_we/pm_waddr/pm_wdata), driven by
// uart_protocol's LOAD_PROGRAM handling. It's a separate always block
// with no reset, so the CPU can sit in reset while its program is being
// written; the fetch reads (ir <= prog_mem[pc], ir2 <= prog_mem[pc+1])
// are unchanged. Testbenches may still poke prog_mem hierarchically.
//
// LOAD_IMM/JMP/JMP_IF are two-word instructions (spec section 3): word0
// carries the opcode plus Rd or Rs1, word1's low bits carry the
// immediate/address. That needs an extra fetch cycle (S_FETCH2) between
// DECODE and EXECUTE to pull word1 in before we can act on it.
//
// GETSTOCKPRICE/GETSTOCKPRICEBEFORE are plain 1-word ops: stock_buffers'
// read port is combinational, so the sign-extended value is written back
// on the normal WRITEBACK cycle.
//
// UPDATEALLSTOCKBUFFERS is blocking: DECODE goes to S_WAIT_TICKS instead
// of EXECUTE and sits there, with no timeout, until every buffer has a
// staged tick. buf_advance is asserted for exactly that one cycle, then
// WRITEBACK moves the PC on as usual. With all ticks already waiting it
// takes the same 4 cycles as any other 1-word op.
//
// DIV: DECODE pulses div_start with Rs1/Rs2 (the register file reads are
// combinational off ir, so they're valid in DECODE), then S_DIV_WAIT
// holds until div_done. With divider.v that's 17 cycles in S_DIV_WAIT,
// 20 cycles fetch-to-fetch. Waiting on done rather than a fixed count
// means the Divider Generator IP can replace divider.v without touching
// this FSM.
//
// GETSUMPRICEBEFORE Rd, buf_id, N: imm5 is the WINDOW SIZE N -- the N most
// recent entries including today, i.e. days_before offsets 0..N-1. N=30
// sums the whole buffer, every slot exactly once (no mod-30 aliasing,
// since offsets only run to 29). N=0 sums nothing -> 0 and takes the
// normal 1-word path. imm5=31 is outside the spec's 0-30 range; it clamps
// to 30. Otherwise S_SUM_WAIT reads one entry per cycle through the same
// stock_buffers read port GETSTOCKPRICEBEFORE uses, so it takes exactly N
// cycles (<= 30, spec section 4).
//
// ASSIGNVAR/GETVAR/GETBALANCE/UPDATEBALANCE/SETBALANCE are plain 1-word
// ops on the normal path; every side effect lands on the WRITEBACK cycle
// like a register write. ASSIGNVAR's Rs, UPDATEBALANCE's amount and
// SETBALANCE's value all come from the Rs1 field (same as JMP_IF's Rs).
// UPDATEBALANCE's buf_id is ignored for now -- it's only there for a
// future DECISION_EVENT.
// BALANCE is cash on hand: UPDATEBALANCE SUBTRACTS the amount (buy +,
// sell -); SETBALANCE (0x18, first reserved slot) overwrites it, for
// seeding starting cash.
//
// EMITDECISION (0x19) Rs1, buf_id, imm5: report a trade decision to the
// host as a DECISION_EVENT -- quantity = low 16 bits of Rs1, symbol =
// buf_id, action = buy (1) if imm5 != 0 else sell (0). It does not touch
// BALANCE; a strategy pairs it with UPDATEBALANCE.
//
// EMITBALANCE (0x1A) Rs1: report a 32-bit value to the host as an
// EMIT_BALANCE message -- all 32 bits of Rs1. It doesn't read BALANCE
// itself; a program does GETBALANCE Rx then EMITBALANCE Rx.
//
// Both EMITs hand one message to uart_protocol's outgoing queue:
// msg_kind (0 = decision, 1 = balance) + msg_data (decision fields
// packed {buf_id, action, quantity} in the low 20 bits, or the 32-bit
// value). They hold in S_EXECUTE with msg_valid high until the queue has
// room (msg_ready), hand over on that cycle, then take the normal
// WRITEBACK -- 4 cycles unless the queue is full. One queue, so messages
// go out in the order the program issued them, whatever their kind.
// Truncation/sign-extension for VAR lives in var_store.

module control_unit (
    input  wire        clk,
    input  wire        rst_n,

    output wire        rf_we,
    output wire [2:0]  rf_waddr,
    output wire [31:0] rf_wdata,
    output wire [2:0]  rf_raddr1,
    output wire [2:0]  rf_raddr2,
    input  wire [31:0] rf_rdata1,
    input  wire [31:0] rf_rdata2,

    output wire [4:0]  alu_opcode,
    output wire [31:0] alu_in1,
    output wire [31:0] alu_in2,
    input  wire [31:0] alu_result,

    output wire [2:0]  buf_rd_id,
    output wire [4:0]  buf_rd_days_before,
    input  wire [15:0] buf_rd_data,
    input  wire        buf_all_ticks_pending,
    output wire        buf_advance,

    output wire        div_start,
    output wire [31:0] div_dividend,
    output wire [31:0] div_divisor,
    input  wire        div_done,
    input  wire [31:0] div_quotient,

    output wire [3:0]  var_id,
    output wire        var_we,
    output wire [31:0] var_wdata,
    input  wire [31:0] var_rdata,

    output wire        bal_update_en,
    output wire [31:0] bal_amount,
    output wire        bal_set_en,
    output wire [31:0] bal_set_value,
    input  wire [31:0] bal_value,

    input  wire        pm_we,
    input  wire [8:0]  pm_waddr,
    input  wire [31:0] pm_wdata,

    output wire        msg_valid,
    input  wire        msg_ready,
    output wire        msg_kind,
    output wire [31:0] msg_data
);

    localparam OP_NOP      = 5'h00;
    localparam OP_ADD      = 5'h01;
    localparam OP_SUB      = 5'h02;
    localparam OP_MUL      = 5'h03;
    localparam OP_DIV      = 5'h04;
    localparam OP_CMP_GT   = 5'h05;
    localparam OP_CMP_LT   = 5'h06;
    localparam OP_LOAD_IMM = 5'h09;
    localparam OP_JMP      = 5'h0A;
    localparam OP_JMP_IF   = 5'h0B;
    localparam OP_ASSIGNVAR             = 5'h0C;
    localparam OP_GETVAR                = 5'h0D;
    localparam OP_GETBALANCE            = 5'h0E;
    localparam OP_GETSTOCKPRICE         = 5'h0F;
    localparam OP_GETSTOCKPRICEBEFORE   = 5'h10;
    localparam OP_GETSUMPRICEBEFORE     = 5'h11;
    localparam OP_UPDATEBALANCE         = 5'h12;
    localparam OP_UPDATEALLSTOCKBUFFERS = 5'h13;
    localparam OP_SETBALANCE            = 5'h18;
    localparam OP_EMITDECISION          = 5'h19;
    localparam OP_EMITBALANCE           = 5'h1A;

    localparam S_FETCH     = 3'd0;
    localparam S_DECODE    = 3'd1;
    localparam S_FETCH2    = 3'd2;
    localparam S_EXECUTE   = 3'd3;
    localparam S_WRITEBACK = 3'd4;
    localparam S_WAIT_TICKS = 3'd5;
    localparam S_DIV_WAIT   = 3'd6;
    localparam S_SUM_WAIT   = 3'd7;

    reg [2:0]  state;
    reg [8:0]  pc;           // 512-word prog mem -> 9 bits
    reg [31:0] ir;
    reg [31:0] ir2;          // second word of a two-word instruction

    reg [31:0] sum_acc;      // GETSUMPRICEBEFORE running total
    reg [4:0]  sum_idx;      // days_before offset currently being read

    reg [31:0] prog_mem [0:511];

    always @(posedge clk) begin
        if (pm_we)
            prog_mem[pm_waddr] <= pm_wdata;
    end

    wire [4:0] opcode_f = ir[31:27];
    wire [2:0] rd_f     = ir[26:24];
    wire [2:0] rs1_f    = ir[23:21];
    wire [2:0] rs2_f    = ir[20:18];
    wire [3:0] var_id_f = ir[17:14];
    wire [2:0] buf_id_f = ir[13:11];
    wire [4:0] imm5_f   = ir[10:6];

    wire [8:0] addr_f  = ir2[8:0];   // only low 9 bits matter, 512-word memory
    wire [15:0] imm16_f = ir2[15:0];

    wire is_write_opcode = (opcode_f == OP_ADD)    ||
                            (opcode_f == OP_SUB)    ||
                            (opcode_f == OP_MUL)    ||
                            (opcode_f == OP_CMP_GT) ||
                            (opcode_f == OP_CMP_LT);

    wire is_load_imm = (opcode_f == OP_LOAD_IMM);
    wire is_jmp      = (opcode_f == OP_JMP);
    wire is_jmp_if   = (opcode_f == OP_JMP_IF);
    wire is_two_word = is_load_imm || is_jmp || is_jmp_if;

    wire is_get_price        = (opcode_f == OP_GETSTOCKPRICE);
    wire is_get_price_before = (opcode_f == OP_GETSTOCKPRICEBEFORE);
    wire is_buf_read         = is_get_price || is_get_price_before;
    wire is_update_bufs      = (opcode_f == OP_UPDATEALLSTOCKBUFFERS);

    wire is_div     = (opcode_f == OP_DIV);
    wire is_sum     = (opcode_f == OP_GETSUMPRICEBEFORE);
    wire [4:0] sum_len = (imm5_f > 5'd30) ? 5'd30 : imm5_f;

    wire is_assignvar      = (opcode_f == OP_ASSIGNVAR);
    wire is_getvar         = (opcode_f == OP_GETVAR);
    wire is_getbalance     = (opcode_f == OP_GETBALANCE);
    wire is_updatebalance  = (opcode_f == OP_UPDATEBALANCE);
    wire is_setbalance     = (opcode_f == OP_SETBALANCE);
    wire is_emit_decision  = (opcode_f == OP_EMITDECISION);
    wire is_emit_balance   = (opcode_f == OP_EMITBALANCE);
    wire is_emit           = is_emit_decision || is_emit_balance;

    assign rf_raddr1  = rs1_f;
    assign rf_raddr2  = rs2_f;
    assign alu_opcode = opcode_f;
    assign alu_in1    = rf_rdata1;
    assign alu_in2    = rf_rdata2;

    // GETSTOCKPRICE is just "0 days before"; force it rather than trust
    // the unused imm5 field to be zero
    assign buf_rd_id          = buf_id_f;
    assign buf_rd_days_before = is_get_price_before ? imm5_f  :
                                is_sum              ? sum_idx : 5'd0;
    assign buf_advance        = (state == S_WAIT_TICKS) && buf_all_ticks_pending;

    assign div_start    = (state == S_DECODE) && is_div;
    assign div_dividend = rf_rdata1;
    assign div_divisor  = rf_rdata2;

    assign rf_waddr = rd_f;
    assign rf_wdata = is_load_imm   ? {{16{imm16_f[15]}}, imm16_f} :
                      is_buf_read   ? {{16{buf_rd_data[15]}}, buf_rd_data} :
                      is_div        ? div_quotient :
                      is_sum        ? sum_acc :
                      is_getvar     ? var_rdata :
                      is_getbalance ? bal_value :
                                      alu_result;
    assign rf_we    = (state == S_WRITEBACK) &&
                      (is_write_opcode || is_load_imm || is_buf_read || is_div || is_sum ||
                       is_getvar || is_getbalance);

    assign var_id     = var_id_f;
    assign var_we     = (state == S_WRITEBACK) && is_assignvar;
    assign var_wdata  = rf_rdata1;

    assign bal_update_en = (state == S_WRITEBACK) && is_updatebalance;
    assign bal_amount    = rf_rdata1;
    assign bal_set_en    = (state == S_WRITEBACK) && is_setbalance;
    assign bal_set_value = rf_rdata1;

    assign msg_valid = (state == S_EXECUTE) && is_emit;
    assign msg_kind  = is_emit_balance;
    assign msg_data  = is_emit_balance ? rf_rdata1 :
                       {12'd0, buf_id_f, (imm5_f != 5'd0), rf_rdata1[15:0]};

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state <= S_FETCH;
            pc    <= 9'd0;
            ir    <= 32'd0;
            ir2   <= 32'd0;
            sum_acc <= 32'd0;
            sum_idx <= 5'd0;
        end else begin
            case (state)
                S_FETCH: begin
                    ir    <= prog_mem[pc];
                    state <= S_DECODE;
                end

                S_DECODE: begin
                    if (is_sum) begin
                        sum_acc <= 32'd0;
                        sum_idx <= 5'd0;
                    end

                    if (is_two_word)
                        state <= S_FETCH2;
                    else if (is_update_bufs)
                        state <= S_WAIT_TICKS;
                    else if (is_div)
                        state <= S_DIV_WAIT;
                    else if (is_sum && sum_len != 5'd0)
                        state <= S_SUM_WAIT;
                    else
                        state <= S_EXECUTE;
                end

                S_WAIT_TICKS: begin
                    if (buf_all_ticks_pending)
                        state <= S_WRITEBACK;
                end

                S_DIV_WAIT: begin
                    if (div_done)
                        state <= S_WRITEBACK;
                end

                S_SUM_WAIT: begin
                    sum_acc <= sum_acc + {{16{buf_rd_data[15]}}, buf_rd_data};
                    sum_idx <= sum_idx + 5'd1;
                    if (sum_idx == sum_len - 5'd1)
                        state <= S_WRITEBACK;
                end

                S_FETCH2: begin
                    ir2   <= prog_mem[pc + 9'd1];
                    state <= S_EXECUTE;
                end

                S_EXECUTE: begin
                    // EMITDECISION/EMITBALANCE wait here for queue space
                    if (!is_emit || msg_ready)
                        state <= S_WRITEBACK;
                end

                S_WRITEBACK: begin
                    if (is_jmp)
                        pc <= addr_f;
                    else if (is_jmp_if)
                        pc <= (rf_rdata1 != 32'sd0) ? addr_f : (pc + 9'd2);
                    else if (is_load_imm)
                        pc <= pc + 9'd2;
                    else
                        pc <= pc + 9'd1;

                    state <= S_FETCH;
                end

                default: state <= S_FETCH;
            endcase
        end
    end

endmodule
