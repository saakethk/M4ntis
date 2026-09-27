`timescale 1ns/1ps

// VAR[0..14]: 15 slots of 16-bit signed, separate from the register file
// (spec sections 1/5). Takes and returns 32-bit register values so the
// width convention lives in one place:
//   - write (ASSIGNVAR) keeps the low 16 bits and drops the rest -- a
//     plain truncation, no saturation (spec section 1)
//   - read (GETVAR) sign-extends back to 32 bits
//
// var_id is a 4-bit field but only 0-14 exist: a write to 15 is dropped
// and a read of 15 returns 0.
//
// Only 240 bits, so these are plain flops and clear on rst_n like the
// register file (unlike stock_buffers' LUTRAM contents).

module var_store (
    input  wire        clk,
    input  wire        rst_n,

    input  wire [3:0]  var_id,
    input  wire        we,
    input  wire [31:0] wdata,
    output wire [31:0] rdata
);

    localparam NUM_VARS = 15;

    reg [15:0] vars [0:NUM_VARS-1];

    wire id_valid = (var_id < NUM_VARS);

    integer i;
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            for (i = 0; i < NUM_VARS; i = i + 1)
                vars[i] <= 16'd0;
        end else if (we && id_valid) begin
            vars[var_id] <= wdata[15:0];
        end
    end

    wire [15:0] slot = id_valid ? vars[var_id] : 16'd0;
    assign rdata = {{16{slot[15]}}, slot};

endmodule
