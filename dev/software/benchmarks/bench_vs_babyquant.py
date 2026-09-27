"""Benchmark: BabyQuant (block strategies executed in Python on the host) vs TradeCPU (block
strategies compiled to the FPGA ISA).

    python3 bench_vs_babyquant.py --babyquant /path/to/BabyQuant [--quick]

BabyQuant's own Backtest/Stock classes are imported and run unmodified. Only the network data
source (yfinance) is replaced with the same synthetic minute bars TradeCPU receives, and the
sentiment modules (never called by these strategies) are stubbed so no API keys are needed.

TradeCPU execution time comes from the golden-model simulator, whose per-instruction cycle
counts match hardware/rtl/control_unit.v (4 cycles per 1-word op, 5 per 2-word op, 20 for DIV,
N+3 for GETSUMPRICEBEFORE), divided by the 50 MHz core clock. UART time is computed from the
bytes the protocol moves at 115200 baud 8N1 (10 bits per byte).
"""

from __future__ import annotations

import argparse
import contextlib
import io
import json
import os
import platform
import statistics
import subprocess
import sys
import tempfile
import time
import types
from collections import deque
from math import sqrt
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(REPO / "software" / "compiler"))

from tradecpu import compile_strategy  # noqa: E402
from tradecpu.isa import load_program_message  # noqa: E402
from tradecpu.simulator import BalanceMsg, Decision, run_rounds  # noqa: E402

CORE_HZ = 50_000_000
BAUD = 115_200
BITS_PER_BYTE = 10  # 8N1
TICK_BYTES = 4
MSG_BYTES = 5
NUM_BUFFERS = 5
BARS_PER_DAY = 390
BARS_1Y = 252 * BARS_PER_DAY
BARS_5Y = 5 * BARS_1Y
SYMBOL = "AAPL"
EXAMPLES = REPO / "software" / "frontend" / "dev-sketchout" / "examples"

STRATEGIES = {
    "sma": "sma_crossover.strategy.json",
    "trend": "trend_confirmation.strategy.json",
    "meanrev": "mean_reversion.strategy.json",
}


def uart_seconds(nbytes: int) -> float:
    return nbytes * BITS_PER_BYTE / BAUD


# ---------------------------------------------------------------- shared data

