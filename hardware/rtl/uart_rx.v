`timescale 1ns/1ps

// UART receiver, 8N1 (8 data bits LSB first, no parity, 1 stop bit), idle
// high. CLKS_PER_BIT = clk frequency / baud; tradecpu_core computes it
// (100 MHz / 115200 -> 868).
//
// rxd comes straight off a pin, so it goes through a 2-flop synchronizer
// first. A start bit is a falling edge that is still low half a bit later
// (shorter glitches are ignored); every later bit is sampled mid-bit.
//
// A byte is delivered as a 1-cycle `valid` pulse with `data`. If the stop
// bit is low the byte is dropped, `frame_err` pulses instead, and the
// receiver waits for the line to go idle (high) before looking for the
// next start bit -- otherwise the tail of a bad frame could be mistaken
// for a new start bit.

module uart_rx #(
    parameter CLKS_PER_BIT = 868
) (
    input  wire       clk,
    input  wire       rst_n,
    input  wire       rxd,

    output reg  [7:0] data,
    output reg        valid,
    output reg        frame_err
);

    localparam HALF_BIT = CLKS_PER_BIT / 2;

    localparam S_IDLE      = 3'd0;
    localparam S_START     = 3'd1;
    localparam S_DATA      = 3'd2;
    localparam S_STOP      = 3'd3;
    localparam S_WAIT_IDLE = 3'd4;

    reg        rx_meta, rx_sync;
    reg [2:0]  state;
    reg [15:0] cnt;
    reg [2:0]  bit_idx;
    reg [7:0]  shift;

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            rx_meta <= 1'b1;
            rx_sync <= 1'b1;
        end else begin
            rx_meta <= rxd;
            rx_sync <= rx_meta;
        end
    end

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state     <= S_IDLE;
            cnt       <= 16'd0;
            bit_idx   <= 3'd0;
            shift     <= 8'd0;
            data      <= 8'd0;
            valid     <= 1'b0;
            frame_err <= 1'b0;
        end else begin
            valid     <= 1'b0;
            frame_err <= 1'b0;

            case (state)
                S_IDLE: begin
                    cnt <= 16'd0;
                    if (rx_sync == 1'b0)
                        state <= S_START;
                end

                S_START: begin
                    if (cnt == HALF_BIT - 1) begin
                        cnt <= 16'd0;
                        if (rx_sync == 1'b0) begin
                            bit_idx <= 3'd0;
                            state   <= S_DATA;
                        end else begin
                            state <= S_IDLE;   // glitch, not a start bit
                        end
                    end else begin
                        cnt <= cnt + 16'd1;
                    end
                end

                S_DATA: begin
                    if (cnt == CLKS_PER_BIT - 1) begin
                        cnt   <= 16'd0;
                        shift <= {rx_sync, shift[7:1]};
                        if (bit_idx == 3'd7)
                            state <= S_STOP;
                        else
                            bit_idx <= bit_idx + 3'd1;
                    end else begin
                        cnt <= cnt + 16'd1;
                    end
                end

                S_STOP: begin
                    if (cnt == CLKS_PER_BIT - 1) begin
                        cnt <= 16'd0;
                        if (rx_sync == 1'b1) begin
                            data  <= shift;
                            valid <= 1'b1;
                            state <= S_IDLE;
                        end else begin
                            frame_err <= 1'b1;
                            state     <= S_WAIT_IDLE;
                        end
                    end else begin
                        cnt <= cnt + 16'd1;
                    end
                end

                S_WAIT_IDLE: begin
                    if (rx_sync == 1'b1)
                        state <= S_IDLE;
                end

                default: state <= S_IDLE;
            endcase
        end
    end

endmodule
