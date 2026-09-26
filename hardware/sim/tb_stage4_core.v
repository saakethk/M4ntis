`timescale 1ns/1ps

// Stage 4 exit criteria: divide-by-zero returns 0 as specified; sum at
// N=30 (wraparound-adjacent) correct. Plus normal DIV (truncation toward
// zero, all sign combinations) and a realistic 14-day window.
//
// GETSUMPRICEBEFORE convention under test (see control_unit.v): imm5 is
// the window size N = the N most recent entries INCLUDING today (offsets
// 0..N-1). N=30 sums all 30 slots once; N=0 -> 0; imm5=31 clamps to 30.
//
// ======================= expected results ==========================
//
// DIV latency: every DIV spends exactly 17 cycles in S_DIV_WAIT
// (20 cycles fetch-to-fetch), divide-by-zero included.
//
// Test 1 -- DIV signs, truncation toward zero (not floor)
//   R1=100, R2=7, R3=-100, R4=-7
//   R5 = R1/R2 =  100/7  =  14   (14.28)
//   R6 = R3/R2 = -100/7  = -14   (floor would give -15)
//   R7 = R1/R4 =  100/-7 = -14
//   R0 = R3/R4 = -100/-7 =  14
//
// Test 2 -- divide-by-zero, and truncation not rounding
//   R1=5, R2=0; R3 and R7 preloaded with 12345 sentinel
//   R3 = 5/0  = 0   (overwrites the sentinel -> it really wrote 0)
//   R4 = -9/0 = 0   (R4 was -9, overwritten)
//   R5 = 5/3  = 1   (1.67 -- rounding would give 2)
//   R7 = 3/5  = 0   (overwrites sentinel)
//   R0 = 999        (LOAD_IMM after the DIVs -> FSM kept running)
//
// Test 3 -- 32-bit edges (operands built with LOAD_IMM + MUL)
//   R1 = -32768 * (256*256) = -2147483648 (INT_MIN)
//   R4 = INT_MIN / -1 = -2147483648 (overflow wraps to INT_MIN, documented)
//   R5 = INT_MIN + -1 = 2147483647 (INT_MAX, via ADD wrap)
//   R7 = INT_MAX / 2  = 1073741823
//   R0 = INT_MIN / 2  = -1073741824
//
// Test 4 -- GETSUMPRICEBEFORE
//   33 days of ticks: price(b, d) = b*100 + d for b = 0..3,
//                     price(4, d) = 10*d - 200 (runs -190..130, mixed sign)
//   Day d sits in slot d mod 30, so after day 33: head = 3, days 1-3 are
//   overwritten, days 4..33 survive, and any window over 4 days
//   crosses the slot 0 -> 29 wrap.
//   R1 = SUM buf1, 30 -> days 4..33:  3000 + (4+33)*30/2  = 3000 + 555 = 3555
//   R2 = SUM buf1, 14 -> days 20..33: 1400 + (20+33)*14/2 = 1400 + 371 = 1771
//   R3 = SUM buf1, 29 -> days 5..33:  2900 + (5+33)*29/2  = 2900 + 551 = 3451
//   R4 = SUM buf1, 1  -> day 33 only:                             133
//   R5 = SUM buf1, 0  -> empty window: 0 (R5 preloaded 12345 sentinel)
//   R6 = SUM buf4, 30 -> 10*555 - 200*30 = 5550 - 6000          = -450
//   R7 = SUM buf1, 31 -> clamps to 30:                            3555
//   R0 = R2 / 14      -> 14-day SMA = 1771/14 = 126.5 ->          126
//   For reference, the rejected conventions would give N=30 -> 133
//   (mod-30, same as N=0 today-only) or 3451 (clamp to 29).
//   S_SUM_WAIT: exactly N cycles each -> 30+14+29+1+0+30+30 = 134 total,
//   longest single run 30. Heads stay 3 (the sums don't advance anything).
// ===================================================================

module tb_stage4_core;

    localparam OP_ADD                   = 5'h01;
    localparam OP_SUB                   = 5'h02;
    localparam OP_MUL                   = 5'h03;
    localparam OP_DIV                   = 5'h04;
    localparam OP_CMP_GT                = 5'h05;
    localparam OP_LOAD_IMM              = 5'h09;
    localparam OP_JMP                   = 5'h0A;
    localparam OP_JMP_IF                = 5'h0B;
    localparam OP_GETSUMPRICEBEFORE     = 5'h11;
    localparam OP_UPDATEALLSTOCKBUFFERS = 5'h13;

    localparam S_DIV_WAIT = 3'd6;
    localparam S_SUM_WAIT = 3'd7;

    reg        clk;
    reg        rst_n;
    reg        tick_valid;
    reg [2:0]  tick_buf_id;
    reg [15:0] tick_price;

    integer errors;
    integer day, b, guard;

    // length of each contiguous run in a wait state
    integer div_run, div_run_min, div_run_max, div_runs;
    integer sum_run, sum_run_max, sum_total;

    tradecpu_core dut (
        .clk         (clk),
        .rst_n       (rst_n),
        .tick_valid  (tick_valid),
        .tick_buf_id (tick_buf_id),
        .tick_price  (tick_price),
        .UART_RXD    (1'b1)    // serial line idle
    );

    always #5 clk = ~clk;

    always @(posedge clk) begin
        if (rst_n) begin
            if (dut.u_control_unit.state == S_DIV_WAIT) begin
                div_run = div_run + 1;
            end else if (div_run != 0) begin
                if (div_run < div_run_min) div_run_min = div_run;
                if (div_run > div_run_max) div_run_max = div_run;
                div_runs = div_runs + 1;
                div_run  = 0;
            end

            if (dut.u_control_unit.state == S_SUM_WAIT) begin
                sum_run   = sum_run + 1;
                sum_total = sum_total + 1;
            end else if (sum_run != 0) begin
                if (sum_run > sum_run_max) sum_run_max = sum_run;
                sum_run = 0;
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

    task check_div_latency;
        input [8*48-1:0] label;
        input integer    expected_runs;
        begin
            check32(label, div_runs, expected_runs);
            check32("  shortest DIV wait (cycles)", div_run_min, 17);
            check32("  longest DIV wait (cycles)",  div_run_max, 17);
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
            div_run     = 0;
            div_run_min = 9999;
            div_run_max = 0;
            div_runs    = 0;
            sum_run     = 0;
            sum_run_max = 0;
            sum_total   = 0;
            rst_n = 1;
        end
    endtask

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

        // ---------------- Test 1: DIV signs / truncation ----------------
        reset_dut();
        dut.u_control_unit.prog_mem[0]  = encode_r3(OP_LOAD_IMM, 3'd1, 3'd0, 3'd0);
        dut.u_control_unit.prog_mem[1]  = encode_word16(16'd100);
        dut.u_control_unit.prog_mem[2]  = encode_r3(OP_LOAD_IMM, 3'd2, 3'd0, 3'd0);
        dut.u_control_unit.prog_mem[3]  = encode_word16(16'd7);
        dut.u_control_unit.prog_mem[4]  = encode_r3(OP_LOAD_IMM, 3'd3, 3'd0, 3'd0);
        dut.u_control_unit.prog_mem[5]  = encode_word16(-16'sd100);
        dut.u_control_unit.prog_mem[6]  = encode_r3(OP_LOAD_IMM, 3'd4, 3'd0, 3'd0);
        dut.u_control_unit.prog_mem[7]  = encode_word16(-16'sd7);
        dut.u_control_unit.prog_mem[8]  = encode_r3(OP_DIV, 3'd5, 3'd1, 3'd2);
        dut.u_control_unit.prog_mem[9]  = encode_r3(OP_DIV, 3'd6, 3'd3, 3'd2);
        dut.u_control_unit.prog_mem[10] = encode_r3(OP_DIV, 3'd7, 3'd1, 3'd4);
        dut.u_control_unit.prog_mem[11] = encode_r3(OP_DIV, 3'd0, 3'd3, 3'd4);
        dut.u_control_unit.prog_mem[12] = encode_r3(OP_JMP, 3'd0, 3'd0, 3'd0);
        dut.u_control_unit.prog_mem[13] = encode_word16(16'd12);

        repeat (200) @(negedge clk);
        check32("T1: R5 =  100 /  7", dut.u_register_file.registers[5],  32'sd14);
        check32("T1: R6 = -100 /  7 (trunc, not -15)", dut.u_register_file.registers[6], -32'sd14);
        check32("T1: R7 =  100 / -7", dut.u_register_file.registers[7], -32'sd14);
        check32("T1: R0 = -100 / -7", dut.u_register_file.registers[0],  32'sd14);
        check_div_latency("T1: DIVs executed", 4);

        // ---------------- Test 2: divide-by-zero ----------------
        reset_dut();
        dut.u_control_unit.prog_mem[0]  = encode_r3(OP_LOAD_IMM, 3'd1, 3'd0, 3'd0);
        dut.u_control_unit.prog_mem[1]  = encode_word16(16'd5);
        dut.u_control_unit.prog_mem[2]  = encode_r3(OP_LOAD_IMM, 3'd2, 3'd0, 3'd0);
        dut.u_control_unit.prog_mem[3]  = encode_word16(16'd0);
        dut.u_control_unit.prog_mem[4]  = encode_r3(OP_LOAD_IMM, 3'd3, 3'd0, 3'd0);
        dut.u_control_unit.prog_mem[5]  = encode_word16(16'd12345);
        dut.u_control_unit.prog_mem[6]  = encode_r3(OP_LOAD_IMM, 3'd7, 3'd0, 3'd0);
        dut.u_control_unit.prog_mem[7]  = encode_word16(16'd12345);
        dut.u_control_unit.prog_mem[8]  = encode_r3(OP_DIV, 3'd3, 3'd1, 3'd2);
        dut.u_control_unit.prog_mem[9]  = encode_r3(OP_LOAD_IMM, 3'd4, 3'd0, 3'd0);
        dut.u_control_unit.prog_mem[10] = encode_word16(-16'sd9);
        dut.u_control_unit.prog_mem[11] = encode_r3(OP_DIV, 3'd4, 3'd4, 3'd2);
        dut.u_control_unit.prog_mem[12] = encode_r3(OP_LOAD_IMM, 3'd6, 3'd0, 3'd0);
        dut.u_control_unit.prog_mem[13] = encode_word16(16'd3);
        dut.u_control_unit.prog_mem[14] = encode_r3(OP_DIV, 3'd5, 3'd1, 3'd6);
        dut.u_control_unit.prog_mem[15] = encode_r3(OP_DIV, 3'd7, 3'd6, 3'd1);
        dut.u_control_unit.prog_mem[16] = encode_r3(OP_LOAD_IMM, 3'd0, 3'd0, 3'd0);
        dut.u_control_unit.prog_mem[17] = encode_word16(16'd999);
        dut.u_control_unit.prog_mem[18] = encode_r3(OP_JMP, 3'd0, 3'd0, 3'd0);
        dut.u_control_unit.prog_mem[19] = encode_word16(16'd18);

        repeat (200) @(negedge clk);
        check32("T2: R3 =  5 / 0 (sentinel overwritten)", dut.u_register_file.registers[3], 32'sd0);
        check32("T2: R4 = -9 / 0",                         dut.u_register_file.registers[4], 32'sd0);
        check32("T2: R5 =  5 / 3 (trunc, not 2)",          dut.u_register_file.registers[5], 32'sd1);
        check32("T2: R7 =  3 / 5 (sentinel overwritten)", dut.u_register_file.registers[7], 32'sd0);
        check32("T2: R0 marker (FSM ran on past DIV/0)",   dut.u_register_file.registers[0], 32'sd999);
        check32("T2: parked at final JMP (pc)",            dut.u_control_unit.pc, 18);
        check_div_latency("T2: DIVs executed (2 by zero)", 4);

        // ---------------- Test 3: 32-bit edges ----------------
        reset_dut();
        dut.u_control_unit.prog_mem[0]  = encode_r3(OP_LOAD_IMM, 3'd1, 3'd0, 3'd0);
        dut.u_control_unit.prog_mem[1]  = encode_word16(-16'sd32768);
        dut.u_control_unit.prog_mem[2]  = encode_r3(OP_LOAD_IMM, 3'd2, 3'd0, 3'd0);
        dut.u_control_unit.prog_mem[3]  = encode_word16(16'd256);
        dut.u_control_unit.prog_mem[4]  = encode_r3(OP_MUL, 3'd2, 3'd2, 3'd2);
        dut.u_control_unit.prog_mem[5]  = encode_r3(OP_MUL, 3'd1, 3'd1, 3'd2);
        dut.u_control_unit.prog_mem[6]  = encode_r3(OP_LOAD_IMM, 3'd3, 3'd0, 3'd0);
        dut.u_control_unit.prog_mem[7]  = encode_word16(-16'sd1);
        dut.u_control_unit.prog_mem[8]  = encode_r3(OP_DIV, 3'd4, 3'd1, 3'd3);
        dut.u_control_unit.prog_mem[9]  = encode_r3(OP_ADD, 3'd5, 3'd1, 3'd3);
        dut.u_control_unit.prog_mem[10] = encode_r3(OP_LOAD_IMM, 3'd6, 3'd0, 3'd0);
        dut.u_control_unit.prog_mem[11] = encode_word16(16'd2);
        dut.u_control_unit.prog_mem[12] = encode_r3(OP_DIV, 3'd7, 3'd5, 3'd6);
        dut.u_control_unit.prog_mem[13] = encode_r3(OP_DIV, 3'd0, 3'd1, 3'd6);
        dut.u_control_unit.prog_mem[14] = encode_r3(OP_JMP, 3'd0, 3'd0, 3'd0);
        dut.u_control_unit.prog_mem[15] = encode_word16(16'd14);

        repeat (200) @(negedge clk);
        check32("T3: R1 = INT_MIN (setup)",        dut.u_register_file.registers[1], 32'h80000000);
        check32("T3: R4 = INT_MIN / -1 (wraps)",   dut.u_register_file.registers[4], 32'h80000000);
        check32("T3: R5 = INT_MAX (setup)",        dut.u_register_file.registers[5], 32'sd2147483647);
        check32("T3: R7 = INT_MAX / 2",            dut.u_register_file.registers[7], 32'sd1073741823);
        check32("T3: R0 = INT_MIN / 2",            dut.u_register_file.registers[0], -32'sd1073741824);
        check_div_latency("T3: DIVs executed", 3);

        // ---------------- Test 4: GETSUMPRICEBEFORE ----------------
        reset_dut();
        dut.u_control_unit.prog_mem[0]  = encode_r3(OP_LOAD_IMM, 3'd5, 3'd0, 3'd0);
        dut.u_control_unit.prog_mem[1]  = encode_word16(16'd12345);
        dut.u_control_unit.prog_mem[2]  = encode_r3(OP_LOAD_IMM, 3'd1, 3'd0, 3'd0);
        dut.u_control_unit.prog_mem[3]  = encode_word16(16'd33);
        dut.u_control_unit.prog_mem[4]  = encode_r3(OP_LOAD_IMM, 3'd2, 3'd0, 3'd0);
        dut.u_control_unit.prog_mem[5]  = encode_word16(16'd1);
        dut.u_control_unit.prog_mem[6]  = encode_r3(OP_UPDATEALLSTOCKBUFFERS, 3'd0, 3'd0, 3'd0);
        dut.u_control_unit.prog_mem[7]  = encode_r3(OP_SUB, 3'd1, 3'd1, 3'd2);
        dut.u_control_unit.prog_mem[8]  = encode_r3(OP_CMP_GT, 3'd3, 3'd1, 3'd0);
        dut.u_control_unit.prog_mem[9]  = encode_r3(OP_JMP_IF, 3'd0, 3'd3, 3'd0);
        dut.u_control_unit.prog_mem[10] = encode_word16(16'd6);
        dut.u_control_unit.prog_mem[11] = encode_buf(OP_GETSUMPRICEBEFORE, 3'd1, 3'd1, 5'd30);
        dut.u_control_unit.prog_mem[12] = encode_buf(OP_GETSUMPRICEBEFORE, 3'd2, 3'd1, 5'd14);
        dut.u_control_unit.prog_mem[13] = encode_buf(OP_GETSUMPRICEBEFORE, 3'd3, 3'd1, 5'd29);
        dut.u_control_unit.prog_mem[14] = encode_buf(OP_GETSUMPRICEBEFORE, 3'd4, 3'd1, 5'd1);
        dut.u_control_unit.prog_mem[15] = encode_buf(OP_GETSUMPRICEBEFORE, 3'd5, 3'd1, 5'd0);
        dut.u_control_unit.prog_mem[16] = encode_buf(OP_GETSUMPRICEBEFORE, 3'd6, 3'd4, 5'd30);
        dut.u_control_unit.prog_mem[17] = encode_buf(OP_GETSUMPRICEBEFORE, 3'd7, 3'd1, 5'd31);
        dut.u_control_unit.prog_mem[18] = encode_r3(OP_LOAD_IMM, 3'd0, 3'd0, 3'd0);
        dut.u_control_unit.prog_mem[19] = encode_word16(16'd14);
        dut.u_control_unit.prog_mem[20] = encode_r3(OP_DIV, 3'd0, 3'd2, 3'd0);
        dut.u_control_unit.prog_mem[21] = encode_r3(OP_JMP, 3'd0, 3'd0, 3'd0);
        dut.u_control_unit.prog_mem[22] = encode_word16(16'd21);

        for (day = 1; day <= 33; day = day + 1) begin
            for (b = 0; b < 4; b = b + 1)
                stage_tick(b[2:0], b * 100 + day);
            stage_tick(3'd4, 10 * day - 200);
            wait_ticks_consumed();
        end

        repeat (400) @(negedge clk);
        check_true("T4: heads = 3 after 33 days, untouched by sums",
                   dut.u_stock_buffers.g_buf[0].head == 5'd3 &&
                   dut.u_stock_buffers.g_buf[1].head == 5'd3 &&
                   dut.u_stock_buffers.g_buf[2].head == 5'd3 &&
                   dut.u_stock_buffers.g_buf[3].head == 5'd3 &&
                   dut.u_stock_buffers.g_buf[4].head == 5'd3);
        check32("T4: R1 SUM buf1, N=30 (full buffer)", dut.u_register_file.registers[1], 32'sd3555);
        check32("T4: R2 SUM buf1, N=14",               dut.u_register_file.registers[2], 32'sd1771);
        check32("T4: R3 SUM buf1, N=29",               dut.u_register_file.registers[3], 32'sd3451);
        check32("T4: R4 SUM buf1, N=1 (today)",        dut.u_register_file.registers[4], 32'sd133);
        check32("T4: R5 SUM buf1, N=0 (empty)",        dut.u_register_file.registers[5], 32'sd0);
        check32("T4: R6 SUM buf4, N=30 (mixed sign)",  dut.u_register_file.registers[6], -32'sd450);
        check32("T4: R7 SUM buf1, imm5=31 -> 30",      dut.u_register_file.registers[7], 32'sd3555);
        check32("T4: R0 14-day SMA = R2 / 14",         dut.u_register_file.registers[0], 32'sd126);
        check32("T4: total S_SUM_WAIT cycles",         sum_total, 134);
        check32("T4: longest single sum (cycles)",     sum_run_max, 30);

        if (errors == 0)
            $display("tb_stage4_core: ALL TESTS PASSED -- Stage 4 exit criteria met");
        else
            $display("tb_stage4_core: %0d TEST(S) FAILED", errors);

        $finish;
    end

endmodule
