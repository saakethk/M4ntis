`timescale 1ns/1ps

// Stage 2 exit criteria: an if/else program takes the correct branch
// across 3+ scenarios, plus a backward-JMP loop.
//
// if/else program (same layout for all three scenarios, only the R1/R2
// immediates change):
//   addr0-1:   LOAD_IMM R1, r1
//   addr2-3:   LOAD_IMM R2, r2
//   addr4:     CMP_GT   R3, R1, R2
//   addr5-6:   JMP_IF   R3, THEN(=11)
//   addr7-8:   LOAD_IMM R4, 222        ; else
//   addr9-10:  JMP      END(=13)
//   addr11-12: LOAD_IMM R4, 111        ; then
//   addr13-14: LOAD_IMM R5, 999        ; end (both paths land here)
//
// expected, hand-computed:
//   A: r1=10, r2=5  -> 10>5 true  -> then -> R4=111, R5=999
//   B: r1=3,  r2=5  -> 3>5  false -> else -> R4=222, R5=999
//   C: r1=7,  r2=7  -> 7>7  false (boundary, strict >) -> else -> R4=222, R5=999
//
// loop program (counts R1 up 4 times, R2 down from 4 to 0):
//   addr0-1:   LOAD_IMM R1, 0
//   addr2-3:   LOAD_IMM R2, 4
//   addr4-5:   LOAD_IMM R3, 1
//   addr6:     LOOP: ADD R1, R1, R3
//   addr7:     SUB R2, R2, R3
//   addr8:     CMP_GT R4, R2, R0
//   addr9-10:  JMP_IF R4, LOOP(=6)
//   addr11-12: LOAD_IMM R5, 999
//
// expected: 3 backward jumps (R2 hits 0 on the 4th pass, condition goes
// false, falls through) -> R1=4, R2=0, R4=0, R5=999

module tb_stage2_core;

    localparam OP_ADD      = 5'h01;
    localparam OP_SUB      = 5'h02;
    localparam OP_CMP_GT   = 5'h05;
    localparam OP_LOAD_IMM = 5'h09;
    localparam OP_JMP      = 5'h0A;
    localparam OP_JMP_IF   = 5'h0B;

    reg clk;
    reg rst_n;
    integer errors;

    tradecpu_core dut (
        .clk         (clk),
        .rst_n       (rst_n),
        .tick_valid  (1'b0),   // no ticks in this stage's tests
        .tick_buf_id (3'd0),
        .tick_price  (16'd0),
        .UART_RXD    (1'b1)    // serial line idle
    );

    always #5 clk = ~clk;

    function [31:0] encode_r3;
        input [4:0] opc;
        input [2:0] rd, rs1, rs2;
        begin
            encode_r3 = {opc, rd, rs1, rs2, 4'd0, 3'd0, 5'd0, 6'd0};
        end
    endfunction

    function [31:0] encode_word16;
        input [15:0] val;
        begin
            encode_word16 = {16'd0, val};
        end
    endfunction

    task check32;
        input [255:0]       label;
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

    task reset_dut;
        begin
            rst_n = 0;
            @(negedge clk);
            @(negedge clk);
            rst_n = 1;
        end
    endtask

    task load_ifelse_program;
        input [15:0] r1_val, r2_val;
        begin
            dut.u_control_unit.prog_mem[0]  = encode_r3(OP_LOAD_IMM, 3'd1, 3'd0, 3'd0);
            dut.u_control_unit.prog_mem[1]  = encode_word16(r1_val);
            dut.u_control_unit.prog_mem[2]  = encode_r3(OP_LOAD_IMM, 3'd2, 3'd0, 3'd0);
            dut.u_control_unit.prog_mem[3]  = encode_word16(r2_val);
            dut.u_control_unit.prog_mem[4]  = encode_r3(OP_CMP_GT, 3'd3, 3'd1, 3'd2);
            dut.u_control_unit.prog_mem[5]  = encode_r3(OP_JMP_IF, 3'd0, 3'd3, 3'd0);
            dut.u_control_unit.prog_mem[6]  = encode_word16(16'd11);
            dut.u_control_unit.prog_mem[7]  = encode_r3(OP_LOAD_IMM, 3'd4, 3'd0, 3'd0);
            dut.u_control_unit.prog_mem[8]  = encode_word16(16'd222);
            dut.u_control_unit.prog_mem[9]  = encode_r3(OP_JMP, 3'd0, 3'd0, 3'd0);
            dut.u_control_unit.prog_mem[10] = encode_word16(16'd13);
            dut.u_control_unit.prog_mem[11] = encode_r3(OP_LOAD_IMM, 3'd4, 3'd0, 3'd0);
            dut.u_control_unit.prog_mem[12] = encode_word16(16'd111);
            dut.u_control_unit.prog_mem[13] = encode_r3(OP_LOAD_IMM, 3'd5, 3'd0, 3'd0);
            dut.u_control_unit.prog_mem[14] = encode_word16(16'd999);
        end
    endtask

    initial begin
        errors = 0;
        clk    = 0;

        // A: 10 > 5, then-branch
        reset_dut();
        load_ifelse_program(16'd10, 16'd5);
        repeat (60) @(negedge clk);
        check32("A: R4 (then taken)",   dut.u_register_file.registers[4], 32'sd111);
        check32("A: R5 (reaches end)",  dut.u_register_file.registers[5], 32'sd999);

        // B: 3 > 5 is false, else-branch
        reset_dut();
        load_ifelse_program(16'd3, 16'd5);
        repeat (60) @(negedge clk);
        check32("B: R4 (else taken)",   dut.u_register_file.registers[4], 32'sd222);
        check32("B: R5 (reaches end)",  dut.u_register_file.registers[5], 32'sd999);

        // C: 7 > 7 is false (boundary), else-branch
        reset_dut();
        load_ifelse_program(16'd7, 16'd7);
        repeat (60) @(negedge clk);
        check32("C: R4 (boundary, else taken)", dut.u_register_file.registers[4], 32'sd222);
        check32("C: R5 (reaches end)",           dut.u_register_file.registers[5], 32'sd999);

        // D: backward-JMP loop, 4 iterations
        reset_dut();
        dut.u_control_unit.prog_mem[0]  = encode_r3(OP_LOAD_IMM, 3'd1, 3'd0, 3'd0);
        dut.u_control_unit.prog_mem[1]  = encode_word16(16'd0);
        dut.u_control_unit.prog_mem[2]  = encode_r3(OP_LOAD_IMM, 3'd2, 3'd0, 3'd0);
        dut.u_control_unit.prog_mem[3]  = encode_word16(16'd4);
        dut.u_control_unit.prog_mem[4]  = encode_r3(OP_LOAD_IMM, 3'd3, 3'd0, 3'd0);
        dut.u_control_unit.prog_mem[5]  = encode_word16(16'd1);
        dut.u_control_unit.prog_mem[6]  = encode_r3(OP_ADD, 3'd1, 3'd1, 3'd3);
        dut.u_control_unit.prog_mem[7]  = encode_r3(OP_SUB, 3'd2, 3'd2, 3'd3);
        dut.u_control_unit.prog_mem[8]  = encode_r3(OP_CMP_GT, 3'd4, 3'd2, 3'd0);
        dut.u_control_unit.prog_mem[9]  = encode_r3(OP_JMP_IF, 3'd0, 3'd4, 3'd0);
        dut.u_control_unit.prog_mem[10] = encode_word16(16'd6);
        dut.u_control_unit.prog_mem[11] = encode_r3(OP_LOAD_IMM, 3'd5, 3'd0, 3'd0);
        dut.u_control_unit.prog_mem[12] = encode_word16(16'd999);

        repeat (130) @(negedge clk);
        check32("D: R1 (counted up 4x)",   dut.u_register_file.registers[1], 32'sd4);
        check32("D: R2 (counted down to 0)", dut.u_register_file.registers[2], 32'sd0);
        check32("D: R4 (loop exit condition)", dut.u_register_file.registers[4], 32'sd0);
        check32("D: R5 (reached after loop)", dut.u_register_file.registers[5], 32'sd999);

        if (errors == 0)
            $display("tb_stage2_core: ALL TESTS PASSED -- Stage 2 exit criteria met");
        else
            $display("tb_stage2_core: %0d TEST(S) FAILED", errors);

        $finish;
    end

endmodule
