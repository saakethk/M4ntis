# TradeCPU

A custom-designed CPU, built from scratch in Verilog, with a purpose-built
instruction set for executing algorithmic stock-trading strategies —
implemented on a Real Digital Urbana board (Xilinx Spartan-7,
`xc7s50csga324-2`).

This isn't a general-purpose CPU running trading software. It's an
application-specific processor whose entire instruction set — registers,
buffers, and opcodes — exists specifically to make strategies like moving
averages and threshold-crossing rules cheap and natural to execute
directly in hardware.

---

## Architecture

TradeCPU is a **single-cycle-class, non-pipelined** processor built around
a classic fetch → decode → execute → writeback FSM in `control_unit.v`.
It is not pipelined — one instruction fully completes before the next
begins fetching. Most opcodes take a fixed number of cycles (commonly 4,
fetch-to-fetch); a few (`DIV`, `GETSUMPRICEBEFORE`, `UPDATEALLSTOCKBUFFERS`)
are explicitly multi-cycle or block on an external event.

```
                    control_unit.v (fetch/decode/execute/writeback FSM)
                              |
        +---------------------+---------------------+
        |                     |                     |
 register_file.v          alu.v + divider.v    stock_buffers.v
   (R0-R7, 32-bit)       (ADD/SUB/MUL/CMP/DIV)   (5 x 30-entry
        |                                          circular buffers)
        |
 var_store.v (15 slots)   balance_reg.v (BALANCE)
        |                         |
        +------------+------------+
                      |
              uart_protocol.v / uart_rx.v / uart_tx.v / sync_fifo.v
                      |
              tradecpu_top.v (board pins, MMCM clock generation, LEDs)
```

The control unit is the hub — it reads and writes the register file,
drives the ALU/divider, and reads/advances the stock buffers, VAR store,
and BALANCE register, all through its own FSM states. Data doesn't flow
stage-to-stage through separate pipeline hardware; the control unit
sequences one instruction through all of these resources before moving to
the next.

**Clock:** the board's 100MHz oscillator drives an MMCM (`tradecpu_top.v`)
that generates a 50MHz clock, which the entire core runs on. This was a
deliberate, measured decision — real place-and-route timing showed the
design does not close at 100MHz (worst path ~10.3ns against a 10ns
budget) but closes comfortably at 50MHz (see Results below).

---

## Instruction set

27 opcodes (5 slots reserved for future use), operating on 8 general-purpose
32-bit signed registers, a dedicated 32-bit `BALANCE` register, 15 16-bit
`VAR` slots, and 5 independent 30-entry circular stock-price buffers.
Full opcode table, bit-level encoding, and semantics:
**[`docs/tradecpu_full_specification.md`](docs/tradecpu_full_specification.md)**
— the authoritative reference for anything precise.

Broad categories: arithmetic (`ADD`/`SUB`/`MUL`/`DIV`), comparisons and
logic, control flow (`JMP`/`JMP_IF`/`SELECT`), reading stock price history
(`GETSTOCKPRICE`/`GETSTOCKPRICEBEFORE`/`GETSUMPRICEBEFORE`), a small
variable store for reusing computed values within a tick, and balance
tracking (`SETBALANCE`/`UPDATEBALANCE`/`GETBALANCE`) with the ability to
report trade decisions and balance back to the host
(`EMITDECISION`/`EMITBALANCE`) over UART.

For a plain-language walkthrough instead of the bit-level spec, see
[`docs/tradecpu_opcode_guide.md`](docs/tradecpu_opcode_guide.md).

---

## Host communication (UART)

The board talks to a host machine over a 115200 baud, 8N1 serial
connection. Three things flow in, two flow out:

- **`LOAD_PROGRAM`** (host → board): loads a new bytecode program,
  instantly, without resynthesizing or reflashing.
- **`TICK`** (host → board): stages a price update for one stock buffer.
- **`DECISION_EVENT`** (board → host): reports a buy/sell decision.
- **`EMIT_BALANCE`** (board → host): reports the current balance.

