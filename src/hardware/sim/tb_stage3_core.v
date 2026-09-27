`timescale 1ns/1ps

// Stage 3 exit criteria: wraparound (day 31 on a 30-deep buffer) is
// correct, and UPDATEALLSTOCKBUFFERS blocks correctly both when ticks are
// already waiting and when they haven't arrived yet. Also checks that
// GETSTOCKPRICE reads without advancing anything.
//
// The testbench plays the Stage 6 UART TICK decoder: stage_tick() drives
// one 1-cycle tick_valid strobe with buf_id + price.
//
// Buffer contents survive rst_n (LUTRAM, see stock_buffers.v); only heads
// and staging reset. So every read below targets a slot the same test
// wrote after its own reset. Heads reset to 0, so the Nth advance after
// reset writes slot (N mod 30).
//
// ======================= expected results ==========================
//
// Test 1 -- wraparound
//   price(b, d) = b*1000 + d, for days d = 1..31, all 5 buffers.
//   Day d lands in slot d mod 30:
//     day 1->slot 1 ... day 29->slot 29, day 30->slot 0 (wrap),
//     day 31->slot 1 (overwrites day 1)
//   After day 30: head = 0, BUF[1][0] = 1030
//   After day 31: head = 1 in all 5 buffers, BUF[1][1] = 1031 (not 1001)
//   program:
//     0-1:  LOAD_IMM R1, 31
//     2-3:  LOAD_IMM R2, 1
//     4:    LOOP: UPDATEALLSTOCKBUFFERS
//     5:    SUB    R1, R1, R2
//     6:    CMP_GT R3, R1, R0
//     7-8:  JMP_IF R3, LOOP(=4)
//     9:    GETSTOCKPRICE       R1, buf1      -> day 31          = 1031
//     10:   GETSTOCKPRICEBEFORE R2, buf1, 1   -> slot 0,  day 30 = 1030
//     11:   GETSTOCKPRICEBEFORE R3, buf1, 2   -> slot 29, day 29 = 1029
//                                              (1-2 wraps to 29)
//     12:   GETSTOCKPRICEBEFORE R4, buf1, 29  -> slot 2,  day 2  = 1002
//                                              (oldest surviving entry)
//     13:   GETSTOCKPRICEBEFORE R5, buf3, 15  -> slot 16, day 16 = 3016
//     14:   GETSTOCKPRICEBEFORE R6, buf4, 0   -> slot 1,  day 31 = 4031
//     15:   GETSTOCKPRICE       R7, buf0      -> day 31          = 31
//     16-17: JMP 16 (park)
//
// Test 2 -- blocking scenario A, tick already waiting
//   program: 0-19 NOP (80 cycles of lead time), 20 UPDATEALLSTOCKBUFFERS,
//            21 GETSTOCKPRICE R1,buf0; 22 R2,buf2; 23 R3,buf4; 24-25 JMP 24
//   All 5 ticks staged right after reset (price = b*100 + 7), long before
//   the CPU reaches addr 20.
//   Before addr 20: tick_pending = 5'b11111, heads = 0, no advance yet
//   After:  S_WAIT_TICKS for exactly 1 cycle (no stall), exactly 1
//           advance, heads = 1, tick_pending = 0,
//           R1 = 7, R2 = 207, R3 = 407
//
// Test 3 -- blocking scenario B, tick not yet arrived
//   program: 0 UPDATEALLSTOCKBUFFERS; 1 GETSTOCKPRICE R1,buf0;
//            2 R2,buf1; 3 R3,buf3; 4 R4,buf4; 5 R6,buf2;
//            6-7 LOAD_IMM R5, 999; 8-9 JMP 8
//   step 1: stage buf0=11, buf1=1011, buf3=3011, wait 50 cycles
//     -> stalled: state = S_WAIT_TICKS, pc = 0, 0 advances, heads = 0,
//        tick_pending = 5'b01011, R1..R6 = 0, slot 1 of every buffer
//        unchanged from its post-reset snapshot
//   step 2: stage buf2=2011, wait 50 -> still stalled, pending = 5'b01111
//   step 3: re-stage buf0=12 (replaces 11), wait 20 -> still stalled,
//           buf0 staged price = 12
//   step 4: stage buf4=-411 (the last missing tick), wait 40
//     -> exactly 1 advance, heads = 1, pending = 0,
//        R1 = 12, R2 = 1011, R3 = 3011, R4 = -411 (sign-extended),
//        R6 = 2011, R5 = 999, and more than 100 cycles spent in
//        S_WAIT_TICKS (it really stalled)
//
// Test 4 -- GETSTOCKPRICE doesn't advance or modify anything
//   program: 0 UPDATEALLSTOCKBUFFERS; 1,2,3,5 GETSTOCKPRICE R1/R2/R3/R5, buf2;
//            4 GETSTOCKPRICEBEFORE R4, buf2, 0; 6-7 JMP 6
//   ticks: 50, 150, -1234 (buf2), 350, 450. Right after the advance,
//   stage next day's buf2 = 777 (staged, never advanced).
//   -> R1..R5 = -1234 (0xFFFFFB2E, sign-extended), exactly 1 advance,
//      heads = 1, BUF[2][1] = -1234, pending = 5'b00100 (777 still
//      staged, not visible to reads), buf2 staged price = 777
// ===================================================================

module tb_stage3_core;

    localparam OP_NOP                   = 5'h00;
    localparam OP_SUB                   = 5'h02;
    localparam OP_CMP_GT                = 5'h05;
    localparam OP_LOAD_IMM              = 5'h09;
    localparam OP_JMP                   = 5'h0A;
    localparam OP_JMP_IF                = 5'h0B;
    localparam OP_GETSTOCKPRICE         = 5'h0F;
    localparam OP_GETSTOCKPRICEBEFORE   = 5'h10;
    localparam OP_UPDATEALLSTOCKBUFFERS = 5'h13;

    localparam S_WAIT_TICKS = 3'd5;

    reg        clk;
    reg        rst_n;
    reg        tick_valid;
    reg [2:0]  tick_buf_id;
    reg [15:0] tick_price;

    integer errors;
    integer wait_cycles;
    integer advance_count;
    integer day, b, guard;
    reg [15:0] snap [0:4];

    tradecpu_core dut (
        .clk         (clk),
        .rst_n       (rst_n),
        .tick_valid  (tick_valid),
        .tick_buf_id (tick_buf_id),
        .tick_price  (tick_price),
        .UART_RXD    (1'b1)    // serial line idle
    );

    always #5 clk = ~clk;

    // how long the FSM sits blocked, and how many advances actually fire
    always @(posedge clk) begin
        if (rst_n) begin
            if (dut.u_control_unit.state == S_WAIT_TICKS)
                wait_cycles = wait_cycles + 1;
            if (dut.u_control_unit.buf_advance)
                advance_count = advance_count + 1;
        end
    end

    function [31:0] encode_r3;
        input [4:0] opc;
        input [2:0] rd, rs1, rs2;
        begin
            encode_r3 = {opc, rd, rs1, rs2, 4'd0, 3'd0, 5'd0, 6'd0};
        end
    endfunction

    function [31:0] encode_buf;
        input [4:0] opc;
        input [2:0] rd, buf_id;
        input [4:0] days_before;
        begin
            encode_buf = {opc, rd, 3'd0, 3'd0, 4'd0, buf_id, days_before, 6'd0};
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

    task check_heads;
        input [8*48-1:0] label;
        input [4:0]      expected;
        begin
            check_true(label,
                (dut.u_stock_buffers.g_buf[0].head == expected) &&
                (dut.u_stock_buffers.g_buf[1].head == expected) &&
                (dut.u_stock_buffers.g_buf[2].head == expected) &&
                (dut.u_stock_buffers.g_buf[3].head == expected) &&
                (dut.u_stock_buffers.g_buf[4].head == expected));
        end
    endtask

    task reset_dut;
        begin
            rst_n       = 0;
            tick_valid  = 0;
            tick_buf_id = 3'd0;
            tick_price  = 16'd0;
            @(negedge clk);
            @(negedge clk);
            wait_cycles   = 0;
            advance_count = 0;
            rst_n = 1;
        end
    endtask

    // one decoded TICK message, as Stage 6's UART decoder will present it
    task stage_tick;
        input [2:0]  id;
        input [15:0] price;
        begin
            tick_valid  = 1;
            tick_buf_id = id;
            tick_price  = price;
            @(negedge clk);
            tick_valid  = 0;
        end
    endtask

    task wait_ticks_consumed;
        begin
            guard = 0;
            while (dut.u_stock_buffers.tick_pending != 5'd0 && guard < 500) begin
                @(negedge clk);
                guard = guard + 1;
            end
            if (guard >= 500) begin
                $display("FAIL: timed out waiting for UPDATEALLSTOCKBUFFERS to consume ticks");
                errors = errors + 1;
            end
        end
    endtask

    initial begin
        errors = 0;
        clk    = 0;

        // ---------------- Test 1: wraparound ----------------
        reset_dut();
        dut.u_control_unit.prog_mem[0]  = encode_r3(OP_LOAD_IMM, 3'd1, 3'd0, 3'd0);
        dut.u_control_unit.prog_mem[1]  = encode_word16(16'd31);
        dut.u_control_unit.prog_mem[2]  = encode_r3(OP_LOAD_IMM, 3'd2, 3'd0, 3'd0);
        dut.u_control_unit.prog_mem[3]  = encode_word16(16'd1);
        dut.u_control_unit.prog_mem[4]  = encode_r3(OP_UPDATEALLSTOCKBUFFERS, 3'd0, 3'd0, 3'd0);
        dut.u_control_unit.prog_mem[5]  = encode_r3(OP_SUB, 3'd1, 3'd1, 3'd2);
        dut.u_control_unit.prog_mem[6]  = encode_r3(OP_CMP_GT, 3'd3, 3'd1, 3'd0);
        dut.u_control_unit.prog_mem[7]  = encode_r3(OP_JMP_IF, 3'd0, 3'd3, 3'd0);
        dut.u_control_unit.prog_mem[8]  = encode_word16(16'd4);
        dut.u_control_unit.prog_mem[9]  = encode_buf(OP_GETSTOCKPRICE,       3'd1, 3'd1, 5'd0);
        dut.u_control_unit.prog_mem[10] = encode_buf(OP_GETSTOCKPRICEBEFORE, 3'd2, 3'd1, 5'd1);
        dut.u_control_unit.prog_mem[11] = encode_buf(OP_GETSTOCKPRICEBEFORE, 3'd3, 3'd1, 5'd2);
        dut.u_control_unit.prog_mem[12] = encode_buf(OP_GETSTOCKPRICEBEFORE, 3'd4, 3'd1, 5'd29);
        dut.u_control_unit.prog_mem[13] = encode_buf(OP_GETSTOCKPRICEBEFORE, 3'd5, 3'd3, 5'd15);
        dut.u_control_unit.prog_mem[14] = encode_buf(OP_GETSTOCKPRICEBEFORE, 3'd6, 3'd4, 5'd0);
        dut.u_control_unit.prog_mem[15] = encode_buf(OP_GETSTOCKPRICE,       3'd7, 3'd0, 5'd0);
        dut.u_control_unit.prog_mem[16] = encode_r3(OP_JMP, 3'd0, 3'd0, 3'd0);
        dut.u_control_unit.prog_mem[17] = encode_word16(16'd16);

        for (day = 1; day <= 31; day = day + 1) begin
            for (b = 0; b < 5; b = b + 1)
                stage_tick(b[2:0], b * 1000 + day);
            wait_ticks_consumed();
            if (day == 30) begin
                check_heads("T1: day 30 -> all heads wrapped to 0", 5'd0);
                check32("T1: day 30 -> BUF[1][0]",
                        $signed(dut.u_stock_buffers.g_buf[1].mem[0]), 32'sd1030);
            end
        end

        repeat (100) @(negedge clk);
        check32("T1: advances fired",               advance_count, 31);
        check_heads("T1: day 31 -> all heads = 1", 5'd1);
        check32("T1: BUF[1][1] overwritten (not 1001)",
                $signed(dut.u_stock_buffers.g_buf[1].mem[1]), 32'sd1031);
        check32("T1: R1 GETSTOCKPRICE buf1",        dut.u_register_file.registers[1], 32'sd1031);
        check32("T1: R2 BEFORE buf1,1 (slot 0)",    dut.u_register_file.registers[2], 32'sd1030);
        check32("T1: R3 BEFORE buf1,2 (wraps->29)", dut.u_register_file.registers[3], 32'sd1029);
        check32("T1: R4 BEFORE buf1,29 (oldest)",   dut.u_register_file.registers[4], 32'sd1002);
        check32("T1: R5 BEFORE buf3,15",            dut.u_register_file.registers[5], 32'sd3016);
        check32("T1: R6 BEFORE buf4,0",             dut.u_register_file.registers[6], 32'sd4031);
        check32("T1: R7 GETSTOCKPRICE buf0",        dut.u_register_file.registers[7], 32'sd31);

        // ---------------- Test 2: scenario A, tick already waiting ----------------
        reset_dut();
        for (b = 0; b < 20; b = b + 1)
            dut.u_control_unit.prog_mem[b] = encode_r3(OP_NOP, 3'd0, 3'd0, 3'd0);
        dut.u_control_unit.prog_mem[20] = encode_r3(OP_UPDATEALLSTOCKBUFFERS, 3'd0, 3'd0, 3'd0);
        dut.u_control_unit.prog_mem[21] = encode_buf(OP_GETSTOCKPRICE, 3'd1, 3'd0, 5'd0);
        dut.u_control_unit.prog_mem[22] = encode_buf(OP_GETSTOCKPRICE, 3'd2, 3'd2, 5'd0);
        dut.u_control_unit.prog_mem[23] = encode_buf(OP_GETSTOCKPRICE, 3'd3, 3'd4, 5'd0);
        dut.u_control_unit.prog_mem[24] = encode_r3(OP_JMP, 3'd0, 3'd0, 3'd0);
        dut.u_control_unit.prog_mem[25] = encode_word16(16'd24);

        for (b = 0; b < 5; b = b + 1)
            stage_tick(b[2:0], b * 100 + 7);

        check_true("T2: all 5 pending before UPDATE reached",
                   dut.u_stock_buffers.tick_pending == 5'b11111);
        check_true("T2: CPU still in NOP lead-in (pc < 20)",
                   dut.u_control_unit.pc < 9'd20);
        check32("T2: no advance yet", advance_count, 0);
        check_heads("T2: heads still 0", 5'd0);

        repeat (100) @(negedge clk);
        check32("T2: cycles in S_WAIT_TICKS (no stall)", wait_cycles, 1);
        check32("T2: advances fired",                     advance_count, 1);
        check_heads("T2: heads advanced to 1", 5'd1);
        check_true("T2: staging cleared",
                   dut.u_stock_buffers.tick_pending == 5'b00000);
        check32("T2: R1 GETSTOCKPRICE buf0", dut.u_register_file.registers[1], 32'sd7);
        check32("T2: R2 GETSTOCKPRICE buf2", dut.u_register_file.registers[2], 32'sd207);
        check32("T2: R3 GETSTOCKPRICE buf4", dut.u_register_file.registers[3], 32'sd407);

        // ---------------- Test 3: scenario B, tick not yet arrived ----------------
        reset_dut();
        dut.u_control_unit.prog_mem[0] = encode_r3(OP_UPDATEALLSTOCKBUFFERS, 3'd0, 3'd0, 3'd0);
        dut.u_control_unit.prog_mem[1] = encode_buf(OP_GETSTOCKPRICE, 3'd1, 3'd0, 5'd0);
        dut.u_control_unit.prog_mem[2] = encode_buf(OP_GETSTOCKPRICE, 3'd2, 3'd1, 5'd0);
        dut.u_control_unit.prog_mem[3] = encode_buf(OP_GETSTOCKPRICE, 3'd3, 3'd3, 5'd0);
        dut.u_control_unit.prog_mem[4] = encode_buf(OP_GETSTOCKPRICE, 3'd4, 3'd4, 5'd0);
        dut.u_control_unit.prog_mem[5] = encode_buf(OP_GETSTOCKPRICE, 3'd6, 3'd2, 5'd0);
        dut.u_control_unit.prog_mem[6] = encode_r3(OP_LOAD_IMM, 3'd5, 3'd0, 3'd0);
        dut.u_control_unit.prog_mem[7] = encode_word16(16'd999);
        dut.u_control_unit.prog_mem[8] = encode_r3(OP_JMP, 3'd0, 3'd0, 3'd0);
        dut.u_control_unit.prog_mem[9] = encode_word16(16'd8);

        // slot 1 is where the advance will write; it must not move early
        snap[0] = dut.u_stock_buffers.g_buf[0].mem[1];
        snap[1] = dut.u_stock_buffers.g_buf[1].mem[1];
        snap[2] = dut.u_stock_buffers.g_buf[2].mem[1];
        snap[3] = dut.u_stock_buffers.g_buf[3].mem[1];
        snap[4] = dut.u_stock_buffers.g_buf[4].mem[1];

        // step 1: buffers 2 and 4 missing
        stage_tick(3'd0, 16'd11);
        stage_tick(3'd1, 16'd1011);
        stage_tick(3'd3, 16'd3011);
        repeat (50) @(negedge clk);
        check_true("T3.1: FSM parked in S_WAIT_TICKS",
                   dut.u_control_unit.state == S_WAIT_TICKS);
        check32("T3.1: pc held at UPDATE (0)", dut.u_control_unit.pc, 0);
        check32("T3.1: no advance", advance_count, 0);
        check_heads("T3.1: heads still 0", 5'd0);
        check_true("T3.1: pending = 01011",
                   dut.u_stock_buffers.tick_pending == 5'b01011);
        check_true("T3.1: R1..R6 untouched (0)",
                   dut.u_register_file.registers[1] == 0 &&
                   dut.u_register_file.registers[2] == 0 &&
                   dut.u_register_file.registers[3] == 0 &&
                   dut.u_register_file.registers[4] == 0 &&
                   dut.u_register_file.registers[5] == 0 &&
                   dut.u_register_file.registers[6] == 0);
        check_true("T3.1: buffer slot 1 contents untouched",
                   dut.u_stock_buffers.g_buf[0].mem[1] === snap[0] &&
                   dut.u_stock_buffers.g_buf[1].mem[1] === snap[1] &&
                   dut.u_stock_buffers.g_buf[2].mem[1] === snap[2] &&
                   dut.u_stock_buffers.g_buf[3].mem[1] === snap[3] &&
                   dut.u_stock_buffers.g_buf[4].mem[1] === snap[4]);

        // step 2: buffer 2 arrives, 4 still missing
        stage_tick(3'd2, 16'd2011);
        repeat (50) @(negedge clk);
        check_true("T3.2: still parked in S_WAIT_TICKS",
                   dut.u_control_unit.state == S_WAIT_TICKS);
        check32("T3.2: pc still 0", dut.u_control_unit.pc, 0);
        check32("T3.2: still no advance", advance_count, 0);
        check_heads("T3.2: heads still 0", 5'd0);
        check_true("T3.2: pending = 01111",
                   dut.u_stock_buffers.tick_pending == 5'b01111);
        check32("T3.2: R5 marker not reached", dut.u_register_file.registers[5], 0);

        // step 3: a newer tick for buffer 0 replaces the staged one
        stage_tick(3'd0, 16'd12);
        repeat (20) @(negedge clk);
        check_true("T3.3: still parked in S_WAIT_TICKS",
                   dut.u_control_unit.state == S_WAIT_TICKS);
        check32("T3.3: still no advance", advance_count, 0);
        check32("T3.3: buf0 staged price replaced",
                $signed(dut.u_stock_buffers.g_buf[0].staged_price), 32'sd12);

        // step 4: last missing tick arrives
        stage_tick(3'd4, -16'sd411);
        repeat (40) @(negedge clk);
        check32("T3.4: exactly one advance", advance_count, 1);
        check_heads("T3.4: heads advanced to 1", 5'd1);
        check_true("T3.4: staging cleared",
                   dut.u_stock_buffers.tick_pending == 5'b00000);
        check_true("T3.4: stalled > 100 cycles before release", wait_cycles > 100);
        $display("      (S_WAIT_TICKS cycles: %0d)", wait_cycles);
        check32("T3.4: R1 buf0 (latest staged, 12)", dut.u_register_file.registers[1], 32'sd12);
        check32("T3.4: R2 buf1",                     dut.u_register_file.registers[2], 32'sd1011);
        check32("T3.4: R3 buf3",                     dut.u_register_file.registers[3], 32'sd3011);
        check32("T3.4: R4 buf4 (sign-extended)",     dut.u_register_file.registers[4], -32'sd411);
        check32("T3.4: R6 buf2",                     dut.u_register_file.registers[6], 32'sd2011);
        check32("T3.4: R5 marker (ran past UPDATE)", dut.u_register_file.registers[5], 32'sd999);

        // ---------------- Test 4: GETSTOCKPRICE is non-destructive ----------------
        reset_dut();
        dut.u_control_unit.prog_mem[0] = encode_r3(OP_UPDATEALLSTOCKBUFFERS, 3'd0, 3'd0, 3'd0);
        dut.u_control_unit.prog_mem[1] = encode_buf(OP_GETSTOCKPRICE,       3'd1, 3'd2, 5'd0);
        dut.u_control_unit.prog_mem[2] = encode_buf(OP_GETSTOCKPRICE,       3'd2, 3'd2, 5'd0);
        dut.u_control_unit.prog_mem[3] = encode_buf(OP_GETSTOCKPRICE,       3'd3, 3'd2, 5'd0);
        dut.u_control_unit.prog_mem[4] = encode_buf(OP_GETSTOCKPRICEBEFORE, 3'd4, 3'd2, 5'd0);
        dut.u_control_unit.prog_mem[5] = encode_buf(OP_GETSTOCKPRICE,       3'd5, 3'd2, 5'd0);
        dut.u_control_unit.prog_mem[6] = encode_r3(OP_JMP, 3'd0, 3'd0, 3'd0);
        dut.u_control_unit.prog_mem[7] = encode_word16(16'd6);

        stage_tick(3'd0, 16'd50);
        stage_tick(3'd1, 16'd150);
        stage_tick(3'd2, -16'sd1234);
        stage_tick(3'd3, 16'd350);
        stage_tick(3'd4, 16'd450);
        wait_ticks_consumed();
        stage_tick(3'd2, 16'd777);   // next day's tick, staged but never advanced

        repeat (60) @(negedge clk);
        check32("T4: R1 GETSTOCKPRICE buf2 (1st)",  dut.u_register_file.registers[1], -32'sd1234);
        check32("T4: R2 GETSTOCKPRICE buf2 (2nd)",  dut.u_register_file.registers[2], -32'sd1234);
        check32("T4: R3 GETSTOCKPRICE buf2 (3rd)",  dut.u_register_file.registers[3], -32'sd1234);
        check32("T4: R4 BEFORE buf2,0",             dut.u_register_file.registers[4], -32'sd1234);
        check32("T4: R5 GETSTOCKPRICE buf2 (4th)",  dut.u_register_file.registers[5], -32'sd1234);
        check_true("T4: R1 raw bits = 0xFFFFFB2E",
                   dut.u_register_file.registers[1] === 32'hFFFFFB2E);
        check32("T4: exactly one advance", advance_count, 1);
        check_heads("T4: heads stayed at 1", 5'd1);
        check32("T4: BUF[2][1] unchanged",
                $signed(dut.u_stock_buffers.g_buf[2].mem[1]), -32'sd1234);
        check_true("T4: next tick still staged, not consumed",
                   dut.u_stock_buffers.tick_pending == 5'b00100);
        check32("T4: buf2 staged price = 777",
                $signed(dut.u_stock_buffers.g_buf[2].staged_price), 32'sd777);

        if (errors == 0)
            $display("tb_stage3_core: ALL TESTS PASSED -- Stage 3 exit criteria met");
        else
            $display("tb_stage3_core: %0d TEST(S) FAILED", errors);

        $finish;
    end

endmodule
