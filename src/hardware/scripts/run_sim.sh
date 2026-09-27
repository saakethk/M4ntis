#!/usr/bin/env bash
# Compiles and runs all TradeCPU testbenches with Icarus Verilog
# (iverilog + vvp), per spec Section 7 Stage 0.5's toolchain choice.
# Vivado is reserved for final checks only -- not used here.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
RTL_DIR="$ROOT_DIR/rtl"
SIM_DIR="$ROOT_DIR/sim"
BUILD_DIR="$SCRIPT_DIR/build"

mkdir -p "$BUILD_DIR"

FAIL=0

run_test () {
    local name="$1"
    shift
    echo "=== $name ==="
    if ! iverilog -g2005 -Wall -o "$BUILD_DIR/$name.vvp" "$@"; then
        echo "*** $name: COMPILE FAILED ***"
        FAIL=1
        return
    fi
    if ! (cd "$BUILD_DIR" && vvp "$name.vvp"); then
        echo "*** $name: SIMULATION FAILED ***"
        FAIL=1
    fi
    echo ""
}

run_test tb_register_file \
    "$RTL_DIR/register_file.v" \
    "$SIM_DIR/tb_register_file.v"

run_test tb_alu \
    "$RTL_DIR/alu.v" \
    "$SIM_DIR/tb_alu.v"

run_test tb_stage1_core \
    "$RTL_DIR/register_file.v" \
    "$RTL_DIR/alu.v" \
    "$RTL_DIR/stock_buffers.v" \
    "$RTL_DIR/divider.v" \
    "$RTL_DIR/var_store.v" \
    "$RTL_DIR/balance_reg.v" \
    "$RTL_DIR/uart_rx.v" \
    "$RTL_DIR/uart_tx.v" \
    "$RTL_DIR/sync_fifo.v" \
    "$RTL_DIR/uart_protocol.v" \
    "$RTL_DIR/control_unit.v" \
    "$RTL_DIR/tradecpu_core.v" \
    "$SIM_DIR/tb_stage1_core.v"

run_test tb_stage2_core \
    "$RTL_DIR/register_file.v" \
    "$RTL_DIR/alu.v" \
    "$RTL_DIR/stock_buffers.v" \
    "$RTL_DIR/divider.v" \
    "$RTL_DIR/var_store.v" \
    "$RTL_DIR/balance_reg.v" \
    "$RTL_DIR/uart_rx.v" \
    "$RTL_DIR/uart_tx.v" \
    "$RTL_DIR/sync_fifo.v" \
    "$RTL_DIR/uart_protocol.v" \
    "$RTL_DIR/control_unit.v" \
    "$RTL_DIR/tradecpu_core.v" \
    "$SIM_DIR/tb_stage2_core.v"

run_test tb_stage3_core \
    "$RTL_DIR/register_file.v" \
    "$RTL_DIR/alu.v" \
    "$RTL_DIR/stock_buffers.v" \
    "$RTL_DIR/divider.v" \
    "$RTL_DIR/var_store.v" \
    "$RTL_DIR/balance_reg.v" \
    "$RTL_DIR/uart_rx.v" \
    "$RTL_DIR/uart_tx.v" \
    "$RTL_DIR/sync_fifo.v" \
    "$RTL_DIR/uart_protocol.v" \
    "$RTL_DIR/control_unit.v" \
    "$RTL_DIR/tradecpu_core.v" \
    "$SIM_DIR/tb_stage3_core.v"

run_test tb_stage4_core \
    "$RTL_DIR/register_file.v" \
    "$RTL_DIR/alu.v" \
    "$RTL_DIR/stock_buffers.v" \
    "$RTL_DIR/divider.v" \
    "$RTL_DIR/var_store.v" \
    "$RTL_DIR/balance_reg.v" \
    "$RTL_DIR/uart_rx.v" \
    "$RTL_DIR/uart_tx.v" \
    "$RTL_DIR/sync_fifo.v" \
    "$RTL_DIR/uart_protocol.v" \
    "$RTL_DIR/control_unit.v" \
    "$RTL_DIR/tradecpu_core.v" \
    "$SIM_DIR/tb_stage4_core.v"

run_test tb_stage5_core \
    "$RTL_DIR/register_file.v" \
    "$RTL_DIR/alu.v" \
    "$RTL_DIR/stock_buffers.v" \
    "$RTL_DIR/divider.v" \
    "$RTL_DIR/var_store.v" \
    "$RTL_DIR/balance_reg.v" \
    "$RTL_DIR/uart_rx.v" \
    "$RTL_DIR/uart_tx.v" \
    "$RTL_DIR/sync_fifo.v" \
    "$RTL_DIR/uart_protocol.v" \
    "$RTL_DIR/control_unit.v" \
    "$RTL_DIR/tradecpu_core.v" \
    "$SIM_DIR/tb_stage5_core.v"

