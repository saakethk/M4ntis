"""Command line: python -m tradecpu {compile,asm,disasm,simulate} ..."""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

from .asm import Assembled, AsmError, assemble, disassemble, format_asm, parse_asm
from .compiler import CompileError, CompileOptions, Diagnostic, compile_strategy
from .isa import NUM_BUFFERS, load_program_message
from .simulator import BalanceMsg, Decision, run_rounds


def _price_exps(pairs: list[str]) -> dict[int, int]:
    exps = {b: 2 for b in range(NUM_BUFFERS)}
    for pair in pairs:
        buf, _, exp = pair.partition("=")
        exps[int(buf)] = int(exp)
    return exps


def _read_json(path: str) -> dict:
    return json.load(sys.stdin if path == "-" else open(path))


def cmd_compile(args: argparse.Namespace) -> int:
    try:
        doc = _read_json(args.strategy)
        result = compile_strategy(doc, CompileOptions(price_exponents=_price_exps(args.price_exp)))
    except (json.JSONDecodeError, CompileError) as err:
        e = err if isinstance(err, CompileError) else CompileError(
            [Diagnostic("error", f"Strategy is not valid JSON: {err}")]
        )
        if args.json:
            print(json.dumps({"ok": False, "diagnostics": [d.to_json() for d in e.diagnostics]}))
        else:
            print(e, file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps({
            "ok": True,
            "asm": format_asm(result.items, addresses=True),
            "hex": result.assembled.hex_lines(),
            "manifest": result.manifest,
            "diagnostics": [w.to_json() for w in result.warnings],
        }))
        return 0

    if args.out:
        out = Path(args.out)
        out.mkdir(parents=True, exist_ok=True)
        stem = Path(args.strategy).name.split(".")[0] if args.strategy != "-" else "strategy"
        (out / f"{stem}.asm").write_text(format_asm(result.items, addresses=True))
        (out / f"{stem}.hex").write_text(result.assembled.hex_lines())
        (out / f"{stem}_program.py").write_text(result.assembled.python_array())
        (out / f"{stem}.load_program.bin").write_bytes(load_program_message(result.words))
        (out / f"{stem}.manifest.json").write_text(json.dumps(result.manifest, indent=2) + "\n")
        print(f"{stem}: {len(result.words)} words -> {out}/", file=sys.stderr)
    else:
        sys.stdout.write(_render(result.assembled, args.format))
    for w in result.warnings:
        print(w, file=sys.stderr)
    return 0


def _render(prog: Assembled, fmt: str) -> str:
    if fmt == "python":
        return prog.python_array()
    if fmt == "hex":
        return prog.hex_lines()
    return prog.listing()


def cmd_asm(args: argparse.Namespace) -> int:
    try:
        prog = assemble(parse_asm(Path(args.file).read_text()))
    except AsmError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    sys.stdout.write(_render(prog, args.format))
    return 0


def cmd_disasm(args: argparse.Namespace) -> int:
    words = [int(line, 16) for line in Path(args.file).read_text().split() if line]
    sys.stdout.write(format_asm(disassemble(words), addresses=True))
    return 0


def cmd_simulate(args: argparse.Namespace) -> int:
    """Compile a strategy and replay prices through the golden model.

    CSV: one row per tick round, columns buf0..buf4 as scaled integers (missing -> 0).
    """
    doc = _read_json(args.strategy)
    try:
        result = compile_strategy(doc, CompileOptions(price_exponents=_price_exps(args.price_exp)))
    except CompileError as e:
        print(e, file=sys.stderr)
        return 1
    with open(args.prices) as f:
        rounds = [[int(row.get(f"buf{b}") or 0) for b in range(NUM_BUFFERS)] for row in csv.DictReader(f)]
    at_load, per_round, cycles = run_rounds(result.words, rounds)
    warm = result.manifest["warmupTicks"]
    print(f"load: {at_load}")
    for i, (msgs, cyc) in enumerate(zip(per_round, cycles)):
        tag = "warm-up" if i < warm else "tick"
        decisions = [f"{m.action.upper()} {m.quantity} x BUF{m.buf}" for m in msgs if isinstance(m, Decision)]
        bal = [m.value for m in msgs if isinstance(m, BalanceMsg)]
        print(f"{i:5d} {tag:7s} prices={rounds[i]} cycles={cyc:5d} {', '.join(decisions) or '-':30s} balance={bal[-1] if bal else '?'}")
    return 0


def _load_program(path: str, price_exps: dict[int, int]) -> tuple[list[int], int]:
    """(words, warm-up ticks) from a strategy JSON or a hand-written .asm file."""
    if path.endswith(".asm"):
        return assemble(parse_asm(Path(path).read_text())).words, 0
    result = compile_strategy(_read_json(path), CompileOptions(price_exponents=price_exps))
    return result.words, result.manifest["warmupTicks"]


