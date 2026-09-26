`timescale 1ns/1ps

// Single-clock FIFO, first-word-fall-through: rd_data always shows the
// oldest entry while !empty, and rd_en pops it. Writes when full and reads
// when empty are ignored. Depth = 2**ADDR_W.

module sync_fifo #(
    parameter WIDTH  = 8,
    parameter ADDR_W = 3
) (
    input  wire             clk,
    input  wire             rst_n,

    input  wire             wr_en,
    input  wire [WIDTH-1:0] wr_data,
    output wire             full,

    input  wire             rd_en,
    output wire [WIDTH-1:0] rd_data,
    output wire             empty
);

    localparam DEPTH = 1 << ADDR_W;

    reg [WIDTH-1:0] mem [0:DEPTH-1];
    reg [ADDR_W:0]  wptr, rptr;     // extra MSB tells full from empty

    assign empty   = (wptr == rptr);
    assign full    = (wptr[ADDR_W] != rptr[ADDR_W]) &&
                     (wptr[ADDR_W-1:0] == rptr[ADDR_W-1:0]);
    assign rd_data = mem[rptr[ADDR_W-1:0]];

    always @(posedge clk) begin
        if (wr_en && !full)
            mem[wptr[ADDR_W-1:0]] <= wr_data;
    end

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            wptr <= {(ADDR_W+1){1'b0}};
            rptr <= {(ADDR_W+1){1'b0}};
        end else begin
            if (wr_en && !full)
                wptr <= wptr + 1'b1;
            if (rd_en && !empty)
                rptr <= rptr + 1'b1;
        end
    end

endmodule
