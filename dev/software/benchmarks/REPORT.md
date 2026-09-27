# Benchmark: TradeCPU (FPGA) vs BabyQuant (on-device Python)

**Question.** Both projects let users build trading strategies from blocks and backtest them.
BabyQuant runs the strategy in Python on the user's machine. TradeCPU compiles it to a custom
instruction set and runs it on a Spartan-7 FPGA. Which one executes a backtest faster, and how
does compile time compare with execution time?

**Short answer.**

1. **Strategy execution: the FPGA core is 13–263× faster than BabyQuant.** It evaluates a bar in
   3.0–37 µs. BabyQuant takes 361–789 µs per bar, and its per-bar cost grows as the dataset grows.
2. **End to end, the FPGA is currently 4.6–7.2× slower on 1-month to 1-year backtests, and about
   level at 5 years.** Almost all of its time (98.4–99.9%) is spent sending prices over the
   115200-baud UART, not computing. Raising the baud rate to 921,600, a one-parameter RTL change,
   is projected to make it faster than BabyQuant for all three strategies tested.
3. **Compile time is not the FPGA's weak point.** Compiling a strategy takes 0.18–0.71 ms, and
   loading it onto the board takes 19–106 ms. The only slow step is building the FPGA bitstream,
   which takes a few minutes but happens once per hardware change, not once per strategy.
   BabyQuant has no separate compile step, but it recompiles the strategy source on every bar
   (34–59 µs each time), about 3.3 s per year of minute data.
4. **For honesty:** a hand-optimized CPU loop beats both projects. Plain Python is 10–87× faster
   than the FPGA core, and C is roughly 1,400–5,900× faster. The FPGA's advantage over BabyQuant
   comes from avoiding BabyQuant's interpreter and pandas overhead, not from raw compute speed.

---

## 1. Systems compared

