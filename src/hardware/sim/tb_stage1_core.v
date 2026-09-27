`timescale 1ns/1ps

// Stage 1 exit criteria from the spec: "a (5+3)*2 > 6 style program,
// stored and read back correctly."
//
// No LOAD_IMM until Stage 2, so R1..R4 get poked directly into the
// register file below, same way prog_mem gets hand-loaded.
//
//   R1=5, R2=3, R3=2, R4=6           (pre-loaded operands)
//   addr0: ADD    R5, R1, R2         R5 = R1 + R2
//   addr1: MUL    R6, R5, R3         R6 = R5 * R3
//   addr2: CMP_GT R7, R6, R4         R7 = (R6 > R4) ? 1 : 0
//   addr3: NOP                       (padding)

module tb_stage1_core;

    localparam OP_NOP    = 5'h00;
    localparam OP_ADD    = 5'h01;
    localparam OP_SUB    = 5'h02;
    localparam OP_MUL    = 5'h03;
    localparam OP_CMP_GT = 5'h05;
    localparam OP_CMP_LT = 5'h06;

    localparam signed [31:0] EXPECTED_R5 = 32'sd8;
    localparam signed [31:0] EXPECTED_R6 = 32'sd16;
    localparam signed [31:0] EXPECTED_R7 = 32'sd1;

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

    // builds a 3-register instruction word: opcode[31:27] Rd[26:24]
    // Rs1[23:21] Rs2[20:18], everything else zero (unused in Stage 1)
    function [31:0] encode_r3;
        input [4:0] opc;
        input [2:0] rd, rs1, rs2;
        begin
            encode_r3 = {opc, rd, rs1, rs2, 4'd0, 3'd0, 5'd0, 6'd0};
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

    initial begin
        $dumpfile("tb_stage1_core.vcd");
        $dumpvars(0, tb_stage1_core);

        errors = 0;
        clk    = 0;
        rst_n  = 0;

        @(negedge clk);
        @(negedge clk);
        rst_n = 1;

        // load the program + starting operands before the clock gets to
        // instruction 0's EXECUTE phase
        dut.u_control_unit.prog_mem[0] = encode_r3(OP_ADD,    3'd5, 3'd1, 3'd2);
        dut.u_control_unit.prog_mem[1] = encode_r3(OP_MUL,    3'd6, 3'd5, 3'd3);
        dut.u_control_unit.prog_mem[2] = encode_r3(OP_CMP_GT, 3'd7, 3'd6, 3'd4);
        dut.u_control_unit.prog_mem[3] = encode_r3(OP_NOP,    3'd0, 3'd0, 3'd0);

        dut.u_register_file.registers[1] = 32'sd5;
        dut.u_register_file.registers[2] = 32'sd3;
        dut.u_register_file.registers[3] = 32'sd2;
        dut.u_register_file.registers[4] = 32'sd6;

        $display("Loaded program words: %h %h %h %h",
            dut.u_control_unit.prog_mem[0], dut.u_control_unit.prog_mem[1],
            dut.u_control_unit.prog_mem[2], dut.u_control_unit.prog_mem[3]);

        // 3 real instructions x 4 cycles/instruction, plus some margin
        repeat (24) @(negedge clk);

        check32("R5 = R1+R2",       dut.u_register_file.registers[5], EXPECTED_R5);
        check32("R6 = R5*R3",       dut.u_register_file.registers[6], EXPECTED_R6);
        check32("R7 = (R6>R4)?1:0", dut.u_register_file.registers[7], EXPECTED_R7);

        check32("R1 unchanged", dut.u_register_file.registers[1], 32'sd5);
        check32("R2 unchanged", dut.u_register_file.registers[2], 32'sd3);
        check32("R3 unchanged", dut.u_register_file.registers[3], 32'sd2);
        check32("R4 unchanged", dut.u_register_file.registers[4], 32'sd6);

        if (errors == 0)
            $display("tb_stage1_core: ALL TESTS PASSED -- Stage 1 exit criteria met");
        else
            $display("tb_stage1_core: %0d TEST(S) FAILED", errors);

        $finish;
    end

endmodule
