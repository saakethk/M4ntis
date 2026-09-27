# checkpoints/

A synthesis + implementation sanity check of the **real** design
(`rtl/tradecpu_top.v` and everything under it) for the Urbana board's
xc7s50csga324-2: resource use, FSM/latch inference, DRC/methodology
warnings, and -- the point of it -- real post-route timing at the clock the
design actually runs at.

It uses Vivado **non-project mode**: it reads `rtl/*.v` straight from the
repo, runs synth -> opt -> place -> route in memory, writes reports, and
exits. It never opens, edits or depends on the Vivado project folder. No
bitstream is generated.

## Files

- `run_checkpoint.tcl` -- the whole flow.
- `tradecpu_top_checkpoint.xdc` -- constraints: `create_clock` on the
  100 MHz `CLK_100MHZ` pin, pin/IOSTANDARD lines copied verbatim from
  Urbana.xdc for the ports `tradecpu_top` has, and false paths on the
  asynchronous I/O (buttons, LEDs, UART pins). The 50 MHz core clock is
  **not** constrained by hand: Vivado derives it from the MMCM
  (100 MHz x 10 / 20). This file doubles as a ready-made constraints set
  for bring-up.
- `reports/` -- output of the latest run (`summary.txt` first).

## How to run

From a scratch directory (Vivado drops `.Xil/` and `vivado.log` into the
current dir):

```
vivado -mode batch -nojournal -source "<repo>/checkpoints/run_checkpoint.tcl"
```

Reports go to `checkpoints/reports/` (pass `-tclargs <dir>` to change
that). Takes a few minutes. Nothing needs regenerating between stages --
it always builds whatever is in `rtl/` now.

**Paths with spaces:** on Windows, `vivado.bat` splits quoted arguments
at spaces, and this repo lives under `.../Trade CPU/`. `-source` copes,
and the script re-joins a split `-tclargs`, but don't point `-log` into
the repo -- let the log land in the scratch directory. If anything else
misbehaves, use a tiny launcher Tcl in a space-free directory:

```
set argv [list {<repo>/checkpoints/reports}]; set argc 1
source {<repo>/checkpoints/run_checkpoint.tcl}
```

## History: why the old harness is gone

The Stage 2 harness (`control_unit_checkpoint.v`,
`tradecpu_core_checkpoint.v`, a `.hex` program, and a `DONT_TOUCH` xdc --
all still in git history at `f0b5b21`) existed because back then
`prog_mem` had no write path and `tradecpu_core` had no outputs, so
synthesis swept the whole design away. It worked around that with a
cloned control unit that `$readmemh`-loaded a fixed program. Stage 6 fixed
both problems for real -- LOAD_PROGRAM writes `prog_mem` from the UART pin,
and the UART TX pin and LEDs are real outputs -- so the actual design now
synthesizes as-is and the clone is obsolete.

That harness's timing run (100 MHz, on a Stage 2-sized design) missed
timing: worst path 10.283 ns against a 10 ns budget. That is why the core
now runs at 50 MHz from an MMCM (see `rtl/tradecpu_top.v`).

## Latest results

Stage 6 design (full CPU + UART + MMCM, including EMITBALANCE), Vivado
2026.1, xc7s50csga324-2, core on the MMCM's 50 MHz clock (`clk50_mmcm`,
20 ns). Full reports in `reports/`.

**Timing: met, with real margin.**

| | |
|---|---|
| Worst setup slack (WNS) | **+5.310 ns** on a 20 ns period (0 failing of 4369 endpoints) |
| Worst hold slack (WHS)  | +0.072 ns (0 failing) |
| Pulse width (WPWS)      | +3.000 ns |
| Implied max clock       | 1 / (20 - 5.310 ns) = ~68 MHz |

`check_timing`: 0 unclocked registers, 0 unconstrained internal
endpoints, 0 combinational loops. The only ports without I/O delays are
the 2 inputs / 17 outputs deliberately cut as asynchronous in the xdc.

Worst path: `prog_mem` block RAM (instruction word) -> operand select ->
32x32 `MUL` (two cascaded DSP48E1s) -> register file write, 11 logic
levels. The next worst paths are the same shape. (The previous run,
before EMITBALANCE, had 4.929 ns on the same path -- the difference is
placement variation, not a design change on that path.) At 100 MHz this
path would miss by ~5 ns -- the move to 50 MHz was necessary, not just
cautious.

**Errors / warnings:** 0 errors, 0 critical warnings, 39 warnings, all
expected:
- 38x `Synth 8-7129` unused port bits -- `var_store.wdata[31:16]` (ASSIGNVAR
  keeps only the low 16 bits, by design) and `BTN[3:1]` (unused buttons).
- 1x `Synth 8-13373` a DSP48E1 removed by constant propagation -- the
  partial product that only feeds the discarded upper 32 bits of `MUL`.

**Resources (post-route):** 1306 LUTs (4.0%), 1104 FFs (1.7%), 84 LUTs as
memory (stock buffers + 33-bit outgoing message FIFO), 1 Block RAM tile
(`prog_mem` -- it did infer real BRAM), 3 DSP48E1 (`MUL`), 20 IOBs, 1 BUFG,
1 MMCM.

**FSM / latch inference:** FSMs extracted for `uart_rx.state` and
`uart_protocol.rstate` (sequential encoding). `control_unit.state` is kept
as a plain register. No latches inferred, 0 latch loops.

**DRC / methodology (warnings only, reviewed, benign here):**
- `REQP-1840` RAMB18 async control check: `prog_mem`'s address/write-enable
  registers use async reset. Every reset source is itself a clk50 flop,
  so these are timed like any other path.
- `LUTAR-1` LUT drives async reset: `cpu_rst_n = rst_n & ~cpu_hold`. Both
  are clk50 flops; the only simultaneous-opposite-change case is entering
  reset anyway. Registering `cpu_rst_n` would clear the warning if wanted.
- `DPIP-1` / `SYNTH-10` / `SYNTH-6`: the multiplier and the `prog_mem` read
  aren't pipelined. They'd matter for a higher clock; at 50 MHz there's
  ~5 ns to spare.
