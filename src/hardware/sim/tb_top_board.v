`timescale 1ns/1ps

// Board-level smoke test of tradecpu_top: the real 100 MHz pin -> MMCM ->
// BUFG -> 50 MHz core -> UART chain, using Vivado's own MMCME2_BASE /
// BUFG simulation models (compiled from the Vivado install by
// run_sim.sh). tb_stage6_uart covers the protocol in depth; this only
// checks that clocking, reset sequencing and the baud divisor are right
// as wired on the board. The MMCM model is slow to simulate (it models
// the 1 GHz VCO), so serial traffic is kept to one message each way.
//
// ======================= expected results ==========================
//
// - LED[15] (reset) lit until the MMCM locks, then released
// - clk50 period = 20.000 ns; core CLKS_PER_BIT = 434
// - prog_mem preloaded (hierarchically, before reset releases) with
//     0 C8001840  EMITDECISION qty=R0 (0 after reset), buf3, buy
//     1 50000000  JMP ...      2 00000001  ... 1 (park)
//   everything else 0, like the FPGA's power-up BRAM
//   -> out of reset the CPU sends one DECISION_EVENT on UART_TXD:
//        03 03 01 00 00, start bit 8680 ns wide
// - one TICK in on UART_RXD: 02 02 E8 03 (buf2 = 1000)
//   -> LED[2] lit (tick staged), LED[14] (error) off
// - press BTN[0] -> LED[15] lit, LED[2] cleared; release -> LED[15] off
// ===================================================================

module tb_top_board;

    localparam real BIT_NS = 8680.0;

    reg         clk100;
    reg  [3:0]  btn;
    reg         rxd;
    wire        txd;
    wire [15:0] led;

    integer errors;
    integer i;

    tradecpu_top dut (
        .CLK_100MHZ (clk100),
        .BTN        (btn),
        .UART_RXD   (rxd),
        .UART_TXD   (txd),
        .LED        (led)
    );

    always #5 clk100 = ~clk100;   // 100 MHz board oscillator

    // independent 8N1 decoder on UART_TXD
    integer   tx_n, kt;
    reg [7:0] tx_bytes [0:15];
    reg [7:0] tx_shift;
    always begin
        @(negedge txd);
        #(BIT_NS / 2.0);
        if (txd === 1'b0) begin
            for (kt = 0; kt < 8; kt = kt + 1) begin
                #(BIT_NS);
                tx_shift[kt] = txd;
            end
            #(BIT_NS);
            tx_bytes[tx_n] = tx_shift;
            tx_n = tx_n + 1;
        end
    end

    realtime t_fall, start_bit_ns, t_clk;
    initial begin
        start_bit_ns = 0.0;
        @(negedge led[15]);
        @(negedge txd);
        t_fall = $realtime;
        @(posedge txd);
        start_bit_ns = $realtime - t_fall;
    end

    task check32;
        input [8*48-1:0]    label;
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

    task check_true;
        input [8*48-1:0] label;
        input            cond;
        begin
            if (cond !== 1'b1) begin
                $display("FAIL: %0s", label);
                errors = errors + 1;
            end else begin
                $display("PASS: %0s", label);
            end
        end
    endtask

    task uart_send;
        input [7:0] b;
        integer k;
        begin
            rxd = 1'b0;
            #(BIT_NS);
            for (k = 0; k < 8; k = k + 1) begin
                rxd = b[k];
                #(BIT_NS);
            end
            rxd = 1'b1;
            #(BIT_NS);
        end
    endtask

    initial begin
        errors = 0;
        clk100 = 0;
        btn    = 4'b0000;
        rxd    = 1'b1;
        tx_n   = 0;

        #1;
        for (i = 0; i < 512; i = i + 1)
            dut.u_core.u_control_unit.prog_mem[i] = 32'd0;
        dut.u_core.u_control_unit.prog_mem[0] = 32'hC8001840;
        dut.u_core.u_control_unit.prog_mem[1] = 32'h50000000;
        dut.u_core.u_control_unit.prog_mem[2] = 32'h00000001;

        #100;
        check_true("reset held before MMCM lock (LED[15])", led[15] === 1'b1);

        wait (led[15] === 1'b0);
        $display("      (reset released at %0t ps)", $realtime);
        check_true("MMCM locked", dut.mmcm_locked === 1'b1);
        @(posedge dut.clk50);
        t_clk = $realtime;
        @(posedge dut.clk50);
        check_true("clk50 period = 20.000 ns",
                   ($realtime - t_clk) > 19.99 && ($realtime - t_clk) < 20.01);
        check32("core CLKS_PER_BIT (50 MHz / 115200)", dut.u_core.CLKS_PER_BIT, 434);

        // the TICK goes in while the DECISION_EVENT is going out
        uart_send(8'h02);
        uart_send(8'h02);
        uart_send(8'hE8);
        uart_send(8'h03);
        #1000;
        check_true("TICK buf2 staged (LED[2]), no error (LED[14])",
                   led[4:0] === 5'b00100 && led[14] === 1'b0);
        check32("staged price", $signed(dut.u_core.u_stock_buffers.g_buf[2].staged_price), 1000);

        wait (tx_n >= 5);
        check_true("DECISION_EVENT = 03 03 01 00 00",
                   tx_bytes[0] === 8'h03 && tx_bytes[1] === 8'h03 &&
                   tx_bytes[2] === 8'h01 && tx_bytes[3] === 8'h00 &&
                   tx_bytes[4] === 8'h00);
        check_true("TX start bit = 8680 ns", start_bit_ns > 8679.0 && start_bit_ns < 8681.0);
        $display("      (measured %0.1f ns)", start_bit_ns);

        btn[0] = 1'b1;
        #2000;
        check_true("BTN[0] held: reset (LED[15]), tick cleared",
                   led[15] === 1'b1 && led[2] === 1'b0);
        btn[0] = 1'b0;
        #10000;
        check_true("BTN[0] released: out of reset", led[15] === 1'b0);

        if (errors == 0)
            $display("tb_top_board: ALL TESTS PASSED -- clocking/reset/baud correct at board level");
        else
            $display("tb_top_board: %0d TEST(S) FAILED", errors);
        $finish;
    end

endmodule
