`timescale 1ns/1ps

// R0-R7, no hardwired zero reg like some ISAs -- R0 is just a normal
// register here.

module register_file (
    input  wire        clk,
    input  wire        rst_n,

    input  wire        we,
    input  wire [2:0]  waddr,
    input  wire [31:0] wdata,

    input  wire [2:0]  raddr1,
    input  wire [2:0]  raddr2,
    output wire [31:0] rdata1,
    output wire [31:0] rdata2
);

    reg signed [31:0] registers [0:7];

    integer i;
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            for (i = 0; i < 8; i = i + 1)
                registers[i] <= 32'sd0;
        end else if (we) begin
            registers[waddr] <= wdata;
        end
    end

    assign rdata1 = registers[raddr1];
    assign rdata2 = registers[raddr2];

endmodule
