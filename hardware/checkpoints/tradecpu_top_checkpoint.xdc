# SYNTHESIS-CHECKPOINT CONSTRAINTS -- see checkpoints/README.md.
# Constraints for rtl/tradecpu_top.v on the Urbana board. Pin/IOSTANDARD
# lines are copied verbatim from Urbana.xdc (V2I1) for the ports the
# design actually has; this file is also a ready-made constraints set for
# real bring-up.

## Clock: the 100 MHz oscillator into the MMCM. Vivado derives the MMCM's
## 50 MHz output clock (the one the whole core runs on) automatically --
## it is NOT constrained by hand here.
create_clock -period 10.000 -name clk100 [get_ports CLK_100MHZ]
set_property -dict {PACKAGE_PIN N15 IOSTANDARD LVCMOS33} [get_ports {CLK_100MHZ}]

## Bank 0 configuration voltage (from Urbana.xdc)
set_property CFGBVS VCCO [current_design]
set_property CONFIG_VOLTAGE 3.3 [current_design]

## USB-UART bridge
set_property -dict {PACKAGE_PIN B16 IOSTANDARD LVCMOS33} [get_ports {UART_TXD}]
set_property -dict {PACKAGE_PIN A16 IOSTANDARD LVCMOS33} [get_ports {UART_RXD}]

## Push buttons (BTN[0] = reset; 1-3 unused but still ports)
set_property -dict {PACKAGE_PIN J2 IOSTANDARD LVCMOS25} [get_ports {BTN[0]}]
set_property -dict {PACKAGE_PIN J1 IOSTANDARD LVCMOS25} [get_ports {BTN[1]}]
set_property -dict {PACKAGE_PIN G2 IOSTANDARD LVCMOS25} [get_ports {BTN[2]}]
set_property -dict {PACKAGE_PIN H2 IOSTANDARD LVCMOS25} [get_ports {BTN[3]}]

## LEDs
set_property -dict {PACKAGE_PIN C13 IOSTANDARD LVCMOS33} [get_ports {LED[0]}]
set_property -dict {PACKAGE_PIN C14 IOSTANDARD LVCMOS33} [get_ports {LED[1]}]
set_property -dict {PACKAGE_PIN D14 IOSTANDARD LVCMOS33} [get_ports {LED[2]}]
set_property -dict {PACKAGE_PIN D15 IOSTANDARD LVCMOS33} [get_ports {LED[3]}]
set_property -dict {PACKAGE_PIN D16 IOSTANDARD LVCMOS33} [get_ports {LED[4]}]
set_property -dict {PACKAGE_PIN F18 IOSTANDARD LVCMOS33} [get_ports {LED[5]}]
set_property -dict {PACKAGE_PIN E17 IOSTANDARD LVCMOS33} [get_ports {LED[6]}]
set_property -dict {PACKAGE_PIN D17 IOSTANDARD LVCMOS33} [get_ports {LED[7]}]
set_property -dict {PACKAGE_PIN C17 IOSTANDARD LVCMOS33} [get_ports {LED[8]}]
set_property -dict {PACKAGE_PIN B18 IOSTANDARD LVCMOS33} [get_ports {LED[9]}]
set_property -dict {PACKAGE_PIN A17 IOSTANDARD LVCMOS33} [get_ports {LED[10]}]
set_property -dict {PACKAGE_PIN B17 IOSTANDARD LVCMOS33} [get_ports {LED[11]}]
set_property -dict {PACKAGE_PIN C18 IOSTANDARD LVCMOS33} [get_ports {LED[12]}]
set_property -dict {PACKAGE_PIN D18 IOSTANDARD LVCMOS33} [get_ports {LED[13]}]
set_property -dict {PACKAGE_PIN E18 IOSTANDARD LVCMOS33} [get_ports {LED[14]}]
set_property -dict {PACKAGE_PIN G17 IOSTANDARD LVCMOS33} [get_ports {LED[15]}]

## Asynchronous I/O -- no board-level I/O timing to meet: buttons and the
## 115200-baud RX line go through 2-flop synchronizers, LEDs are for eyes,
## and TXD changes once per 8.68 us bit. Cut them so they don't show up
## as unconstrained paths or dilute the internal timing numbers.
set_false_path -from [get_ports {BTN[*] UART_RXD}]
set_false_path -to   [get_ports {LED[*] UART_TXD}]