| | **BabyQuant** ([repo](https://github.com/jsaluja09ufl/BabyQuant), commit `f483633`) | **TradeCPU** (this repo) |
| --- | --- | --- |
| Block editor | Blockly | React Flow |
| What the blocks become | A Python source string (`src/frontend/src/generators/python.ts`) | TradeCPU machine code (`software/compiler`) |
| Where it runs | On the user's machine, in `Backtest.backtest()` (`src/backend/backtest.py`) | On a Spartan-7 FPGA: custom 50 MHz, non-pipelined CPU |
| Per-bar mechanism | `exec(self.algorithm)`, which recompiles the string every bar. Each price or indicator lookup is `df[df.index == timestamp]`, a scan of the whole DataFrame. | The host sends 5 `TICK` frames, the CPU runs the compiled program, and replies with `DECISION` and `BALANCE` frames |
| Indicators | Precomputed with pandas before the loop, then looked up each bar | Computed each bar from the 30-tick on-chip price buffers |
| Data path | yfinance DataFrame in RAM | UART at 115200 baud, 8N1 |

## 2. Methodology

**Test machine:** Apple M3 (8 cores), 24 GB RAM, macOS 26.6.2, Python 3.13.7, pandas 2.3.3,
numpy 2.2.6, Apple clang 16.0.0.

**Data:** synthetic one-minute bars during market hours (390 per day) from a seeded random walk
starting at $150. Prices stay under $327.67 so they fit TradeCPU's int16 cents. Both systems
receive the same bars.

**Strategies:** the three TradeCPU example templates, plus BabyQuant's own sample strategy.

| ID | Rule | TradeCPU size |
| --- | --- | --- |
| `sma` | Buy 10 if SMA(10) > SMA(30), else sell 10 | 54 words |
| `trend` | If SMA(12) > SMA(26) and price > SMA(12), buy. Else if price < SMA(26), sell. | 72 words |
| `meanrev` | Buy if price ≤ mean(20) − 2σ. Else sell if price ≥ mean(20) + 2σ. | 303 words |
| `bq_native_rsi` | BabyQuant's `testing/backtest_test.py` sample: on Mondays after 7 AM, buy if RSI < 30, sell if RSI > 70 | not expressible in TradeCPU (no RSI or clock block) |

BabyQuant's user interface has no price or SMA blocks. For `sma`, `trend` and `meanrev` we
therefore wrote the strategy as the same kind of Python its generator produces
(`self.get_indicator(...)`, `self.get_price(...)`, `self.buy_stock(...)`). The indicators were
precomputed with pandas, the same way BabyQuant precomputes RSI and MACD.

**How each side was measured:**

- **BabyQuant:** we imported and ran its own `Backtest` and `Stock` classes, unmodified. We
  replaced only the yfinance download (with the synthetic DataFrame above) and stubbed the
  sentiment modules, which these strategies never call. Each size is the best of 3 runs, with the
  per-bar `print` sent to `/dev/null`. We also timed a run with `print` disabled; it made no
  meaningful difference. One run on a full year of minute bars (98,251 bars) was measured
  directly rather than extrapolated.
- **TradeCPU compile:** `compile_strategy()` on the host, median of 30 runs.
- **TradeCPU execution:** cycle counts from the project's golden-model simulator, divided by the
  50 MHz core clock. The simulator's cycle costs match the RTL state machine in
  `hardware/rtl/control_unit.v`: 4 cycles per 1-word op, 5 per 2-word op, 20 for `DIV` and N+3
  for `GETSUMPRICEBEFORE`. The last two are also asserted in `hardware/sim/tb_stage4_core.v`.
  We ran 19,500 bars (50 trading days) per strategy.
- **TradeCPU UART time:** bytes on the wire × 10 bits ÷ 115200. Each bar sends 5 `TICK` frames
  (20 bytes) and receives 5 bytes per reply message: one `BALANCE`, plus one `DECISION` per trade.
  The protocol is sequential, because the host waits for the `BALANCE` before sending the next bar.
- **Correctness check:** all 19,471 TradeCPU `sma` decisions after warm-up matched an independent
  pandas implementation of the same integer rule. The trade counts in `results.json` differ from
  BabyQuant's because BabyQuant's order logic skips sells when nothing is held and caps buys at
  available cash. Both systems still evaluate the strategy on every bar.
- **Reference baselines:** the same three rules as a streaming loop in plain Python, and in C
  compiled with `clang -O2` (`baseline.c`).

Raw output from every run is in [`results.json`](results.json).

## 3. Results

### 3.1 Compile and setup time (paid once per strategy)

| Step | `sma` | `trend` | `meanrev` |
| --- | ---: | ---: | ---: |
| **TradeCPU:** compile blocks to machine code (host) | 0.18 ms | 0.27 ms | 0.71 ms |
| **TradeCPU:** `LOAD_PROGRAM` over UART | 219 B → 19.0 ms | 291 B → 25.3 ms | 1,215 B → 105.5 ms |
| **TradeCPU total per strategy** | **≈ 19 ms** | **≈ 26 ms** | **≈ 106 ms** |
| TradeCPU: FPGA bitstream build (once per hardware change, not per strategy) | a few minutes (per `hardware/checkpoints/README.md`; not measured here) | | |
| **BabyQuant:** up-front compile | none (Blockly generates the Python string in the browser; not measured) | | |
| **BabyQuant:** indicator precompute (pandas) | 0.9–1.6 ms (≤15.6k bars); 5.2 ms at 1 year | 1.0–1.6 ms | 1.2–1.8 ms |
| **BabyQuant:** hidden per-bar recompile of the strategy by `exec()` | **33.8 µs/bar** | **59.3 µs/bar** | **45.4 µs/bar** |
| BabyQuant: that recompile summed over 1 year of minute bars | 3.3 s | 5.8 s | 4.5 s |
| Reference: `clang -O2` compile of the C baseline | 126 ms | | |

**Takeaway.** Per strategy, TradeCPU's compile step is sub-millisecond, and loading is limited by
the UART. The expectation that the FPGA side compiles slowly only holds for the bitstream build,
which is not part of the per-strategy workflow. BabyQuant never compiles up front, so its compile
cost is paid again inside execution on every bar, and it grows with the length of the backtest.

### 3.2 Execution time per bar, compute only

| Strategy | BabyQuant (1 month, ≈1,530 bars) | BabyQuant (1 year, 98,251 bars) | TradeCPU core @ 50 MHz (mean / max cycles) | **Speedup (FPGA core vs BabyQuant)** |
| --- | ---: | ---: | ---: | ---: |
| `sma` | 361 µs | 789 µs (measured) | **3.00 µs** (150 / 157) | **120× (1 month), 263× (1 year)** |
| `trend` | 512 µs | n/a | **3.49 µs** (175 / 188) | **147×** |
| `meanrev` | 491 µs | n/a | **37.3 µs** (1,864 / 2,285) | **13×** |

Mean cycles include the cheap warm-up bars (21 cycles each).
| `bq_native_rsi` | 300 µs | n/a | not expressible | n/a |

Mean reversion is the FPGA's worst case. The ISA has no square-root or multiply-accumulate
instruction, so the compiler unrolls the variance over the 20-bar window and computes the square
root with an integer Newton loop.

### 3.3 End-to-end time per bar, including data transfer (current 115200-baud link)

| Strategy | Send ticks (20 B) | Receive replies (mean) | Compute | **TradeCPU total** | BabyQuant (1 month) | Result |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| `sma` | 1,736 µs | 10.0 B → 867 µs | 3.0 µs | **2,607 µs** | 361 µs | FPGA 7.2× slower |
| `trend` | 1,736 µs | 8.5 B → 738 µs | 3.5 µs | **2,477 µs** | 512 µs | FPGA 4.8× slower |
| `meanrev` | 1,736 µs | 5.7 B → 491 µs | 37.3 µs | **2,264 µs** | 491 µs | FPGA 4.6× slower |

The UART accounts for 99.9% (`sma`), 99.9% (`trend`) and 98.4% (`meanrev`) of the FPGA's time.
These figures don't include USB-serial turnaround latency, which will add to the real hardware
number (see §5).

### 3.4 Scaling with backtest length

BabyQuant's cost per bar rises with dataset size, because every lookup scans the whole DataFrame.
TradeCPU's cost per bar is constant, because its price history is a fixed 30-entry on-chip buffer.

| Bars | BabyQuant `sma` | BabyQuant `trend` | BabyQuant `meanrev` | TradeCPU (any size) |
| ---: | ---: | ---: | ---: | --- |
| ≈365 | 444 µs\* | 480 µs | 498 µs | constant (§3.2) |
| ≈1,535 | 361 µs | 512 µs | 491 µs | |
| ≈3,875 | 375 µs | 527 µs | 483 µs | |
| ≈7,775 | 392 µs | 556 µs | 503 µs | |
| ≈15,575 | 436 µs | 607 µs | 541 µs | |
| 98,251 (1 year) | **789 µs** | — | — | |

\*The smallest size is dominated by fixed overhead.

### 3.5 Whole backtests: one stock

Totals are per-bar cost × bar count. The **1-year** BabyQuant figure is measured. The **5-year**
BabyQuant figures are extrapolated with a fit of t = aN + bN². For `sma` the fit includes the
measured 1-year point; for `trend` and `meanrev` it uses sizes up to 15.6k bars only, so treat
those as rough.

| Setup | `sma`, 1 year (98,280 bars) | `sma`, 5 years (491,400 bars) | `trend`, 5 years | `meanrev`, 5 years |
| --- | ---: | ---: | ---: | ---: |
| BabyQuant, as-is | **77.5 s** (measured) | ≈ 1,217 s (20 min) | ≈ 1,848 s (31 min) | ≈ 1,392 s (23 min) |
| **TradeCPU, UART 115200 (today)** | **256 s** | **1,281 s (21 min)** | **1,217 s (20 min)** | **1,113 s (19 min)** |
| TradeCPU, UART 921,600 (projected) | 32 s | 161 s | 154 s | 155 s |
| TradeCPU, UART ≈3 Mbaud (projected) | 10 s | 51 s | 48 s | 60 s |
| TradeCPU, compute only (lower bound) | 0.29 s | 1.5 s | 1.7 s | 18.3 s |
| Reference: plain Python streaming loop | 0.028 s | 0.14 s | 0.16 s | 0.21 s |
| Reference: C `-O2` | 0.0002 s | 0.001 s | 0.001 s | 0.003 s |

### 3.6 Where each system spends its time

- **BabyQuant, about 360–790 µs per bar:**
  - about 10% goes to `exec()` recompiling the strategy source (9.3%, 11.6% and 9.2% for the
    three strategies);
  - most of the rest goes to pandas: up to 7 boolean-mask row lookups per bar
    (`get_holdings_value`, `get_indicator`, `get_price`), each scanning every row and allocating a
    filtered DataFrame. That's why per-bar cost grows with the length of the data.
- **TradeCPU today, about 2.3–2.6 ms per bar:** 98.4–99.9% is UART transfer. The CPU core is idle
  for nearly the whole bar.

## 4. Analysis

**Execution vs compile time.** The two projects split the work differently:

| | Up-front (once per strategy) | Repeated on every bar |
| --- | --- | --- |
| **BabyQuant** | ≈ 0; indicator precompute takes ms | Recompile (34–59 µs) plus interpreted evaluation with pandas lookups (300–790 µs) |
| **TradeCPU** | Compile (< 1 ms) plus program load (19–106 ms); bitstream build (minutes) only once per hardware change | 21–2,285 cycles, i.e. 0.4–46 µs, plus UART (≈ 2.2–2.6 ms today) |

TradeCPU pays a small fixed cost once, then runs a tight, fixed-cost loop. BabyQuant pays nothing
up front, but pays compile and interpretation costs again on every bar. For any backtest longer
than a few hundred bars, BabyQuant spends more total time compiling (recompiling, really) than
TradeCPU does.

**Is the FPGA faster?**

- **Strategy execution:** yes, by 13–263×. This is the claim to lead with.
- **Whole backtest today:** no, not yet. The 115200-baud link makes each bar about 2.5 ms, which
  is 4.6–7.2× slower than BabyQuant for 1-month backtests and 3.3× slower at 1 year (256 s vs
  77.5 s). At 5 years the two are roughly level (1,113–1,281 s vs an extrapolated 1,217–1,848 s),
  because BabyQuant slows down as the data grows while TradeCPU doesn't.
- **With a faster link:** raising the UART to 921,600 baud is projected to bring the FPGA to about
  313–328 µs per bar. That's faster than BabyQuant for all three shared strategies at every
  backtest length tested (BabyQuant was never below 361 µs), and about 8–12× faster over 5 years. On the RTL side this is the `BAUD` parameter
  (54 clocks per bit, 0.47% timing error). It depends on the board's USB-serial bridge supporting
  that rate, which we haven't verified. 1,000,000 baud divides 50 MHz exactly (50 clocks per bit)
  and gives about the same result.

**Against an optimized CPU implementation, the FPGA doesn't win.** The core runs at 50 MHz, isn't
pipelined, and takes 4 cycles per instruction (about 12.5 million instructions per second). A
plain-Python streaming loop evaluates `sma` in 0.28 µs, 10.5× faster than the FPGA core, and C
takes 2.1 ns, about 1,400× faster. The FPGA's measured advantage over BabyQuant comes from
BabyQuant's architecture: interpreted `exec()`, pandas lookups that scan the whole DataFrame, and
per-bar allocations. General-purpose CPUs aren't inherently slow at this.

**Where an FPGA does have a real advantage:**

- **Deterministic latency.** A bar's cycle count depends only on which branches the program takes.
  After warm-up, `sma` takes exactly 143 or 157 cycles; `meanrev` takes 874–2,285, depending on
  how many square-root iterations it needs. There is no garbage collector, operating system
  scheduling or interpreter jitter. BabyQuant's per-bar cost for the same strategy changes with
  dataset size (361 → 789 µs for `sma`).
- **Area.** The whole CPU uses about 4% of the chip's logic cells (LUTs), per `hardware/README.md`.
  That leaves room for many cores evaluating different strategies or stocks in parallel. That
  design isn't built, but this is the natural scaling path.
- **Tick-to-decision time.** Once the last price of a bar arrives, the decision is ready 3 µs
  later for `sma`. BabyQuant needs 300–790 µs.

## 5. Caveats

- **Simulated, not yet measured on hardware.** TradeCPU execution times come from cycle counts,
  not board measurements. The cycle model is verified against the RTL state machine and
  testbenches, but real UART throughput also includes USB-serial bridge latency. Common bridges
  batch small reads (FTDI's default latency timer is 16 ms, adjustable to 1 ms), and every bar
  waits for a small reply, so measured hardware time per bar will probably be **higher** than
  2.3–2.6 ms. Measure it with
  `python -m tradecpu hwtest <strategy>.json --port COMx --patterns walk --rounds 1000`, which now
  prints load time and ms/bar.
- **BabyQuant's data download isn't included.** Its yfinance download (network) was excluded, as
  was the time its indicator library takes. yfinance only serves 5-minute bars for the last 60
  days, so BabyQuant can't actually backtest 5 years of minute data. Our 5-year BabyQuant figures
  use its engine with our data.
- **Extrapolation.** The 5-year BabyQuant figures are extrapolated from measured points up to 1
  year (`sma`) or 15.6k bars (`trend`, `meanrev`).
- **Faster-link figures are projections.** 921,600 and 3 Mbaud assume the board's USB-serial
  bridge supports those rates. 3 Mbaud divides 50 MHz with about a 2% timing error, which is
  marginal.
- **The compute-only lower bound assumes prices are already on the board.** Five years of one
  stock is about 960 KB of int16 prices, but the chip's block RAM is 337.5 KB, so this would need
  the board's external memory. It's a bound, not something we've built.
- **Order logic differs.** BabyQuant's cash and holdings checks mean the two systems place
  different numbers of trades. Timing is compared per bar, and both evaluate the full strategy on
  every bar.

## 6. Recommendations for the presentation

**Claims the data supports:**

- "Our FPGA evaluates a strategy on each new bar **120–263× faster** than BabyQuant's on-device
  engine: **3 µs vs 361–789 µs** for an SMA crossover."
- "Compiling a block strategy for the FPGA takes **under 1 ms**, and loading it takes 19–106 ms.
  BabyQuant recompiles its strategy **on every bar**, which adds 3.3 s per year of data."
- "The FPGA's cost per bar is **constant and deterministic**. BabyQuant's grows with dataset size
  (361 → 789 µs per bar from 1 month to 1 year)."

**Claims to avoid:**

- "The FPGA backtests faster than a laptop." This is false against any optimized CPU code, and
  false against BabyQuant end to end at the current baud rate for backtests up to a year.

**Improvements that would make the end-to-end number competitive, in order of payoff:**

1. **Raise the UART baud rate** to 921,600 or 1 Mbaud: about 7–8× faster end to end, and projected
   to beat BabyQuant for all three shared strategies at every length tested.
2. **Send fewer bytes per bar:** only tick the buffers a strategy uses (the protocol currently
   requires all 5), or batch several bars per frame. Each bar currently spends 1,736 µs just
   sending prices.
3. **Keep price history on the board** in the external memory, and stream from there, which
   removes the host link from the loop.
4. **Replicate the core** to run many strategies or symbols at once. It uses about 4% of the LUTs.

## 7. Reproduce

```bash
git clone --depth 1 https://github.com/jsaluja09ufl/BabyQuant /tmp/BabyQuant
cd software/benchmarks
python3 bench_vs_babyquant.py --babyquant /tmp/BabyQuant          # about 5 min on an M3
python3 bench_vs_babyquant.py --babyquant /tmp/BabyQuant --quick  # about 40 s smoke run
```

Requirements: Python 3.10+ with pandas and numpy, plus `clang` for the C baseline. The script
writes `results.json`, which every number in this report comes from.