run_test tb_stage6_uart \
    "$RTL_DIR/register_file.v" \
    "$RTL_DIR/alu.v" \
    "$RTL_DIR/stock_buffers.v" \
    "$RTL_DIR/divider.v" \
    "$RTL_DIR/var_store.v" \
    "$RTL_DIR/balance_reg.v" \
    "$RTL_DIR/uart_rx.v" \
    "$RTL_DIR/uart_tx.v" \
    "$RTL_DIR/sync_fifo.v" \
    "$RTL_DIR/uart_protocol.v" \
    "$RTL_DIR/control_unit.v" \
    "$RTL_DIR/tradecpu_core.v" \
    "$SIM_DIR/tb_stage6_uart.v"

run_test tb_stage6_emit_balance \
    "$RTL_DIR/register_file.v" \
    "$RTL_DIR/alu.v" \
    "$RTL_DIR/stock_buffers.v" \
    "$RTL_DIR/divider.v" \
    "$RTL_DIR/var_store.v" \
    "$RTL_DIR/balance_reg.v" \
    "$RTL_DIR/uart_rx.v" \
    "$RTL_DIR/uart_tx.v" \
    "$RTL_DIR/sync_fifo.v" \
    "$RTL_DIR/uart_protocol.v" \
    "$RTL_DIR/control_unit.v" \
    "$RTL_DIR/tradecpu_core.v" \
    "$SIM_DIR/tb_stage6_emit_balance.v"

# Board top (tradecpu_top): real 100 MHz -> MMCM -> 50 MHz clocking, using
# Vivado's own MMCME2_BASE/BUFG simulation models from the install.
# Point XILINX_VIVADO at the install if it isn't the default path.
VIVADO_DIR="${XILINX_VIVADO:-/c/AMDDesignTools/2026.1/Vivado}"
UNISIM_DIR="$VIVADO_DIR/data/verilog/src"
echo "=== tb_top_board ==="
if [ -f "$UNISIM_DIR/unisims/MMCME2_BASE.v" ]; then
    # the unisim models need -g2012 and print harmless "choosing typ
    # expression" warnings; keep the log, show anything else
    if iverilog -g2012 -o "$BUILD_DIR/tb_top_board.vvp" -s tb_top_board -s glbl \
        "$RTL_DIR/register_file.v" \
        "$RTL_DIR/alu.v" \
        "$RTL_DIR/stock_buffers.v" \
        "$RTL_DIR/divider.v" \
        "$RTL_DIR/var_store.v" \
        "$RTL_DIR/balance_reg.v" \
        "$RTL_DIR/uart_rx.v" \
        "$RTL_DIR/uart_tx.v" \
        "$RTL_DIR/sync_fifo.v" \
        "$RTL_DIR/uart_protocol.v" \
        "$RTL_DIR/control_unit.v" \
        "$RTL_DIR/tradecpu_core.v" \
        "$RTL_DIR/tradecpu_top.v" \
        "$SIM_DIR/tb_top_board.v" \
        "$UNISIM_DIR/unisims/MMCME2_BASE.v" \
        "$UNISIM_DIR/unisims/MMCME2_ADV.v" \
        "$UNISIM_DIR/unisims/BUFG.v" \
        "$UNISIM_DIR/glbl.v" > "$BUILD_DIR/tb_top_board.compile.log" 2>&1; then
        grep -v "choosing typ expression" "$BUILD_DIR/tb_top_board.compile.log" || true
        if ! (cd "$BUILD_DIR" && vvp tb_top_board.vvp); then
            echo "*** tb_top_board: SIMULATION FAILED ***"
            FAIL=1
        fi
    else
        grep -v "choosing typ expression" "$BUILD_DIR/tb_top_board.compile.log" || true
        echo "*** tb_top_board: COMPILE FAILED ***"
        FAIL=1
    fi
else
    echo "SKIPPED: Vivado unisim models not found under $UNISIM_DIR"
    echo "         (set XILINX_VIVADO to the Vivado install to run this test)"
fi
echo ""

if [ "$FAIL" -ne 0 ]; then
    echo "One or more testbenches FAILED."
    exit 1
fi

echo "All testbenches completed successfully."
