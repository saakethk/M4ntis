# TradeCPU Roadmap (Updated)

This replaces the original hour-by-hour hackathon roadmap. The original
`tradecpu_build_roadmap.md` is kept for historical reference, but two
things about it are now superseded and should not be followed as-written:

1. **Numbering**: follow the *specification's* Stage numbers (spec
   Section 7), not the original roadmap's Phase numbers. They drifted —
   e.g. the original Phase 1 mentions a `MOV` opcode that does not exist
   in the final ISA (spec Section 4). Wherever the two docs conflict, the
   specification wins.
2. **Timing split**: RTL is being built *before* the hackathon, not during
   it. The hackathon is scoped to the software stack plus final hardware
   integration. See below for exactly where the line falls and why.

---

## Why the split

RTL (register file → ALU → control flow → buffers → DIV → VAR/BALANCE →
UART) is the highest-uncertainty, least-recoverable-from-mid-hackathon
work — FSM bugs, timing closure, and multi-cycle logic are slow and
unpredictable to debug under a deadline. The software stack (Python
interpreter matching an already-fixed ISA spec, Blockly compiler
retarget, host UART script) is comparatively mechanical, easy to test in
isolation, and splits well across multiple people — which RTL debugging
does not.

Building RTL first also flips the hackathon's fallback ladder in our
favor: if the CPU already works going in, the *worst case* at the
hackathon becomes "software stack partially done, hand-assembled bytecode
still demos on real hardware" — already a strong demo floor, not a last
resort.

**Open item, not yet confirmed:** whether the hackathon's rules permit
pre-building the core project ahead of the event window. Most hackathons
restrict this to environment/toolchain setup only. Confirm with
organizers before relying on this plan — if pre-building isn't allowed,
this split needs to be revisited.

---

## Pre-hackathon scope: Specification Stages 1–6 (RTL)

Built and verified using hand-assembled bytecode test programs written
directly against the spec — not waiting on the golden model or compiler,
which don't exist yet at this point in the plan.

| Stage | Scope | Exit criteria | Status |
|---|---|---|---|
| 0 | ISA reference (the spec doc itself) | Already complete — spec is finalized | ✅ Done |
| 0.5 | Tooling: VS Code, Icarus Verilog + GTKWave, git repo, Vivado project (separate, sibling folder) | Toolchain runs a trivial program end to end | ✅ Done |
| 1 | Register file (32-bit ×8), ALU (ADD/SUB/MUL), CMP_GT/CMP_LT, control unit FSM | `(5+3)*2 > 6` program, stored and read back correctly | ✅ Done — committed, all tests passing |
| 2 | JMP, JMP_IF, 2-word immediate fetch (LOAD_IMM) | If/else program takes correct branch across 3+ scenarios | 🔧 In progress |
| 3 | 5×30 circular buffers, GETSTOCKPRICE, GETSTOCKPRICEBEFORE, UPDATEALLSTOCKBUFFERS (blocking) | Wraparound correct; blocking behavior verified both ways | ⬜ Not started |
| 4 | DIV (Vivado Divider Generator IP), GETSUMPRICEBEFORE | Divide-by-zero returns 0; sum at N=30 correct | ⬜ Not started |
| 5 | VAR store (ASSIGNVAR/GETVAR), BALANCE (GETBALANCE/UPDATEBALANCE, no internal multiply) | Buy-then-sell sequence produces hand-calculated balance | ⬜ Not started |
| 6 | UART RX/TX + FIFO, LOAD_PROGRAM/TICK/DECISION_EVENT wire protocol | Program loads over UART; tick stream updates buffers, observable via LEDs/serial | ⬜ Not started |

**Workflow per stage** (established in Stage 1, carries forward):
- One Claude Code prompt per stage, scoped tightly to that stage's opcodes
  only — no reaching ahead into later stages' opcodes/features.
- Testbenches self-check against hand-computed expected values in a
  clearly labeled block (not a golden model yet — see below).
- `scripts/run_sim.sh` runs all testbenches, old and new, in one command —
  every stage's tests must keep passing as later stages are added.
- Commit to git after each stage passes, before starting the next.
- RTL source files live in `rtl/`/`sim/`/`scripts/`, kept as siblings to
  the Vivado-managed project folder — never inside it, never copied into
  Vivado's `.srcs`. Vivado references the files, it doesn't own them.

---

## Hackathon scope: software stack + Stage 7 integration

| Component | Description |
|---|---|
| Golden model | Python interpreter implementing the ISA exactly (spec Section 4), owned by the software team. Once it exists, Stage 1–6 testbenches get upgraded from hand-computed expected values to golden-model comparisons. |
| Compiler retarget | Blockly block tree → TradeCPU bytecode, per the roadmap's original Phase 6 approach (new generator alongside the existing one, two-pass assembler for jump resolution). Fallback: hand-written bytecode assembler if this runs long. |
| Host UART script | Python + pyserial, sends `LOAD_PROGRAM`/`TICK` messages and reads `DECISION_EVENT` per spec Section 6's wire protocol. |
| **Stage 7** | Full integration on real hardware: a corrected real strategy program (e.g. the rescaled MACD example) produces correct decisions end-to-end, using the golden model, compiler, and host script all together. |

This is where the original roadmap's Phase 6/7 content (scope-creep
warning, fallback checkpoints, demo polish) still applies directly — no
changes needed there, just note it now starts from a working CPU rather
than needing to build one under time pressure.

---

## Fallback checkpoints (updated)

Because RTL already works going in, the floor is higher than the original
roadmap assumed:

- **Worst case:** RTL complete (Stages 1–6), software stack incomplete —
  demo with hand-assembled bytecode sent manually over UART, live on
  hardware. Already a legitimate, fully-working hardware demo.
- **Middle case:** golden model + host script done, compiler not finished
  — demo hand-crafted-but-verified bytecode, live tick streaming, correct
  decisions on hardware. Compiler explained via slides/walkthrough.
- **Best case:** full pipeline — Blockly blocks → compiler → UART → FPGA
  → visible decision stream, live, repeatable 3+ times in a row (Stage 7
  exit criteria).
