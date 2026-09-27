`timescale 1ns/1ps

// register_file checks: async reset clears everything, each reg
// (including R0 -- no hardwire-zero) writes/reads independently, and
// both read ports work at the same time.

module tb_register_file;

    // expected values, hand-computed
    localparam signed [31:0] EXPECTED_AFTER_RESET = 32'sd0;
    localparam signed [31:0] EXPECTED_R0           = 32'sd42;        // R0 is writable
    localparam signed [31:0] EXPECTED_R3           = -32'sd17;
    localparam signed [31:0] EXPECTED_R7           = 32'sh7FFFFFFF;  // max positive signed

    reg         clk;
    reg         rst_n;
    reg         we;
    reg  [2:0]  waddr;
    reg  [31:0] wdata;
    reg  [2:0]  raddr1;
    reg  [2:0]  raddr2;
    wire [31:0] rdata1;
    wire [31:0] rdata2;

    integer errors;

    register_file dut (
        .clk    (clk),
        .rst_n  (rst_n),
        .we     (we),
        .waddr  (waddr),
        .wdata  (wdata),
        .raddr1 (raddr1),
        .raddr2 (raddr2),
        .rdata1 (rdata1),
        .rdata2 (rdata2)
    );

    always #5 clk = ~clk;

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
        clk    = 0;
        rst_n  = 0;
        we     = 0;
        waddr  = 0;
        wdata  = 0;
        raddr1 = 0;
        raddr2 = 0;

        // hold reset for a couple cycles
        @(negedge clk);
        @(negedge clk);
        raddr1 = 0; raddr2 = 7;
        #1;
        check32("reset clears R0", rdata1, EXPECTED_AFTER_RESET);
        check32("reset clears R7", rdata2, EXPECTED_AFTER_RESET);

        rst_n = 1;
        @(negedge clk);

        // R0 isn't hardwired -- make sure it actually takes a write
        we = 1; waddr = 3'd0; wdata = EXPECTED_R0;
        @(negedge clk);
        we = 0;
        raddr1 = 3'd0;
        #1;
        check32("R0 write/read", rdata1, EXPECTED_R0);

        we = 1; waddr = 3'd3; wdata = EXPECTED_R3;
        @(negedge clk);
        we = 0;
        raddr1 = 3'd3;
        #1;
        check32("R3 write/read negative", rdata1, EXPECTED_R3);

        we = 1; waddr = 3'd7; wdata = EXPECTED_R7;
        @(negedge clk);
        we = 0;

        raddr1 = 3'd0; raddr2 = 3'd7;
        #1;
        check32("dual-read port1 (R0)", rdata1, EXPECTED_R0);
        check32("dual-read port2 (R7)", rdata2, EXPECTED_R7);

        raddr1 = 3'd3;
        #1;
        check32("R3 unaffected by other writes", rdata1, EXPECTED_R3);

        if (errors == 0)
            $display("tb_register_file: ALL TESTS PASSED");
        else
            $display("tb_register_file: %0d TEST(S) FAILED", errors);

        $finish;
    end

endmodule
