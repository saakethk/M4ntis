`timescale 1ns/1ps

// 32-bit signed divider for DIV (spec sections 2/4). Simulation-first
// stand-in for Vivado's Divider Generator IP: same shape of interface
// (pulse start with operands, wait for done), so swapping in the IP
// later only touches this file -- control_unit waits on done, it doesn't
// count cycles, so a different IP latency is fine.
//
// Restoring division on magnitudes, 2 quotient bits per cycle -> 16
// cycles, then done pulses for one cycle with the quotient valid. The
// quotient holds until the next start.
//
// Semantics:
//   - truncates toward zero (C / Verilog '/'), NOT floor: -100/7 = -14
//   - divisor 0 -> quotient 0, same latency, no fault (spec section 2)
//   - INT_MIN / -1 overflows; it wraps to INT_MIN (low 32 bits of +2^31)

module divider (
    input  wire        clk,
    input  wire        rst_n,

    input  wire        start,
    input  wire [31:0] dividend,
    input  wire [31:0] divisor,

    output reg         done,
    output wire [31:0] quotient
);

    reg        busy;
    reg [3:0]  count;
    reg [31:0] quo;       // dividend shifts out the top, quotient bits shift in
    reg [31:0] rem;
    reg [31:0] dvsr;
    reg        negate;
    reg        div_by_zero;

    wire [31:0] dividend_mag = dividend[31] ? (32'd0 - dividend) : dividend;
    wire [31:0] divisor_mag  = divisor[31]  ? (32'd0 - divisor)  : divisor;

    // two restoring steps per cycle
    wire [32:0] step1_shift = {rem, quo[31]};
    wire        step1_ge    = step1_shift >= {1'b0, dvsr};
    wire [32:0] step1_diff  = step1_shift - {1'b0, dvsr};
    wire [31:0] step1_rem   = step1_ge ? step1_diff[31:0] : step1_shift[31:0];
    wire [31:0] step1_quo   = {quo[30:0], step1_ge};

    wire [32:0] step2_shift = {step1_rem, step1_quo[31]};
    wire        step2_ge    = step2_shift >= {1'b0, dvsr};
    wire [32:0] step2_diff  = step2_shift - {1'b0, dvsr};
    wire [31:0] step2_rem   = step2_ge ? step2_diff[31:0] : step2_shift[31:0];
    wire [31:0] step2_quo   = {step1_quo[30:0], step2_ge};

    assign quotient = div_by_zero ? 32'd0 :
                      negate      ? (32'd0 - quo) : quo;

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            busy        <= 1'b0;
            done        <= 1'b0;
            count       <= 4'd0;
            quo         <= 32'd0;
            rem         <= 32'd0;
            dvsr        <= 32'd0;
            negate      <= 1'b0;
            div_by_zero <= 1'b0;
        end else begin
            done <= 1'b0;

            if (start) begin
                busy        <= 1'b1;
                count       <= 4'd0;
                quo         <= dividend_mag;
                rem         <= 32'd0;
                dvsr        <= divisor_mag;
                negate      <= dividend[31] ^ divisor[31];
                div_by_zero <= (divisor == 32'd0);
            end else if (busy) begin
                quo   <= step2_quo;
                rem   <= step2_rem;
                count <= count + 4'd1;
                if (count == 4'd15) begin
                    busy <= 1'b0;
                    done <= 1'b1;
                end
            end
        end
    end

endmodule
