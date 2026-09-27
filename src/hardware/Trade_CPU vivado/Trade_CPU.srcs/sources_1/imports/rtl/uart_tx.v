`timescale 1ns/1ps

// UART transmitter, 8N1 (start bit, 8 data bits LSB first, 1 stop bit),
// idle high. Pulse `start` with `data` while `busy` is low; busy goes high
// on the next cycle and drops after the full stop bit, so a new byte can
// start back-to-back. txd is registered so it never glitches.

module uart_tx #(
    parameter CLKS_PER_BIT = 868
) (
    input  wire       clk,
    input  wire       rst_n,

    input  wire       start,
    input  wire [7:0] data,

    output reg        txd,
    output reg        busy
);

    reg [8:0]  shift;      // data bits then the stop bit, LSB first
    reg [3:0]  bits_sent;  // 0 = start bit on the wire, 1-8 data, 9 stop
    reg [15:0] cnt;

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            txd       <= 1'b1;
            busy      <= 1'b0;
            shift     <= 9'h1FF;
            bits_sent <= 4'd0;
            cnt       <= 16'd0;
        end else if (!busy) begin
            txd <= 1'b1;
            if (start) begin
                shift     <= {1'b1, data};
                txd       <= 1'b0;          // start bit
                busy      <= 1'b1;
                bits_sent <= 4'd0;
                cnt       <= 16'd0;
            end
        end else if (cnt == CLKS_PER_BIT - 1) begin
            cnt <= 16'd0;
            if (bits_sent == 4'd9) begin
                busy <= 1'b0;               // stop bit done
                txd  <= 1'b1;
            end else begin
                txd       <= shift[0];
                shift     <= {1'b1, shift[8:1]};
                bits_sent <= bits_sent + 4'd1;
            end
        end else begin
            cnt <= cnt + 16'd1;
        end
    end

endmodule
