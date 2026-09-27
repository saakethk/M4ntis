"""Backtests run on the TradeCPU FPGA, and the performance metrics derived from them.

A run:

1. compiles the strategy and reads which stock each hardware slot holds,
2. loads the most recent ``BACKTEST_TICKS`` bars (plus warm-up) of those stocks at the
   strategy's resolution from ``stock_minute_bars``, or a chosen calendar range,
3. picks each slot's price scale so its highest price fits the board's 16-bit tick
   field, and compiles again with those scales,
4. loads the program onto the FPGA and feeds it every tick
   (:mod:`mantis.services.fpga`), and
5. stores the board's own decisions as orders and its balance after every tick.

Nothing is simulated in software. If the board is not connected, the run fails with
503 and nothing is stored.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any
from zoneinfo import ZoneInfo

from psycopg.types.json import Jsonb

from backend.mantis import db
from backend.mantis.config import env
from backend.mantis.errors import Forbidden, InvalidInput, NotFound
from backend.mantis.services import compiler, market_data, strategies
from backend.mantis.services import fpga

DEFAULT_TICKS = 500
DEFAULT_MAX_TICKS = 20_000
TICK_MAX = 32767  # the board's price field is a signed 16-bit integer
SOURCE = "fpga"
NY = ZoneInfo("America/New_York")


def backtest_ticks() -> int:
    raw = env("BACKTEST_TICKS", str(DEFAULT_TICKS))
    if not raw.isdigit() or not 1 <= int(raw) <= 20_000:
        raise InvalidInput("BACKTEST_TICKS must be a whole number from 1 to 20000")
    return int(raw)


def backtest_max_ticks() -> int:
    raw = env("BACKTEST_MAX_TICKS", str(DEFAULT_MAX_TICKS))
    if not raw.isdigit() or not 1 <= int(raw) <= 20_000:
        raise InvalidInput("BACKTEST_MAX_TICKS must be a whole number from 1 to 20000")
    return int(raw)


def fpga_status() -> dict[str, Any]:
    return fpga.status()


def backtest_available_range(user_id: int, strategy_id: int) -> dict[str, Any]:
    """Symbols, resolution, and calendar days with complete minute-bar coverage."""
    _, manifest, _, symbols = _strategy_market_context(user_id, strategy_id)
    span = market_data.available_range(symbols)
    days = span["days"]
    start = span["start"]
    end = span["end"]
    return {
        "symbols": symbols,
        "resolution": manifest["resolution"],
        "start": start.isoformat() if start else None,
        "end": end.isoformat() if end else None,
        "days": [day.isoformat() for day in days],
    }


def run_backtest(
    user_id: int,
    requested_user_id: int,
    strategy_id: int,
    start: date | None = None,
    end: date | None = None,
) -> dict[str, Any]:
    """Run a strategy the user can view on the FPGA and store the result."""
    if requested_user_id != user_id:
        raise Forbidden("You can only run a backtest as yourself")
    board = fpga.status()
    if not board["connected"]:
        raise fpga.FpgaUnavailable(board["detail"])

    strategy, manifest, slots, symbols = _strategy_market_context(user_id, strategy_id)
    warmup = int(manifest["warmupTicks"])

    if (start is None) ^ (end is None):
        raise InvalidInput("Provide both start and end dates, or omit both to use the latest bars.")
    if start is not None and end is not None:
        if start > end:
            raise InvalidInput("Backtest start must be on or before end.")
        avail = market_data.available_range(symbols)
        _ensure_range_has_data(symbols, start, end, avail)
        bars = market_data.closes_between(symbols, manifest["resolution"], start, end, warmup)
        in_range = len(bars) - warmup
        if in_range > backtest_max_ticks():
            raise InvalidInput(
                f"This range needs {in_range} ticks after warm-up; the limit is {backtest_max_ticks()}. Narrow the dates."
            )
    else:
        bars = market_data.latest_closes(symbols, manifest["resolution"], warmup + backtest_ticks())

    if len(bars) <= warmup:
        raise InvalidInput(
            f"Not enough {manifest['resolution']} price history for {', '.join(symbols)}: "
            f"found {len(bars)} bars, the strategy needs more than {warmup} to warm up."
        )
    range_start, range_end = _bar_range_dates(bars, warmup)
    exponents = {slot["buf"]: _price_exponent(max(closes[i] for _, closes in bars), slot["symbol"]) for i, slot in enumerate(slots)}
    program = compiler.compile_document(strategy.document, exponents)["manifest"]
    rounds = [_round(closes, slots, exponents) for _, closes in bars]

    with fpga.board() as port:
        run = fpga.run_program(port, [int(word, 16) for word in program["words"]], rounds)

    orders, balances = _ledger(bars, slots, run, 10 ** program["balanceExponent"])
    backtest_id, version_id = _store(user_id, strategy, orders, balances, range_start, range_end)
    return {
        "id": backtest_id,
        "user_id": user_id,
        "strategy_id": strategy_id,
        "strategy_version_id": version_id,
        "source": SOURCE,
        "ticks": len(bars),
        "range_start": range_start.isoformat(),
        "range_end": range_end.isoformat(),
        "orders": [_iso(order) for order in orders],
        "balances": [_iso(point) for point in balances],
    }


def get_backtest(viewer_id: int, backtest_id: int) -> dict[str, Any]:
    """A stored run for its runner, or for anyone who can view the strategy."""
    with db.session() as conn:
        row = conn.execute(
            """
            SELECT b.id, b.user_id, b.created_at, b.strategy_version_id,
                   v.strategy_id, s.name, s.user_id, s.visibility, b.source,
                   b.range_start, b.range_end
            FROM backtests b
            JOIN strategy_versions v ON v.id = b.strategy_version_id
            JOIN strategies s ON s.id = v.strategy_id
            WHERE b.id = %s
            """,
            (backtest_id,),
        ).fetchone()
        runner_id = None if row is None else int(row[1])
        if row is None or (runner_id != viewer_id and not strategies.can_view(int(row[6]), str(row[7]), viewer_id)):
            raise NotFound("Backtest not found")
        order_rows = conn.execute(
            "SELECT ts, symbol, side, quantity, price FROM backtest_orders WHERE backtest_id = %s ORDER BY ts, id",
            (backtest_id,),
        ).fetchall()
        balance_rows = conn.execute(
            "SELECT ts, cash, equity FROM backtest_balances WHERE backtest_id = %s ORDER BY ts, id",
            (backtest_id,),
        ).fetchall()
    orders = [
        {"ts": r[0].isoformat(), "symbol": str(r[1]), "side": str(r[2]), "quantity": float(r[3]), "price": float(r[4])}
        for r in order_rows
    ]
    balances = [{"ts": r[0].isoformat(), "cash": float(r[1]), "equity": float(r[2])} for r in balance_rows]
    range_start = row[9]
    range_end = row[10]
    return {
        "id": int(row[0]),
        "user_id": runner_id,
        "strategy_id": int(row[4]),
        "strategy_name": str(row[5]),
        "strategy_version_id": int(row[3]),
        "created_at": row[2].isoformat(),
        "source": str(row[8]),
        "range_start": range_start.isoformat() if range_start is not None else None,
        "range_end": range_end.isoformat() if range_end is not None else None,
        "orders": orders,
        "balances": balances,
        "metrics": performance(orders, balances),
    }


def _strategy_market_context(user_id: int, strategy_id: int) -> tuple[strategies.StrategyRow, dict[str, Any], list[dict[str, Any]], list[str]]:
    with db.session() as conn:
        strategy = strategies.load_viewable(conn, user_id, strategy_id)
    manifest = compiler.compile_document(strategy.document)["manifest"]
    slots = [b for b in manifest["buffers"] if b["used"]]
    if not slots:
        raise InvalidInput("This strategy reads no stock prices, so there is nothing to backtest. Add a Get ticker block.")
    unnamed = [f"BUF{b['buf']}" for b in slots if not b["symbol"]]
    if unnamed:
        raise InvalidInput(f"Pick a stock for {', '.join(unnamed)} before running a backtest.")
    symbols = [str(b["symbol"]) for b in slots]
    return strategy, manifest, slots, symbols


def _ensure_range_has_data(symbols: list[str], start: date, end: date, avail: dict[str, date | list[date]]) -> None:
    days = set(avail["days"])
    span_start = avail["start"]
    span_end = avail["end"]
    if not days or span_start is None or span_end is None:
        raise InvalidInput(f"No price data for {', '.join(symbols)}. Add market data before running a backtest.")
    for day in (start, end):
        if day not in days:
            raise InvalidInput(
                f"No price data for {', '.join(symbols)} on {day.isoformat()}. "
                f"Pick dates between {span_start.isoformat()} and {span_end.isoformat()}."
            )


def _bar_range_dates(bars: list[tuple[datetime, list[float]]], warmup: int) -> tuple[date, date]:
    active = bars[warmup:]
    first = _bar_trading_day(active[0][0])
    last = _bar_trading_day(active[-1][0])
    return first, last


def _bar_trading_day(ts: datetime) -> date:
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=NY)
    return ts.astimezone(NY).date()


def _price_exponent(highest: float, symbol: str) -> int:
    """Cents when the price fits the 16-bit tick field, else dimes, else dollars."""
    for exponent in (2, 1, 0):
        if round(highest * 10**exponent) <= TICK_MAX:
            return exponent
    raise InvalidInput(f"{symbol} traded at ${highest:,.2f}, above the board's ${TICK_MAX:,} price limit.")


def _round(closes: list[float], slots: list[dict[str, Any]], exponents: dict[int, int]) -> list[int]:
    """One tick's prices for all five slots. Slots the program never reads get 0."""
    prices = [0] * fpga.NUM_BUFFERS
    for close, slot in zip(closes, slots):
        prices[slot["buf"]] = max(1, min(TICK_MAX, round(close * 10 ** exponents[slot["buf"]])))
    return prices


