`timescale 1ns/1ps

// Stage 5 exit criteria: a buy-then-sell sequence produces the
// hand-calculated balance. Also: ASSIGNVAR truncation / GETVAR
// sign-extension, and VAR / BALANCE / R0-R7 being independent storage.
//
// Operand fields (spec section 3): ASSIGNVAR's Rs and UPDATEBALANCE's
// amount are in the Rs1 field; var_id is bits [17:14]; buf_id [13:11].
//
// ======================= expected results ==========================
//
// All five new opcodes take the normal 4 cycles fetch-to-fetch and never
// enter a wait state (S_WAIT_TICKS / S_DIV_WAIT / S_SUM_WAIT).
//
// Test 1 -- seed, buy, then sell (amounts in cents, precomputed with MUL
// the way the compiler would; the FPGA never multiplies)
//   BALANCE is cash on hand. SETBALANCE overwrites it; UPDATEBALANCE
//   does BALANCE -= amount, with the opcode's "positive = buy,
//   negative = sell" convention.
//   R0 = 777 sentinel (SET/UPDATEBALANCE must not write the register file)
//   seed: SETBALANCE $10,000.00 -> 10000 * 100 = 1000000
//   buy : 10 shares x $150.25 -> amount  15025 * 10 =  150250, on buf 2
//   sell: 10 shares x $162.40 -> amount -16240 * 10 = -162400, on buf 4
//   R7 = GETBALANCE after seed = 1000000
//   R4 = GETBALANCE after buy  = 1000000 -   150250   =  849750
//   R5 = GETBALANCE after sell = 849750  - (-162400)  = 1012150
//   BALANCE = 1012150 -> profit 1012150 - 1000000 = 12150 = $121.50
//   R6 = 1000000, R3 = -162400 (source regs unchanged), R0 = 777
//
// Test 2 -- ASSIGNVAR truncation, GETVAR sign-extension
//   a) R1 = 24855*3 = 74565  = 0x0001_2345 -> VAR[3]  = 0x2345 -> R3 =   9029
//   b) R4 = 10923*3 = 32769  = 0x0000_8001 -> VAR[14] = 0x8001 -> R5 = -32767
//      (positive 32-bit value whose low half has bit 15 set -> reads back negative)
//   c) R6 = -7000*10 = -70000 = 0xFFFE_EE90 -> VAR[0] = 0xEE90 -> R7 =  -4464
//   d) R0 = -1234 = 0xFFFF_FB2E (fits) -> VAR[7] = 0xFB2E -> R2 = -1234
//   Source regs unchanged: R1 = 74565, R4 = 32769, R6 = -70000
//   Every other slot (1,2,4,5,6,8..13) still 0
//
// Test 3 -- independence (VAR[3] vs R3 vs BALANCE)
//   R3 = 1111; R1 = 2222; ASSIGNVAR VAR[3] <- R1
//   R2 = 5000; UPDATEBALANCE R2              -> BALANCE = 0 - 5000 = -5000
//   R3 = 3333 (overwrite R3)
//   R4 = GETVAR VAR[3]  = 2222   (R3 write didn't touch VAR[3];
//                                 ASSIGNVAR didn't touch R3 or BALANCE)
//   R5 = GETBALANCE     = -5000  (VAR write didn't touch BALANCE)
//   ASSIGNVAR VAR[3] <- R3 (3333)
//   R6 = GETBALANCE     = -5000  (second VAR write, BALANCE still -5000)
//   R7 = GETVAR VAR[3]  = 3333
//   ASSIGNVAR VAR[15] <- R2 (out of range, dropped)
//   R1 = GETVAR VAR[15] = 0      (out of range reads 0; R1 was 2222)
//   Final: R2 = 5000, R3 = 3333, BALANCE = -5000, VAR[3] = 3333,
//          every other VAR slot 0
//
// Test 4 -- SETBALANCE overwrites (doesn't add or subtract)
//   R0 = 999 sentinel (SETBALANCE must not write the register file)
//   UPDATEBALANCE +5000         -> BALANCE = -5000       (R2 reads it)
//   SETBALANCE R3 = 777         -> BALANCE = 777         (R4)
//        (an add would give -4223, a subtract -5777)
//   SETBALANCE R5 = -42         -> BALANCE = -42         (R6)
//        (a negative value is set as-is, no sign flip)
//   R3 = 777, R5 = -42 unchanged, R0 = 999
// ===================================================================

module tb_stage5_core;

    localparam OP_MUL           = 5'h03;
    localparam OP_LOAD_IMM      = 5'h09;
    localparam OP_JMP           = 5'h0A;
    localparam OP_ASSIGNVAR     = 5'h0C;
    localparam OP_GETVAR        = 5'h0D;
    localparam OP_GETBALANCE    = 5'h0E;
    localparam OP_UPDATEBALANCE = 5'h12;
    localparam OP_SETBALANCE    = 5'h18;

    localparam S_FETCH = 3'd0;

    reg clk;
    reg rst_n;
    integer errors;

    // per-instruction length for the five Stage 5 opcodes
    integer instr_len, new_ops, new_ops_not_4, wait_state_cycles;
    wire [4:0] cur_op = dut.u_control_unit.ir[31:27];

    tradecpu_core dut (
        .clk         (clk),
        .rst_n       (rst_n),
        .tick_valid  (1'b0),   // no ticks in this stage's tests
        .tick_buf_id (3'd0),
        .tick_price  (16'd0),
        .UART_RXD    (1'b1)    // serial line idle
    );

    always #5 clk = ~clk;

    always @(posedge clk) begin
        if (rst_n) begin
            if (dut.u_control_unit.state >= 3'd5)
                wait_state_cycles = wait_state_cycles + 1;

            // ir still holds the instruction that just finished
            if (dut.u_control_unit.state == S_FETCH) begin
                if (instr_len != 0 &&
                    (cur_op == OP_ASSIGNVAR  || cur_op == OP_GETVAR ||
                     cur_op == OP_GETBALANCE || cur_op == OP_UPDATEBALANCE ||
                     cur_op == OP_SETBALANCE)) begin
                    new_ops = new_ops + 1;
                    if (instr_len != 4)
                        new_ops_not_4 = new_ops_not_4 + 1;
                end
                instr_len = 1;
            end else begin
                instr_len = instr_len + 1;
            end
        end
    end

    function [31:0] encode_r3;
        input [4:0] opc;
        input [2:0] rd, rs1, rs2;
        begin
            encode_r3 = {opc, rd, rs1, rs2, 4'd0, 3'd0, 5'd0, 6'd0};
        end
    endfunction

    function [31:0] encode_var;
        input [4:0] opc;
        input [2:0] rd, rs1;
        input [3:0] var_id;
        begin
            encode_var = {opc, rd, rs1, 3'd0, var_id, 3'd0, 5'd0, 6'd0};
        end
    endfunction

    function [31:0] encode_bal;
        input [4:0] opc;
        input [2:0] rd, rs1, buf_id;
        begin
            encode_bal = {opc, rd, rs1, 3'd0, 4'd0, buf_id, 5'd0, 6'd0};
        end
    endfunction

    function [31:0] encode_word16;
        input [15:0] val;
        begin
            encode_word16 = {16'd0, val};
        end
    endfunction

    task check32;
        input [8*48-1:0]    label;
        input signed [31:0] actual;
        input signed [31:0] expected;
        begin
            if (actual !== expected) begin
                $display("FAIL: %0s -- got %0d, expected %0d", label, actual, expected);
                errors = errors + 1;
            end else begin
                $display("PASS: %0s -- %0d", label, actual);
            end
        end
    endtask

    task check_true;
        input [8*48-1:0] label;
        input            cond;
        begin
            if (cond !== 1'b1) begin
                $display("FAIL: %0s", label);
                errors = errors + 1;
            end else begin
                $display("PASS: %0s", label);
            end
        end
    endtask

    task check_timing;
        input [8*48-1:0] label;
        input integer    expected_ops;
        begin
            check32(label, new_ops, expected_ops);
            check32("  of those, not 4 cycles", new_ops_not_4, 0);
            check32("  cycles in any wait state", wait_state_cycles, 0);
        end
    endtask

    task reset_dut;
        begin
            rst_n = 0;
            @(negedge clk);
            @(negedge clk);
            instr_len         = 0;
            new_ops           = 0;
            new_ops_not_4     = 0;
            wait_state_cycles = 0;
            rst_n = 1;
        end
    endtask

    initial begin
        errors = 0;
        clk    = 0;

        // ---------------- Test 1: buy then sell ----------------
        reset_dut();
        dut.u_control_unit.prog_mem[0]  = encode_r3(OP_LOAD_IMM, 3'd0, 3'd0, 3'd0);
        dut.u_control_unit.prog_mem[1]  = encode_word16(16'd777);
        // seed: $10,000.00 starting cash
        dut.u_control_unit.prog_mem[2]  = encode_r3(OP_LOAD_IMM, 3'd6, 3'd0, 3'd0);
        dut.u_control_unit.prog_mem[3]  = encode_word16(16'd10000);
        dut.u_control_unit.prog_mem[4]  = encode_r3(OP_LOAD_IMM, 3'd7, 3'd0, 3'd0);
        dut.u_control_unit.prog_mem[5]  = encode_word16(16'd100);
        dut.u_control_unit.prog_mem[6]  = encode_r3(OP_MUL, 3'd6, 3'd6, 3'd7);
        dut.u_control_unit.prog_mem[7]  = encode_bal(OP_SETBALANCE,    3'd0, 3'd6, 3'd0);
        dut.u_control_unit.prog_mem[8]  = encode_bal(OP_GETBALANCE,    3'd7, 3'd0, 3'd0);
        // buy 10 @ $150.25
        dut.u_control_unit.prog_mem[9]  = encode_r3(OP_LOAD_IMM, 3'd2, 3'd0, 3'd0);
        dut.u_control_unit.prog_mem[10] = encode_word16(16'd10);
        dut.u_control_unit.prog_mem[11] = encode_r3(OP_LOAD_IMM, 3'd1, 3'd0, 3'd0);
        dut.u_control_unit.prog_mem[12] = encode_word16(16'd15025);
        dut.u_control_unit.prog_mem[13] = encode_r3(OP_MUL, 3'd3, 3'd1, 3'd2);
        dut.u_control_unit.prog_mem[14] = encode_bal(OP_UPDATEBALANCE, 3'd0, 3'd3, 3'd2);
        dut.u_control_unit.prog_mem[15] = encode_bal(OP_GETBALANCE,    3'd4, 3'd0, 3'd0);
        // sell 10 @ $162.40
        dut.u_control_unit.prog_mem[16] = encode_r3(OP_LOAD_IMM, 3'd1, 3'd0, 3'd0);
        dut.u_control_unit.prog_mem[17] = encode_word16(-16'sd16240);
        dut.u_control_unit.prog_mem[18] = encode_r3(OP_MUL, 3'd3, 3'd1, 3'd2);
        dut.u_control_unit.prog_mem[19] = encode_bal(OP_UPDATEBALANCE, 3'd0, 3'd3, 3'd4);
        dut.u_control_unit.prog_mem[20] = encode_bal(OP_GETBALANCE,    3'd5, 3'd0, 3'd0);
        dut.u_control_unit.prog_mem[21] = encode_r3(OP_JMP, 3'd0, 3'd0, 3'd0);
        dut.u_control_unit.prog_mem[22] = encode_word16(16'd21);

        repeat (120) @(negedge clk);
        check32("T1: R7 balance after seed",           dut.u_register_file.registers[7], 32'sd1000000);
        check32("T1: R4 balance after buy (-150250)",  dut.u_register_file.registers[4], 32'sd849750);
        check32("T1: R5 balance after sell (+162400)", dut.u_register_file.registers[5], 32'sd1012150);
        check32("T1: BALANCE register (final)",        dut.u_balance_reg.balance, 32'sd1012150);
        check32("T1: profit = final - seed",
                dut.u_balance_reg.balance - 32'sd1000000, 32'sd12150);
        check32("T1: R6 seed value unchanged",         dut.u_register_file.registers[6], 32'sd1000000);
        check32("T1: R3 sell amount unchanged",        dut.u_register_file.registers[3], -32'sd162400);
        check32("T1: R0 sentinel (no rf write)",       dut.u_register_file.registers[0], 32'sd777);
        check_timing("T1: Stage 5 ops executed", 6);

        // ---------------- Test 2: truncation / sign-extension ----------------
        reset_dut();
        dut.u_control_unit.prog_mem[0]  = encode_r3(OP_LOAD_IMM, 3'd1, 3'd0, 3'd0);
        dut.u_control_unit.prog_mem[1]  = encode_word16(16'd24855);
        dut.u_control_unit.prog_mem[2]  = encode_r3(OP_LOAD_IMM, 3'd2, 3'd0, 3'd0);
        dut.u_control_unit.prog_mem[3]  = encode_word16(16'd3);
        dut.u_control_unit.prog_mem[4]  = encode_r3(OP_MUL, 3'd1, 3'd1, 3'd2);
        dut.u_control_unit.prog_mem[5]  = encode_var(OP_ASSIGNVAR, 3'd0, 3'd1, 4'd3);
        dut.u_control_unit.prog_mem[6]  = encode_var(OP_GETVAR,    3'd3, 3'd0, 4'd3);
        dut.u_control_unit.prog_mem[7]  = encode_r3(OP_LOAD_IMM, 3'd4, 3'd0, 3'd0);
        dut.u_control_unit.prog_mem[8]  = encode_word16(16'd10923);
        dut.u_control_unit.prog_mem[9]  = encode_r3(OP_MUL, 3'd4, 3'd4, 3'd2);
        dut.u_control_unit.prog_mem[10] = encode_var(OP_ASSIGNVAR, 3'd0, 3'd4, 4'd14);
        dut.u_control_unit.prog_mem[11] = encode_var(OP_GETVAR,    3'd5, 3'd0, 4'd14);
        dut.u_control_unit.prog_mem[12] = encode_r3(OP_LOAD_IMM, 3'd6, 3'd0, 3'd0);
        dut.u_control_unit.prog_mem[13] = encode_word16(-16'sd7000);
        dut.u_control_unit.prog_mem[14] = encode_r3(OP_LOAD_IMM, 3'd7, 3'd0, 3'd0);
        dut.u_control_unit.prog_mem[15] = encode_word16(16'd10);
        dut.u_control_unit.prog_mem[16] = encode_r3(OP_MUL, 3'd6, 3'd6, 3'd7);
        dut.u_control_unit.prog_mem[17] = encode_var(OP_ASSIGNVAR, 3'd0, 3'd6, 4'd0);
        dut.u_control_unit.prog_mem[18] = encode_var(OP_GETVAR,    3'd7, 3'd0, 4'd0);
        dut.u_control_unit.prog_mem[19] = encode_r3(OP_LOAD_IMM, 3'd0, 3'd0, 3'd0);
        dut.u_control_unit.prog_mem[20] = encode_word16(-16'sd1234);
        dut.u_control_unit.prog_mem[21] = encode_var(OP_ASSIGNVAR, 3'd0, 3'd0, 4'd7);
        dut.u_control_unit.prog_mem[22] = encode_var(OP_GETVAR,    3'd2, 3'd0, 4'd7);
        dut.u_control_unit.prog_mem[23] = encode_r3(OP_JMP, 3'd0, 3'd0, 3'd0);
        dut.u_control_unit.prog_mem[24] = encode_word16(16'd23);

        repeat (150) @(negedge clk);
        check32("T2a: VAR[3] raw = 0x2345",           dut.u_var_store.vars[3],  32'h2345);
        check32("T2a: R3 = GETVAR 3",                 dut.u_register_file.registers[3], 32'sd9029);
        check32("T2a: R1 source unchanged",           dut.u_register_file.registers[1], 32'sd74565);
        check32("T2b: VAR[14] raw = 0x8001",          dut.u_var_store.vars[14], 32'h8001);
        check32("T2b: R5 = GETVAR 14 (sign-ext)",     dut.u_register_file.registers[5], -32'sd32767);
        check32("T2b: R4 source unchanged",           dut.u_register_file.registers[4], 32'sd32769);
        check32("T2c: VAR[0] raw = 0xEE90",           dut.u_var_store.vars[0],  32'hEE90);
        check32("T2c: R7 = GETVAR 0 (sign-ext)",      dut.u_register_file.registers[7], -32'sd4464);
        check32("T2c: R6 source unchanged",           dut.u_register_file.registers[6], -32'sd70000);
        check32("T2d: VAR[7] raw = 0xFB2E",           dut.u_var_store.vars[7],  32'hFB2E);
        check32("T2d: R2 = GETVAR 7 (in range)",      dut.u_register_file.registers[2], -32'sd1234);
        check_true("T2: untouched VAR slots still 0",
                   dut.u_var_store.vars[1]  == 0 && dut.u_var_store.vars[2]  == 0 &&
                   dut.u_var_store.vars[4]  == 0 && dut.u_var_store.vars[5]  == 0 &&
                   dut.u_var_store.vars[6]  == 0 && dut.u_var_store.vars[8]  == 0 &&
                   dut.u_var_store.vars[9]  == 0 && dut.u_var_store.vars[10] == 0 &&
                   dut.u_var_store.vars[11] == 0 && dut.u_var_store.vars[12] == 0 &&
                   dut.u_var_store.vars[13] == 0);
        check32("T2: BALANCE untouched", dut.u_balance_reg.balance, 0);
        check_timing("T2: Stage 5 ops executed", 8);

        // ---------------- Test 3: independence ----------------
        reset_dut();
        dut.u_control_unit.prog_mem[0]  = encode_r3(OP_LOAD_IMM, 3'd3, 3'd0, 3'd0);
        dut.u_control_unit.prog_mem[1]  = encode_word16(16'd1111);
        dut.u_control_unit.prog_mem[2]  = encode_r3(OP_LOAD_IMM, 3'd1, 3'd0, 3'd0);
        dut.u_control_unit.prog_mem[3]  = encode_word16(16'd2222);
        dut.u_control_unit.prog_mem[4]  = encode_var(OP_ASSIGNVAR, 3'd0, 3'd1, 4'd3);
        dut.u_control_unit.prog_mem[5]  = encode_r3(OP_LOAD_IMM, 3'd2, 3'd0, 3'd0);
        dut.u_control_unit.prog_mem[6]  = encode_word16(16'd5000);
        dut.u_control_unit.prog_mem[7]  = encode_bal(OP_UPDATEBALANCE, 3'd0, 3'd2, 3'd0);
        dut.u_control_unit.prog_mem[8]  = encode_r3(OP_LOAD_IMM, 3'd3, 3'd0, 3'd0);
        dut.u_control_unit.prog_mem[9]  = encode_word16(16'd3333);
        dut.u_control_unit.prog_mem[10] = encode_var(OP_GETVAR,        3'd4, 3'd0, 4'd3);
        dut.u_control_unit.prog_mem[11] = encode_bal(OP_GETBALANCE,    3'd5, 3'd0, 3'd0);
        dut.u_control_unit.prog_mem[12] = encode_var(OP_ASSIGNVAR,     3'd0, 3'd3, 4'd3);
        dut.u_control_unit.prog_mem[13] = encode_bal(OP_GETBALANCE,    3'd6, 3'd0, 3'd0);
        dut.u_control_unit.prog_mem[14] = encode_var(OP_GETVAR,        3'd7, 3'd0, 4'd3);
        dut.u_control_unit.prog_mem[15] = encode_var(OP_ASSIGNVAR,     3'd0, 3'd2, 4'd15);
        dut.u_control_unit.prog_mem[16] = encode_var(OP_GETVAR,        3'd1, 3'd0, 4'd15);
        dut.u_control_unit.prog_mem[17] = encode_r3(OP_JMP, 3'd0, 3'd0, 3'd0);
        dut.u_control_unit.prog_mem[18] = encode_word16(16'd17);

        repeat (120) @(negedge clk);
        check32("T3: R4 VAR[3] survived R3 write",     dut.u_register_file.registers[4], 32'sd2222);
        check32("T3: R5 BALANCE survived VAR write",   dut.u_register_file.registers[5], -32'sd5000);
        check32("T3: R6 BALANCE after 2nd VAR write",  dut.u_register_file.registers[6], -32'sd5000);
        check32("T3: R7 VAR[3] rewritten from R3",     dut.u_register_file.registers[7], 32'sd3333);
        check32("T3: R1 GETVAR 15 (out of range)",     dut.u_register_file.registers[1], 32'sd0);
        check32("T3: R3 untouched by VAR/BALANCE ops", dut.u_register_file.registers[3], 32'sd3333);
        check32("T3: R2 untouched by UPDATEBALANCE",   dut.u_register_file.registers[2], 32'sd5000);
        check32("T3: BALANCE register",                dut.u_balance_reg.balance, -32'sd5000);
        check32("T3: VAR[3] raw",                      dut.u_var_store.vars[3], 32'sd3333);
        check_true("T3: other VAR slots 0 (VAR[15] write dropped)",
                   dut.u_var_store.vars[0]  == 0 && dut.u_var_store.vars[1]  == 0 &&
                   dut.u_var_store.vars[2]  == 0 && dut.u_var_store.vars[4]  == 0 &&
                   dut.u_var_store.vars[5]  == 0 && dut.u_var_store.vars[6]  == 0 &&
                   dut.u_var_store.vars[7]  == 0 && dut.u_var_store.vars[8]  == 0 &&
                   dut.u_var_store.vars[9]  == 0 && dut.u_var_store.vars[10] == 0 &&
                   dut.u_var_store.vars[11] == 0 && dut.u_var_store.vars[12] == 0 &&
                   dut.u_var_store.vars[13] == 0 && dut.u_var_store.vars[14] == 0);
        check_timing("T3: Stage 5 ops executed", 9);

        // ---------------- Test 4: SETBALANCE overwrites ----------------
        reset_dut();
        dut.u_control_unit.prog_mem[0]  = encode_r3(OP_LOAD_IMM, 3'd0, 3'd0, 3'd0);
        dut.u_control_unit.prog_mem[1]  = encode_word16(16'd999);
        dut.u_control_unit.prog_mem[2]  = encode_r3(OP_LOAD_IMM, 3'd1, 3'd0, 3'd0);
        dut.u_control_unit.prog_mem[3]  = encode_word16(16'd5000);
        dut.u_control_unit.prog_mem[4]  = encode_bal(OP_UPDATEBALANCE, 3'd0, 3'd1, 3'd0);
        dut.u_control_unit.prog_mem[5]  = encode_bal(OP_GETBALANCE,    3'd2, 3'd0, 3'd0);
        dut.u_control_unit.prog_mem[6]  = encode_r3(OP_LOAD_IMM, 3'd3, 3'd0, 3'd0);
        dut.u_control_unit.prog_mem[7]  = encode_word16(16'd777);
        dut.u_control_unit.prog_mem[8]  = encode_bal(OP_SETBALANCE,    3'd0, 3'd3, 3'd0);
        dut.u_control_unit.prog_mem[9]  = encode_bal(OP_GETBALANCE,    3'd4, 3'd0, 3'd0);
        dut.u_control_unit.prog_mem[10] = encode_r3(OP_LOAD_IMM, 3'd5, 3'd0, 3'd0);
        dut.u_control_unit.prog_mem[11] = encode_word16(-16'sd42);
        dut.u_control_unit.prog_mem[12] = encode_bal(OP_SETBALANCE,    3'd0, 3'd5, 3'd0);
        dut.u_control_unit.prog_mem[13] = encode_bal(OP_GETBALANCE,    3'd6, 3'd0, 3'd0);
        dut.u_control_unit.prog_mem[14] = encode_r3(OP_JMP, 3'd0, 3'd0, 3'd0);
        dut.u_control_unit.prog_mem[15] = encode_word16(16'd14);

        repeat (100) @(negedge clk);
        check32("T4: R2 after UPDATEBALANCE +5000",  dut.u_register_file.registers[2], -32'sd5000);
        check32("T4: R4 after SETBALANCE 777",       dut.u_register_file.registers[4], 32'sd777);
        check32("T4: R6 after SETBALANCE -42",       dut.u_register_file.registers[6], -32'sd42);
        check32("T4: BALANCE register (final)",      dut.u_balance_reg.balance, -32'sd42);
        check32("T4: R3 source unchanged",           dut.u_register_file.registers[3], 32'sd777);
        check32("T4: R5 source unchanged",           dut.u_register_file.registers[5], -32'sd42);
        check32("T4: R0 sentinel (no rf write)",     dut.u_register_file.registers[0], 32'sd999);
        check_timing("T4: Stage 5 ops executed", 6);

        if (errors == 0)
            $display("tb_stage5_core: ALL TESTS PASSED -- Stage 5 exit criteria met");
        else
            $display("tb_stage5_core: %0d TEST(S) FAILED", errors);

        $finish;
    end

endmodule
