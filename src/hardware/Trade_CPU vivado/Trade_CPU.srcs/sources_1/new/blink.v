module blink (
    input  wire CLK_100MHZ,
    output wire [15:0] LED
);

    localparam COUNTER_WIDTH = 26;
    reg [COUNTER_WIDTH-1:0] counter;

    always @(posedge CLK_100MHZ)
        counter <= counter + 1'b1;

    assign LED = {16{counter[COUNTER_WIDTH-1]}};

endmodule