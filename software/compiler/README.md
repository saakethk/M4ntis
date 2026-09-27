# TradeCPU strategy compiler

Turns a strategy document saved by the block editor (`m4ntis.strategy/v1`, see
`../frontend/dev-sketchout/README.md`) into TradeCPU assembly and machine code, following
`hardware/docs/tradecpu_full_specification.md`. It has no dependencies beyond Python 3.10+.

```bash
cd software/compiler
python3 -m tradecpu compile STRATEGY.json                 # print the assembly listing
python3 -m tradecpu compile STRATEGY.json -o build/       # .asm, .hex, .load_program.bin, .manifest.json
python3 -m tradecpu compile - --json < STRATEGY.json      # {ok, asm, hex, manifest, diagnostics}
python3 -m tradecpu compile STRATEGY.json --price-exp 1=1 # BUF1 prices arrive in dimes
python3 -m tradecpu simulate STRATEGY.json prices.csv     # run on the golden model, one row per tick
python3 -m tradecpu asm FILE.asm                          # assembly text -> hex words
python3 -m tradecpu disasm FILE.hex                       # hex words -> assembly text
python3 -m unittest discover -s tests
```

## Calling it from Python

The backend (`software/backend/helpers/compile.py`, route `POST /compile`) imports the compiler
directly instead of spawning the CLI:

```python
from tradecpu import CompileOptions, compile_to_json, compile_strategy

out = compile_to_json(doc)                       # same dict as `compile --json`; never raises on bad input
out = compile_to_json(doc, CompileOptions(price_exponents={0: 1}))  # BUF0 in dimes, others cents
out["ok"], out["diagnostics"]                    # [{level, message, node?}], node = editor block id
out["manifest"]["words"]                         # program words to upload

result = compile_strategy(doc)                   # raises CompileError(diagnostics) instead
result.words, result.asm, result.manifest
```

## Testing strategies on the FPGA with dummy data

`hwtest` runs each strategy on the board with synthetic prices and checks every message the board
sends against the simulator. It uses the same UART framing as `hardware/python/balance_test.py` and
needs `pip install pyserial`.

```bash
# See what the board should do, with no hardware attached
python3 -m tradecpu hwtest ../frontend/dev-sketchout/examples/*.strategy.json --dry-run

# On the board
python3 -m tradecpu hwtest my_strategy.json other.json --port COM4
python3 -m tradecpu hwtest my_strategy.json --port /dev/tty.usbserial-XXXX --patterns sine,walk -v
python3 -m tradecpu hwtest hand_written.asm --port COM4 --patterns prices.csv
```

- **Patterns.** `sine` (24-tick cycle), `walk` (seeded random walk), `ramp` (up then down),
  `steps` (jumps every 10 ticks), `spikes` (occasional ±12%) and `flat`. You can also pass a CSV
  with columns `buf0..buf4` of scaled prices. Each buffer gets its own base price and phase.
- **Per pattern.** The program is reloaded, run through its warm-up, then run for `--rounds` more
  rounds (default 60).
- **Output.** Mismatches are printed round by round (`-v` prints every round). A summary shows
  buy, sell and hold counts plus the final balance. It notes any pattern where the strategy never
  traded, since the trade paths weren't tested there.
- **Exit code** is non-zero on any mismatch or timeout.

## Modules

| File | What it is |
| --- | --- |
| `tradecpu/isa.py` | Opcodes, operand fields, `encode`/`decode`, UART `LOAD_PROGRAM` and `TICK` frames |
| `tradecpu/asm.py` | Text assembler/disassembler with labels, plus a peephole pass |
| `tradecpu/simulator.py` | Cycle-counting golden model of the RTL (strict mode rejects opcodes the RTL doesn't implement) |
| `tradecpu/blocks.py` | Block ports and param limits (kept in sync with the frontend by `tests/test_catalog_sync.py`) |
| `tradecpu/compiler.py` | Graph validation, expression building, register allocation, code generation, manifest |
| `tradecpu/hwtest.py` | Dummy price generators, UART runner, and `FakeBoard` for dry runs |

## Program shape

```text
START:     SETBALANCE <cents>; EMITBALANCE           load handshake
WARMUP:    (history-1) × [UPDATEALLSTOCKBUFFERS; EMITBALANCE]
TICK:      UPDATEALLSTOCKBUFFERS
           <exec chain from Start>
TICK_END:  GETBALANCE; EMITBALANCE; JMP TICK        one ack per tick round
```

**Host protocol.** After `LOAD_PROGRAM`, the host reads one `EMIT_BALANCE`. For each bar at the
strategy's resolution it sends one `TICK` per buffer (all five, with 0 for unused buffers), then reads
`DECISION_EVENT`s until the next `EMIT_BALANCE`.

The host has to wait for that acknowledgement before sending more, because each buffer stages only one
pending tick. The first `warmupTicks` rounds only fill history, so they never trade. The manifest
records the resolution, warm-up length, symbol per buffer and price exponents, so the backtester can
drive the program.

## How blocks lower

- **Numbers are fixed-point decimals.** Each buffer delivers prices at its price exponent: 2 means
  cents, and the host picks this per symbol so prices fit in int16. The balance is kept in cents.
  Constants are scaled at compile time, divides pre-multiply the numerator to keep precision, and
  intermediate values are capped at 4 decimal places.
- **If** only has `CMP_GT`, `CMP_LT` and `SUB` + `JMP_IF` to work with. `>=` and `<=` are compiled as
  the opposite strict comparison with Then and Else swapped. `==` and `!=` test the difference.
  AND means nesting an If in Then; OR means chaining an If in Else.
- **Lookbacks** map to `GETSTOCKPRICEBEFORE` (offset N) and `GETSUMPRICEBEFORE` (window N), in ticks.
- **SMA, Momentum, Power and Sqrt** expand into sums, divides, repeated `MUL`, and a Newton-loop
  integer square root.
- **Volatility and Mean Reversion Bands** unroll the variance over the window and then take the
  square root.
- **For** keeps its counter in a spare variable slot, taken from `VAR15` downward.
- **Buy and Sell** do `GETSTOCKPRICE × qty → UPDATEBALANCE → EMITDECISION`, where a sell is a
  negative amount.
- The compiler never emits `CMP_GTE`, `CMP_LTE`, `AND`, `OR`, `SELECT` or `HALT`. They are in the
  spec, but the current RTL doesn't implement them.
- `Log` fails to compile.