Full wire format: [`docs/tradecpu_full_specification.md`](docs/tradecpu_full_specification.md)
§6.

---

## Repository layout

```
rtl/            Synthesizable Verilog — the actual CPU design
sim/            Icarus Verilog testbenches, one set per build stage
scripts/        run_sim.sh -- compiles and runs every testbench in sim/
checkpoints/    Reusable Vivado synthesis/timing sanity check (non-project
                mode; reads rtl/ directly, no bitstream, safe to re-run
                anytime)
docs/           Specification, roadmap, and team-facing reference docs
software/       Golden-model interpreter, compiler, and host script
                (software team's work)
bringup/        Hardware bring-up test script and guide
```

The Vivado-managed project folder (`Trade_CPU vivado/`) is a sibling to
this repo layout, not nested inside it, and is gitignored — Vivado
references the files under `rtl/` as sources rather than owning copies of
them.

---

## Build stages

The design was built and verified incrementally, one stage per spec
Section 7, each with its own testbench(es) and each fully passing before
the next began:

| Stage | What it added | Testbench(es) |
|---|---|---|
| 1 | Register file, ALU (`ADD`/`SUB`/`MUL`/`CMP_GT`/`CMP_LT`), fetch-decode-execute FSM | `tb_register_file.v`, `tb_alu.v`, `tb_stage1_core.v` |
| 2 | `LOAD_IMM`, `JMP`, `JMP_IF` — control flow, including loops via backward jumps | `tb_stage2_core.v` |
| 3 | 5×30 circular stock buffers, `GETSTOCKPRICE`/`GETSTOCKPRICEBEFORE`, blocking `UPDATEALLSTOCKBUFFERS` | `tb_stage3_core.v` |
| 4 | Multi-cycle `DIV`, `GETSUMPRICEBEFORE` | `tb_stage4_core.v` |
| 5 | `VAR` store, `BALANCE` (`SETBALANCE`/`UPDATEBALANCE`/`GETBALANCE`) | `tb_stage5_core.v` |
| 6 | UART RX/TX, `LOAD_PROGRAM`/`TICK`, `EMITDECISION`/`EMITBALANCE`, MMCM-generated 50MHz clock | `tb_stage6_uart.v`, `tb_stage6_emit_balance.v`, `tb_top_board.v` |

Every testbench self-checks against hand-computed expected values
(pass/fail via `$display`/`$finish`) — none require manual waveform
inspection to interpret. Run everything with:

```
bash scripts/run_sim.sh
```

Full build history, including the real design decisions made along the
way (why `BALANCE` counts cash-on-hand rather than net spend, why
`EMITDECISION` is a separate opcode from `UPDATEBALANCE`, why the clock
runs at 50MHz not 100MHz): [`docs/tradecpu_roadmap_updated.md`](docs/tradecpu_roadmap_updated.md).

---

## Verified results (real Vivado synthesis + place & route)

Reproducible via `checkpoints/run_checkpoint.tcl` (non-project mode, no
bitstream generated — see `checkpoints/README.md`):

- **Timing closes at 50MHz** with +5.31ns of worst-case setup slack, 0 of
  4369 endpoints failing. Worst hold slack +0.072ns, also met.
- **`prog_mem` synthesizes to real block RAM**, confirmed once Stage 6
  gave it a genuine write port.
- **Resource usage:** ~4% of LUTs, ~1.7% of flip-flops, 3 DSP48E1 blocks
  (used by `MUL` and the divider), 1 MMCM.
- 0 errors, 0 critical warnings across the full design.

---

## Current status

RTL is complete and verified in simulation and via real synthesis/timing
closure. Physical hardware bring-up (flashing the board and confirming
real UART round-trips) is in progress — see
[`bringup/`](bringup/README.md). Software (golden-model interpreter,
compiler, host script) is being developed in parallel — see
[`docs/tradecpu_software_team_tasks.md`](docs/tradecpu_software_team_tasks.md).