`timescale 1ns/1ps

// alu checks: ADD/SUB/MUL/CMP_GT/CMP_LT, plus the MUL overflow-wrap
// case and signed comparisons with negative operands.

module tb_alu;

    localparam OP_NOP    = 5'h00;
    localparam OP_ADD    = 5'h01;
    localparam OP_SUB    = 5'h02;
    localparam OP_MUL    = 5'h03;
    localparam OP_CMP_GT = 5'h05;
    localparam OP_CMP_LT = 5'h06;

    localparam signed [31:0] EXPECTED_ADD         = 32'sd42;
    localparam signed [31:0] EXPECTED_SUB         = -32'sd15;
    localparam signed [31:0] EXPECTED_MUL_OVERFLOW = 32'sd0;
    localparam signed [31:0] EXPECTED_MUL_NEG      = -32'sd42;
    localparam signed [31:0] EXPECTED_CMP_GT_FALSE = 32'sd0;
    localparam signed [31:0] EXPECTED_CMP_GT_TRUE  = 32'sd1;
    localparam signed [31:0] EXPECTED_CMP_LT_TRUE  = 32'sd1;
    localparam signed [31:0] EXPECTED_CMP_LT_FALSE = 32'sd0;
    localparam signed [31:0] EXPECTED_NOP          = 32'sd0;

    reg  [4:0]         opcode;
    reg  signed [31:0] in1, in2;
    wire signed [31:0] result;

    integer errors;

    alu dut (
        .opcode (opcode),
        .in1    (in1),
        .in2    (in2),
        .result (result)
    );

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
        errors = 0;

        opcode = OP_ADD; in1 = 32'sd12; in2 = 32'sd30; #1;
        check32("ADD 12+30", result, EXPECTED_ADD);

        opcode = OP_SUB; in1 = 32'sd10; in2 = 32'sd25; #1;
        check32("SUB 10-25", result, EXPECTED_SUB);

        opcode = OP_MUL; in1 = 32'sd65536; in2 = 32'sd65536; #1;
        check32("MUL 2^16*2^16 overflow wrap", result, EXPECTED_MUL_OVERFLOW);

        opcode = OP_MUL; in1 = -32'sd6; in2 = 32'sd7; #1;
        check32("MUL -6*7", result, EXPECTED_MUL_NEG);

        opcode = OP_CMP_GT; in1 = -32'sd5; in2 = 32'sd3; #1;
        check32("CMP_GT -5>3", result, EXPECTED_CMP_GT_FALSE);

        opcode = OP_CMP_GT; in1 = 32'sd5; in2 = -32'sd3; #1;
        check32("CMP_GT 5>-3", result, EXPECTED_CMP_GT_TRUE);

        opcode = OP_CMP_LT; in1 = -32'sd5; in2 = 32'sd3; #1;
        check32("CMP_LT -5<3", result, EXPECTED_CMP_LT_TRUE);

        opcode = OP_CMP_LT; in1 = 32'sd5; in2 = -32'sd3; #1;
        check32("CMP_LT 5<-3", result, EXPECTED_CMP_LT_FALSE);

        opcode = OP_NOP; in1 = 32'sd99; in2 = 32'sd99; #1;
        check32("NOP -> 0", result, EXPECTED_NOP);

        if (errors == 0)
            $display("tb_alu: ALL TESTS PASSED");
        else
            $display("tb_alu: %0d TEST(S) FAILED", errors);

        $finish;
    end

endmodule