def _ledger(
    bars: list[tuple[datetime, list[float]]], slots: list[dict[str, Any]], run: fpga.BoardRun, balance_scale: int
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Orders from the board's decisions, and cash plus position value after every tick."""
    column = {slot["buf"]: i for i, slot in enumerate(slots)}
    symbol = {slot["buf"]: str(slot["symbol"]) for slot in slots}
    position = {buf: 0 for buf in column}
    orders: list[dict[str, Any]] = []
    balances = [{"ts": bars[0][0], "cash": run.starting_balance / balance_scale, "equity": run.starting_balance / balance_scale}]
    for (ts, closes), tick in zip(bars, run.ticks):
        for decision in tick.decisions:
            if decision.buf not in column:
                continue
            price = closes[column[decision.buf]]
            position[decision.buf] += decision.quantity if decision.action == "buy" else -decision.quantity
            orders.append({"ts": ts, "symbol": symbol[decision.buf], "side": decision.action, "quantity": decision.quantity, "price": price})
        cash = tick.balance / balance_scale
        holdings = sum(position[buf] * closes[i] for buf, i in column.items())
        balances.append({"ts": ts, "cash": cash, "equity": round(cash + holdings, 2)})
    return orders, balances


def _store(
    user_id: int,
    strategy: strategies.StrategyRow,
    orders: list[dict[str, Any]],
    balances: list[dict[str, Any]],
    range_start: date,
    range_end: date,
) -> tuple[int, int]:
    with db.session() as conn, conn.transaction():
        version_id = int(
            conn.execute(
                "INSERT INTO strategy_versions (strategy_id, document, ir, kind) VALUES (%s, %s, %s, 'backtest') RETURNING id",
                (strategy.id, Jsonb(strategy.document), Jsonb(strategy.ir) if strategy.ir is not None else None),
            ).fetchone()[0]
        )
        backtest_id = int(
            conn.execute(
                """
                INSERT INTO backtests (strategy_version_id, user_id, source, range_start, range_end)
                VALUES (%s, %s, %s, %s, %s) RETURNING id
                """,
                (version_id, user_id, SOURCE, range_start, range_end),
            ).fetchone()[0]
        )
        conn.cursor().executemany(
            "INSERT INTO backtest_orders (backtest_id, ts, symbol, side, quantity, price) VALUES (%s, %s, %s, %s, %s, %s)",
            [(backtest_id, o["ts"], o["symbol"], o["side"], o["quantity"], o["price"]) for o in orders],
        )
        conn.cursor().executemany(
            "INSERT INTO backtest_balances (backtest_id, ts, cash, equity) VALUES (%s, %s, %s, %s)",
            [(backtest_id, b["ts"], b["cash"], b["equity"]) for b in balances],
        )
    return backtest_id, version_id


def performance(orders: list[dict[str, Any]], balances: list[dict[str, Any]]) -> dict[str, Any]:
    """Return, drawdown, CAGR, Sharpe, and per-trade statistics from orders and the equity path."""
    equities = [float(point["equity"]) for point in balances]
    start = equities[0] if equities else 0.0
    end = equities[-1] if equities else 0.0
    peak = start
    max_drawdown = 0.0
    for equity in equities:
        peak = max(peak, equity)
        if peak > 0:
            max_drawdown = max(max_drawdown, (peak - equity) / peak * 100)
    closed = _closed_trades(orders)
    wins = [pnl for pnl in closed if pnl > 0]
    losses = [pnl for pnl in closed if pnl < 0]
    return {
        "equity": end,
        "return_pct": round(0.0 if start == 0 else (end - start) / start * 100, 2),
        "max_drawdown_pct": round(max_drawdown, 2),
        "gross_pnl": round(end - start, 2),
        "cagr_pct": _cagr_pct(balances, start, end),
        "sharpe": _sharpe(equities),
        "num_trades": len(closed),
        "num_trades_won": len(wins),
        "num_trades_lost": len(losses),
        "avg_win_amount": _mean(wins),
        "avg_loss_amount": _mean(losses),
        "expected_pnl_per_trade": _mean(closed),
        "trade_returns": [round(pnl, 2) for pnl in closed],
    }


def _closed_trades(orders: list[dict[str, Any]]) -> list[float]:
    """Cash P&L of each FIFO round trip: a sell closes the oldest open buys first."""
    lots: dict[str, list[list[float]]] = {}
    closed: list[float] = []
    for order in orders:
        book = lots.setdefault(str(order["symbol"]), [])
        quantity, price = float(order["quantity"]), float(order["price"])
        if order["side"] == "buy":
            book.append([quantity, price])
            continue
        if order["side"] != "sell":
            continue
        remaining = quantity
        while remaining > 0 and book:
            lot_quantity, lot_price = book[0]
            matched = min(remaining, lot_quantity)
            closed.append((price - lot_price) * matched)
            remaining -= matched
            if lot_quantity - matched <= 1e-9:
                book.pop(0)
            else:
                book[0][0] = lot_quantity - matched
    return closed


def _cagr_pct(balances: list[dict[str, Any]], start: float, end: float) -> float | None:
    if len(balances) < 2 or start <= 0 or end <= 0:
        return None
    opened, closed = _moment(balances[0]["ts"]), _moment(balances[-1]["ts"])
    years = (closed - opened).total_seconds() / (365.25 * 24 * 60 * 60)
    if years <= 0:
        return None
    return round(((end / start) ** (1 / years) - 1) * 100, 2)


def _sharpe(equities: list[float]) -> float | None:
    """Mean over standard deviation of per-step returns, scaled by sqrt(steps). Risk-free rate 0."""
    returns = [
        (equities[i] - equities[i - 1]) / equities[i - 1]
        for i in range(1, len(equities))
        if equities[i - 1] != 0
    ]
    if len(returns) < 2:
        return None
    mean = sum(returns) / len(returns)
    deviation = (sum((r - mean) ** 2 for r in returns) / (len(returns) - 1)) ** 0.5
    if deviation == 0:
        return None
    return round(mean / deviation * len(returns) ** 0.5, 2)


def _mean(values: list[float]) -> float | None:
    return round(sum(values) / len(values), 2) if values else None


def _moment(value: Any) -> datetime:
    return value if isinstance(value, datetime) else datetime.fromisoformat(str(value))


def _iso(row: dict[str, Any]) -> dict[str, Any]:
    return {**row, "ts": row["ts"].isoformat()}
