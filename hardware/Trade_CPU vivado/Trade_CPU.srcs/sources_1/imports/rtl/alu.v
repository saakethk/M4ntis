`timescale 1ns/1ps

// control_unit decides whether a result actually gets written back;
// NOP and anything unrecognized just falls to the default here.
//
// MUL: assigning the 32x32 product straight into a 32-bit reg already
// gives us the low 32 bits, no masking needed.

module alu (
    input  wire [4:0]         opcode,
    input  wire signed [31:0] in1,
    input  wire signed [31:0] in2,
    output reg  signed [31:0] result
);

    localparam OP_NOP    = 5'h00;
    localparam OP_ADD    = 5'h01;
    localparam OP_SUB    = 5'h02;
    localparam OP_MUL    = 5'h03;
    localparam OP_CMP_GT = 5'h05;
    localparam OP_CMP_LT = 5'h06;

    always @(*) begin
        case (opcode)
            OP_ADD:    result = in1 + in2;
            OP_SUB:    result = in1 - in2;
            OP_MUL:    result = in1 * in2;
            OP_CMP_GT: result = (in1 > in2) ? 32'sd1 : 32'sd0;
            OP_CMP_LT: result = (in1 < in2) ? 32'sd1 : 32'sd0;
            default:   result = 32'sd0;
        endcase
    end

endmodule