def cmd_hwtest(args: argparse.Namespace) -> int:
    """Run strategies on the board (or the simulator with --dry-run) against dummy price data."""
    from . import hwtest

    price_exps = _price_exps(args.price_exp)
    patterns = list(hwtest.PATTERNS) if args.patterns == "all" else args.patterns.split(",")
    port = hwtest.FakeBoard() if args.dry_run else hwtest.open_serial(args.port, args.baud)
    target = "simulator (dry run)" if args.dry_run else f"{args.port} @ {args.baud}"
    print(f"target: {target}\n")

    total_failures = 0
    summary: list[str] = []
    try:
        for path in args.strategies:
            try:
                words, warmup = _load_program(path, price_exps)
            except (CompileError, AsmError) as e:
                print(f"{path}: does not compile\n{e}\n")
                total_failures += 1
                continue
            for pattern in patterns:
                if Path(pattern).suffix == ".csv":
                    rounds = hwtest.read_csv_rounds(pattern)
                else:
                    rounds = hwtest.make_rounds(pattern, warmup + args.rounds, price_exps, args.seed)
                rep = hwtest.run_pattern(port, words, rounds, pattern, warmup, args.tick_delay, args.verbose)
                total_failures += rep.failures
                status = "PASS" if rep.failures == 0 else f"FAIL ({rep.failures})"
                bal = f"${rep.final_balance / 100:,.2f}" if rep.final_balance is not None else "?"
                row = (f"{Path(path).name:32s} {Path(pattern).name:10s} {len(words):4d}w  warm-up {warmup:2d}  "
                       f"buy {rep.buys:3d} sell {rep.sells:3d} hold {rep.holds:3d}  end {bal:>14s}  {status}")
                summary.append(row)
                if rep.lines:
                    print(f"{Path(path).name} / {pattern}")
                    print("\n".join(rep.lines) + "\n")
                if rep.failures == 0 and rep.buys + rep.sells == 0:
                    summary.append(f"{'':32s} note: never traded on '{pattern}', so trade paths were not exercised")
    finally:
        port.close()

    print("\n".join(summary))
    print("\n" + ("ALL CHECKS PASSED" if total_failures == 0 else f"{total_failures} CHECK(S) FAILED -- see above"))
    return 1 if total_failures else 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="tradecpu", description="TradeCPU strategy compiler and tools")
    sub = p.add_subparsers(dest="cmd", required=True)

    c = sub.add_parser("compile", help="strategy JSON -> assembly / machine code")
    c.add_argument("strategy", help="m4ntis.strategy/v1 JSON file, or - for stdin")
    c.add_argument("-o", "--out", help="write .asm, .hex, .load_program.bin and .manifest.json here")
    c.add_argument("--json", action="store_true", help="print one JSON object (asm, manifest, diagnostics)")
    c.add_argument("--price-exp", action="append", default=[], metavar="BUF=EXP",
                   help="price exponent for a buffer (default 2 = cents)")
    c.add_argument("--format", choices=("asm", "hex", "python"), default="asm",
                   help="stdout format: listing, one hex word per line, or a Python `instructions = [...]` list")
    c.set_defaults(fn=cmd_compile)

    a = sub.add_parser("asm", help="assembly text -> words")
    a.add_argument("file")
    a.add_argument("--format", choices=("hex", "python", "asm"), default="hex")
    a.set_defaults(fn=cmd_asm)

    d = sub.add_parser("disasm", help="hex words -> assembly text")
    d.add_argument("file")
    d.set_defaults(fn=cmd_disasm)

    s = sub.add_parser("simulate", help="compile and run against a CSV of tick prices")
    s.add_argument("strategy")
    s.add_argument("prices", help="CSV with columns buf0..buf4")
    s.add_argument("--price-exp", action="append", default=[], metavar="BUF=EXP")
    s.set_defaults(fn=cmd_simulate)

    h = sub.add_parser("hwtest", help="run strategies on the FPGA with dummy prices, checked against the simulator")
    h.add_argument("strategies", nargs="+", help="strategy JSON and/or .asm files")
    h.add_argument("--port", default="COM4", help="serial port (e.g. COM4, /dev/tty.usbserial-XXXX)")
    h.add_argument("--baud", type=int, default=115200)
    h.add_argument("--patterns", default="all",
                   help="comma list of sine,walk,ramp,steps,spikes,flat and/or CSV paths (buf0..buf4), or 'all'")
    h.add_argument("--rounds", type=int, default=60, help="rounds to run after warm-up per pattern")
    h.add_argument("--seed", type=int, default=0, help="seed for the random-walk pattern")
    h.add_argument("--tick-delay", type=float, default=0.01, help="seconds between TICK frames")
    h.add_argument("--price-exp", action="append", default=[], metavar="BUF=EXP")
    h.add_argument("--dry-run", action="store_true", help="use a simulated board instead of the serial port")
    h.add_argument("-v", "--verbose", action="store_true", help="print every round, not just mismatches")
    h.set_defaults(fn=cmd_hwtest)

    args = p.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
