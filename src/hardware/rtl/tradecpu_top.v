`timescale 1ns/1ps

// Urbana board top (xc7s50csga324-2). Port names match Urbana.xdc exactly
// so its existing pin lines apply as-is:
//   CLK_100MHZ  N15  LVCMOS33    UART_RXD  A16  LVCMOS33  (host -> FPGA)
//   BTN[0]      J2   LVCMOS25    UART_TXD  B16  LVCMOS33  (FPGA -> host)
//   LED[15:0]   C13..G17 LVCMOS33
// Urbana.xdc's own create_clock is commented out and names a port that
// doesn't exist; it needs
//   create_clock -period 10.000 -name gclk [get_ports CLK_100MHZ]
//
// Clocking: the design doesn't close timing at 100 MHz, so an MMCM makes
// clk50 = 100 MHz * 10 / 20 (VCO 1000 MHz) and the WHOLE core runs on it --
// CPU and UART alike, one clock domain, nothing to cross. tradecpu_core
// therefore gets CLK_HZ = 50 MHz -> 434 clocks per bit at 115200 baud
// (0.007% off). Only the MMCM input sees the 100 MHz pin; Vivado derives
// the 50 MHz clock constraint from the MMCM automatically.
//
// Reset (all in the clk50 domain): held until the MMCM reports LOCKED,
// then a short power-on count; BTN[0] held = reset. BTN_ACTIVE_HIGH
// assumes a pressed button reads 1 -- confirm at bring-up (if LED[15]
// stays lit with nothing pressed, flip it).
//
// LEDs:
//   [4:0]  a tick is staged for buffer 0..4 (lit by TICK, cleared when
//          UPDATEALLSTOCKBUFFERS consumes the round)
//   [9:5]  number of buffer advances, mod 32
//   [10]   a program has been loaded
//   [11]   LOAD_PROGRAM in progress / CPU held (stays lit after a load
//          that timed out part-way)
//   [12]   flips on every complete TICK / LOAD_PROGRAM received
//   [13]   flips on every DECISION_EVENT sent (not on EMIT_BALANCE -- a
//          strategy that reports balance after each trade would flip it
//          twice per trade and it would look stuck; all 16 LEDs are
//          already in use, so balance gets no LED of its own)
//   [14]   protocol error seen (sticky until reset)
//   [15]   board reset active

module tradecpu_top #(
    parameter BTN_ACTIVE_HIGH = 1
) (
    input  wire        CLK_100MHZ,
    input  wire [3:0]  BTN,
    input  wire        UART_RXD,
    output wire        UART_TXD,
    output wire [15:0] LED
);

    // ---------------- 100 MHz -> 50 MHz ----------------

    wire clk_fb;
    wire clk50_mmcm;
    wire mmcm_locked;
    wire clk50;

    MMCME2_BASE #(
        .CLKIN1_PERIOD    (10.0),   // 100 MHz in
        .DIVCLK_DIVIDE    (1),
        .CLKFBOUT_MULT_F  (10.0),   // VCO = 1000 MHz
        .CLKOUT0_DIVIDE_F (20.0)    // 50 MHz out
    ) u_mmcm (
        .CLKIN1    (CLK_100MHZ),
        .CLKFBIN   (clk_fb),
        .CLKFBOUT  (clk_fb),
        .CLKOUT0   (clk50_mmcm),
        .LOCKED    (mmcm_locked),
        .RST       (1'b0),
        .PWRDWN    (1'b0),
        .CLKFBOUTB (),
        .CLKOUT0B  (),
        .CLKOUT1   (),
        .CLKOUT1B  (),
        .CLKOUT2   (),
        .CLKOUT2B  (),
        .CLKOUT3   (),
        .CLKOUT3B  (),
        .CLKOUT4   (),
        .CLKOUT5   (),
        .CLKOUT6   ()
    );

    BUFG u_bufg_clk50 (
        .I (clk50_mmcm),
        .O (clk50)
    );

    // ---------------- reset, clk50 domain ----------------

    reg [1:0] locked_sync = 2'b00;
    reg [7:0] por_cnt     = 8'd0;
    reg       btn_meta    = 1'b0;
    reg       btn_sync    = 1'b0;
    reg       rst_n       = 1'b0;

    wire btn_pressed = BTN_ACTIVE_HIGH ? btn_sync : ~btn_sync;

    always @(posedge clk50) begin
        locked_sync <= {locked_sync[0], mmcm_locked};
        btn_meta    <= BTN[0];
        btn_sync    <= btn_meta;
        if (!locked_sync[1])
            por_cnt <= 8'd0;
        else if (por_cnt != 8'hFF)
            por_cnt <= por_cnt + 8'd1;
        rst_n <= (por_cnt == 8'hFF) && !btn_pressed;
    end

    wire [4:0] tick_pending;
    wire [4:0] advance_count;
    wire       prog_loaded, loading, proto_error, rx_toggle, tx_toggle;

    tradecpu_core #(
        .CLK_HZ (50000000),     // clk50, not the 100 MHz pin
        .BAUD   (115200)
    ) u_core (
        .clk               (clk50),
        .rst_n             (rst_n),
        .tick_valid        (1'b0),
        .tick_buf_id       (3'd0),
        .tick_price        (16'd0),
        .UART_RXD          (UART_RXD),
        .UART_TXD          (UART_TXD),
        .dbg_tick_pending  (tick_pending),
        .dbg_advance_count (advance_count),
        .dbg_prog_loaded   (prog_loaded),
        .dbg_loading       (loading),
        .dbg_proto_error   (proto_error),
        .dbg_rx_msg_toggle (rx_toggle),
        .dbg_tx_msg_toggle (tx_toggle)
    );

    assign LED[4:0]  = tick_pending;
    assign LED[9:5]  = advance_count;
    assign LED[10]   = prog_loaded;
    assign LED[11]   = loading;
    assign LED[12]   = rx_toggle;
    assign LED[13]   = tx_toggle;
    assign LED[14]   = proto_error;
    assign LED[15]   = !rst_n;

endmodule