def make_bars(n: int, seed: int = 7) -> tuple[pd.DatetimeIndex, np.ndarray, np.ndarray]:
    """n one-minute bars during market hours: (index, dollars, cents). Prices stay in int16 cents."""
    rng = np.random.default_rng(seed)
    r = rng.normal(0, 0.0008, n)
    dollars = np.clip(150 * np.exp(np.cumsum(r)), 60, 320).round(2)
    days = pd.bdate_range("2021-01-04", periods=n // BARS_PER_DAY + 2)
    stamps = [d + pd.Timedelta(hours=9, minutes=30 + m) for d in days for m in range(BARS_PER_DAY)][:n]
    idx = pd.DatetimeIndex(stamps).tz_localize("America/New_York")
    return idx, dollars, (dollars * 100).round().astype(np.int32)


# ---------------------------------------------------------------- BabyQuant

def load_babyquant(root: Path):
    """Import BabyQuant's backend with network-only dependencies stubbed."""
    def rsi(close: pd.Series, length: int = 14) -> pd.Series:
        d = close.diff()
        up = d.clip(lower=0).ewm(alpha=1 / length, adjust=False).mean()
        down = (-d.clip(upper=0)).ewm(alpha=1 / length, adjust=False).mean()
        return 100 - 100 / (1 + up / down)

    stubs = {
        "yfinance": types.ModuleType("yfinance"),
        "pandas_ta": types.ModuleType("pandas_ta"),
        "sentimentAnalysis": types.ModuleType("sentimentAnalysis"),
        "news_api": types.ModuleType("news_api"),
    }
    stubs["pandas_ta"].rsi = rsi
    sys.modules.update(stubs)
    sys.path.insert(0, str(root / "src" / "backend"))
    import backtest as bq_backtest  # type: ignore
    import stock as bq_stock  # type: ignore
    return bq_backtest, bq_stock


def q(ind: str) -> str:
    return f"self.get_indicator(symbol='{SYMBOL}', indicator_name='{ind}')"


PRICE = f"self.get_price(symbol='{SYMBOL}')"
BUY = f"self.buy_stock(symbol='{SYMBOL}', quantity=10)"
SELL = f"self.sell_stock(symbol='{SYMBOL}', quantity=10)"

# Same decision logic as the TradeCPU templates, written against the engine API that
# BabyQuant's generated Python calls (python.ts emits self.get_indicator / self.buy_stock ...).
BQ_ALGOS = {
    "sma": f"if ({q('FAST')} > {q('SLOW')}):\n    {BUY}\nelse:\n    {SELL}\n",
    "trend": (
        f"if ({q('FAST')} > {q('SLOW')}):\n    if ({PRICE} > {q('FAST')}):\n        {BUY}\n"
        f"elif ({PRICE} < {q('SLOW')}):\n    {SELL}\n"
    ),
    "meanrev": f"if ({PRICE} <= {q('LOWER')}):\n    {BUY}\nelif ({PRICE} >= {q('UPPER')}):\n    {SELL}\n",
    # BabyQuant's own sample strategy (testing/backtest_test.py), built from its native blocks.
    "bq_native_rsi": (
        f"if (self.get_time() > 7 and self.get_day() == \"Monday\"):\n"
        f"    if ({q('RSI')} < 30):\n        {BUY}\n    elif ({q('RSI')} > 70):\n        {SELL}\n"
    ),
}


def bq_indicators(name: str, df: pd.DataFrame, bq_stock) -> None:
    """Precompute indicator columns the way BabyQuant does (pandas, before the bar loop)."""
    c = df["Close"]
    if name == "sma":
        df["FAST"], df["SLOW"] = c.rolling(10).mean(), c.rolling(30).mean()
    elif name == "trend":
        df["FAST"], df["SLOW"] = c.rolling(12).mean(), c.rolling(26).mean()
    elif name == "meanrev":
        m, s = c.rolling(20).mean(), c.rolling(20).std(ddof=0)
        df["UPPER"], df["LOWER"] = m + 2 * s, m - 2 * s
    if name == "bq_native_rsi":
        st = bq_stock.Stock.__new__(bq_stock.Stock)
        st.data, st.indicators = df, ["RSI"]
        st.calc_indicators(["RSI"])  # BabyQuant's own code path (calls ta.rsi, dropna)
    else:
        df.dropna(inplace=True)


def run_babyquant(bq_backtest, bq_stock, name: str, idx, dollars, silence_print: bool) -> dict:
    t0 = time.perf_counter()
    df = pd.DataFrame({"Close": dollars}, index=idx)
    bq_indicators(name, df, bq_stock)
    st = bq_stock.Stock.__new__(bq_stock.Stock)
    st.data, st.indicators = df, []
    setup = time.perf_counter() - t0

    algo = BQ_ALGOS[name]
    bt = bq_backtest.Backtest.__new__(bq_backtest.Backtest)
    # Backtest.__init__ minus get_data() (the yfinance download).
    bt.algorithm, bt.frequency = algo, "1m"
    bt.data = {SYMBOL: st}
    bt.parsed_symbols = bt.parse_symbols()
    bt.parsed_indicators = bt.parse_indicators()
    bt.trades, bt.val_history = [], []
    bt.curr_amount = bt.start_amount = 100_000.0
    bt.curr_timestamp, bt.holdings = "", {}

    if silence_print:
        bq_backtest.print = lambda *a, **k: None
    try:
        with open(os.devnull, "w") as devnull, contextlib.redirect_stdout(devnull):
            t0 = time.perf_counter()
            bt.backtest()
            run = time.perf_counter() - t0
    finally:
        if silence_print:
            del bq_backtest.print
    return {"bars": len(df), "setup_s": setup, "run_s": run, "per_bar_us": run / len(df) * 1e6,
            "trades": len(bt.trades)}


def exec_compile_cost_us(name: str) -> float:
    """BabyQuant passes the algorithm *string* to exec() every bar, so Python re-compiles it per bar."""
    src, reps = BQ_ALGOS[name], 20000
    t0 = time.perf_counter()
    for _ in range(reps):
        compile(src, "<string>", "exec")
    return (time.perf_counter() - t0) / reps * 1e6


# ---------------------------------------------------------------- TradeCPU

def tradecpu_compile(name: str, reps: int = 30) -> dict:
    doc = json.loads((EXAMPLES / STRATEGIES[name]).read_text())
    times = []
    for _ in range(reps):
        t0 = time.perf_counter()
        res = compile_strategy(doc)
        times.append(time.perf_counter() - t0)
    frame = load_program_message(res.words)
    return {
        "words": len(res.words),
        "compile_ms_median": statistics.median(times) * 1e3,
        "compile_ms_min": min(times) * 1e3,
        "load_bytes": len(frame),
        "load_uart_ms": uart_seconds(len(frame)) * 1e3,
        "warmup_ticks": res.manifest["warmupTicks"],
        "result": res,
    }


def tradecpu_execute(res, cents: np.ndarray) -> dict:
    rounds = [[int(c), 100, 100, 100, 100] for c in cents]
    t0 = time.perf_counter()
    _, per_round, cycles = run_rounds(res.words, rounds)
    sim_wall = time.perf_counter() - t0
    reply_bytes = [MSG_BYTES * len(m) for m in per_round]
    decisions = [[x for x in m if isinstance(x, Decision)] for m in per_round]
    tx = NUM_BUFFERS * TICK_BYTES
    round_s = [uart_seconds(tx) + c / CORE_HZ + uart_seconds(rb) for c, rb in zip(cycles, reply_bytes)]
    n = len(rounds)
    return {
        "rounds": n,
        "cycles_min": min(cycles), "cycles_mean": statistics.fmean(cycles), "cycles_max": max(cycles),
        "core_per_bar_us": statistics.fmean(cycles) / CORE_HZ * 1e6,
        "core_total_s": sum(cycles) / CORE_HZ,
        "uart_per_bar_us": statistics.fmean(round_s) * 1e6 - statistics.fmean(cycles) / CORE_HZ * 1e6,
        "e2e_per_bar_us": statistics.fmean(round_s) * 1e6,
        "e2e_total_s": sum(round_s),
        "tx_bytes_per_bar": tx,
        "reply_bytes_mean": statistics.fmean(reply_bytes),
        "trades": sum(len(d) for d in decisions),
        "all_balances_acked": all(m and isinstance(m[-1], BalanceMsg) for m in per_round),
        "sim_wall_s": sim_wall,
        "decisions": decisions,
    }


# ---------------------------------------------------------------- optimized CPU baselines

def py_streaming(name: str, cents: np.ndarray) -> tuple[float, int]:
    p = cents.tolist()
    trades = 0
    t0 = time.perf_counter()
    if name in ("sma", "trend"):
        nf, ns = (10, 30) if name == "sma" else (12, 26)
        qf, qs = deque(), deque()
        sf = ss = 0
        for i, x in enumerate(p):
            qf.append(x); sf += x
            qs.append(x); ss += x
            if len(qf) > nf: sf -= qf.popleft()
            if len(qs) > ns: ss -= qs.popleft()
            if i < ns - 1:
                continue
            fast, slow = sf // nf, ss // ns
            if name == "sma":
                trades += 1
            elif fast > slow:
                trades += x > fast
            else:
                trades += x < slow
    else:
        qw = deque()
        s = s2 = 0.0
        for i, x in enumerate(p):
            qw.append(x); s += x; s2 += x * x
            if len(qw) > 20:
                y = qw.popleft(); s -= y; s2 -= y * y
            if i < 19:
                continue
            m = s / 20
            sd = sqrt(max(s2 / 20 - m * m, 0))
            trades += (x <= m - 2 * sd) or (x >= m + 2 * sd)
    return (time.perf_counter() - t0) / len(p) * 1e6, trades


def c_baseline(cents: np.ndarray, workdir: Path) -> dict:
    exe = workdir / "baseline"
    t0 = time.perf_counter()
    subprocess.run(["clang", "-O2", "-o", str(exe), str(HERE / "baseline.c"), "-lm"], check=True)
    compile_s = time.perf_counter() - t0
    data = workdir / "prices.bin"
    data.write_bytes(cents.astype("<i4").tobytes())
    out = {"compile_ms": compile_s * 1e3}
    for name in STRATEGIES:
        reps = max(1, int(3e8 // len(cents) // 10))
        ns, trades, _ = subprocess.run([str(exe), str(data), name, str(reps)], check=True,
                                       capture_output=True, text=True).stdout.split()
        out[name] = {"per_bar_ns": float(ns), "trades": int(trades), "reps": reps}
    return out


# ---------------------------------------------------------------- main

def fit_quadratic(ns: list[int], ts: list[float]) -> tuple[float, float]:
    """Least-squares t = a*N + b*N^2 (no intercept); falls back to t = a*N if the fit bends down."""
    A = np.array([[n, n * n] for n in ns], dtype=float)
    (a, b), *_ = np.linalg.lstsq(A, np.array(ts), rcond=None)
    if b < 0:
        a, b = float(np.dot(ns, ts) / np.dot(ns, ns)), 0.0
    return float(a), float(b)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--babyquant", required=True, type=Path, help="path to a BabyQuant checkout")
    ap.add_argument("--quick", action="store_true", help="smaller sizes for a fast smoke run")
    ap.add_argument("--out", type=Path, default=HERE / "results.json")
    args = ap.parse_args()

    bq_sizes = [390, 1560, 3900] if args.quick else [390, 1560, 3900, 7800, 15600]
    exec_n = 3900 if args.quick else 19500
    bq_backtest, bq_stock = load_babyquant(args.babyquant)

    results: dict = {
        "machine": {
            "platform": platform.platform(), "processor": platform.processor(),
            "python": platform.python_version(), "pandas": pd.__version__, "numpy": np.__version__,
        },
        "constants": {"core_hz": CORE_HZ, "baud": BAUD, "bits_per_byte": BITS_PER_BYTE},
        "tradecpu": {}, "babyquant": {}, "baselines": {},
    }

    # TradeCPU: compile + execute on exec_n bars
    idx, dollars, cents = make_bars(max(exec_n, max(bq_sizes)))
    for name in STRATEGIES:
        comp = tradecpu_compile(name)
        ex = tradecpu_execute(comp.pop("result"), cents[:exec_n])
        decisions = ex.pop("decisions")
        if name == "sma":
            c = pd.Series(cents[:exec_n].astype(np.int64))
            fast, slow = c.rolling(10).sum() // 10, c.rolling(30).sum() // 30
            want = ["buy" if f > s else "sell" for f, s in zip(fast[29:], slow[29:])]
            got = [d[0].action if d else None for d in decisions[29:]]
            ex["signal_agreement_vs_reference"] = sum(g == w for g, w in zip(got, want)) / len(want)
        results["tradecpu"][name] = {**comp, **ex}
        print(f"TradeCPU {name:8s} {comp['words']:3d} words  compile {comp['compile_ms_median']:.2f} ms  "
              f"core {ex['core_per_bar_us']:.2f} us/bar  e2e {ex['e2e_per_bar_us']:.1f} us/bar", flush=True)

    # BabyQuant: per strategy, per size
    for name in list(STRATEGIES) + ["bq_native_rsi"]:
        rows = []
        for n in bq_sizes:
            reps = 3
            runs = [run_babyquant(bq_backtest, bq_stock, name, idx[:n], dollars[:n], False) for _ in range(reps)]
            best = min(runs, key=lambda r: r["run_s"])
            quiet = run_babyquant(bq_backtest, bq_stock, name, idx[:n], dollars[:n], True)
            row = {"n_input": n, **best, "reps": reps, "run_s_no_print": quiet["run_s"],
                   "per_bar_us_no_print": quiet["per_bar_us"]}
            rows.append(row)
            print(f"BabyQuant {name:13s} N={n:6d} bars={row['bars']:6d} run {row['run_s']:8.3f} s "
                  f"({row['per_bar_us']:9.1f} us/bar; no-print {row['per_bar_us_no_print']:9.1f})", flush=True)
        long_run = None
        if name == "sma" and not args.quick:
            # Measured (not extrapolated) point at one year of minute bars.
            lidx, ldollars, _ = make_bars(BARS_1Y)
            long_run = run_babyquant(bq_backtest, bq_stock, name, lidx, ldollars, False)
            print(f"BabyQuant {name:13s} N={BARS_1Y:6d} bars={long_run['bars']:6d} run {long_run['run_s']:8.3f} s "
                  f"({long_run['per_bar_us']:9.1f} us/bar)  [1 year, measured]", flush=True)
        pts = [(r["bars"], r["run_s"]) for r in rows] + ([(long_run["bars"], long_run["run_s"])] if long_run else [])
        a, b = fit_quadratic([p[0] for p in pts], [p[1] for p in pts])
        results["babyquant"][name] = {
            "sizes": rows,
            "one_year_measured": long_run,
            "exec_compile_us_per_bar": exec_compile_cost_us(name),
            "fit": {"a_s_per_bar": a, "b_s_per_bar2": b},
            "extrapolated_s": {"1y_1m": a * BARS_1Y + b * BARS_1Y**2, "5y_1m": a * BARS_5Y + b * BARS_5Y**2},
        }

    # Optimized CPU baselines on exec_n bars
    with tempfile.TemporaryDirectory() as tmp:
        results["baselines"]["c_O2"] = c_baseline(cents[:exec_n], Path(tmp))
    for name in STRATEGIES:
        us, trades = py_streaming(name, cents[:exec_n])
        results["baselines"].setdefault("python_streaming", {})[name] = {"per_bar_us": us, "trades": trades}
    print(json.dumps(results["baselines"], indent=1))

    # Projections from the measured cycles/bytes: link speed what-ifs and 5-year totals per stock.
    proj = {}
    for name in STRATEGIES:
        t = results["tradecpu"][name]
        bq = results["babyquant"][name]
        bytes_per_bar = t["tx_bytes_per_bar"] + t["reply_bytes_mean"]
        per_bar = {f"uart_{b}": (bytes_per_bar * BITS_PER_BYTE / b) * 1e6 + t["core_per_bar_us"]
                   for b in (115_200, 921_600, 3_000_000)}
        per_bar["on_chip_data"] = t["core_per_bar_us"]
        five_y = {f"tradecpu_{k}": v * 1e-6 * BARS_5Y for k, v in per_bar.items()}
        five_y["babyquant_extrapolated"] = bq["extrapolated_s"]["5y_1m"]
        five_y["babyquant_linear_floor"] = bq["sizes"][0]["per_bar_us"] * 1e-6 * BARS_5Y
        five_y["python_streaming"] = results["baselines"]["python_streaming"][name]["per_bar_us"] * 1e-6 * BARS_5Y
        five_y["c_O2"] = results["baselines"]["c_O2"][name]["per_bar_ns"] * 1e-9 * BARS_5Y
        proj[name] = {"per_bar_us": per_bar, "five_year_one_stock_s": five_y}
    results["projections"] = proj
    results["bars_5y"] = BARS_5Y
    print(json.dumps(proj, indent=1))

    args.out.write_text(json.dumps(results, indent=2) + "\n")
    print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
