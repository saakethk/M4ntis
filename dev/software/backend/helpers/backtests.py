"""Run a strategy against stored market data and record the result.

The strategy is compiled with the TradeCPU compiler in software/compiler, then
replayed bar by bar through its golden-model simulator, which matches the RTL
instruction for instruction. Each bar is one tick round: one scaled close per
buffer, then the program's decisions and balance ack are read back.

``dummy_menu`` still serves the fixed sample series for the editor preview.
"""

from __future__ import annotations

import copy
import math
from datetime import date, datetime, time, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

import psycopg
from psycopg.types.json import Jsonb

from dev.software.backend.helpers.db import connect
from dev.software.backend.helpers.strategies import StrategyNotFound, can_view

START = datetime(2024, 1, 2, 14, 30, tzinfo=timezone.utc)
MARKET_TZ = ZoneInfo("America/New_York")

# Compiler resolution -> stream_ticker_data resolution.
BAR_RESOLUTIONS = {
    "1m": "1min",
    "5m": "5min",
    "15m": "15min",
    "30m": "30min",
    "1h": "1hour",
    "1d": "1day",
}
# The simulator runs in Python, so a run is capped at roughly a year of 5m bars.
MAX_BARS = 60_000
# Balance points stored per run. The equity path is evenly thinned to this.
MAX_BALANCE_POINTS = 500
MAX_CAPITAL = 21_000_000


class UserNotFound(Exception):
    pass


class BacktestNotFound(Exception):
    pass


class BacktestFailed(ValueError):
    """The run could not be simulated: bad dates, no market data, or a runaway program."""


class NegativeCash(BacktestFailed):
    """The strategy spent more cash than it had. The run is not stored."""


class ShortSale(BacktestFailed):
    """The strategy sold more shares than it held. The run is not stored."""


def dummy_orders() -> list[dict[str, Any]]:
    return [
        {
            "ts": START,
            "symbol": "AAPL",
            "side": "buy",
            "quantity": 10,
            "price": 180.0,
        },
        {
            "ts": START + timedelta(days=1),
            "symbol": "AAPL",
            "side": "sell",
            "quantity": 10,
            "price": 186.0,
        },
    ]


def dummy_balances() -> list[dict[str, Any]]:
    return [
        {"ts": START, "cash": 100_000.0, "equity": 100_000.0},
        {"ts": START + timedelta(minutes=1), "cash": 98_200.0, "equity": 100_000.0},
        {
            "ts": START + timedelta(days=1),
            "cash": 100_060.0,
            "equity": 100_060.0,
        },
    ]


def dummy_menu() -> dict[str, Any]:
    """Fixed backtest menu. Nothing is read from the database."""
    orders = [_public_row(order) for order in dummy_orders()]
    balances = [_public_row(point) for point in dummy_balances()]
    start_equity = float(balances[0]["equity"])
    end_equity = float(balances[-1]["equity"])
    return_pct = 0.0 if start_equity == 0 else (end_equity - start_equity) / start_equity * 100
    return {
        "dummy": True,
        "equity": end_equity,
        "return_pct": round(return_pct, 2),
        "orders": orders,
        "balances": balances,
    }


def performance(orders: list[dict[str, Any]], balances: list[dict[str, Any]]) -> dict[str, Any]:
    """Metrics the plan derives from orders and the equity path."""
    equities = [float(point["equity"]) for point in balances]
    start = equities[0] if equities else 0.0
    end = equities[-1] if equities else 0.0
    gross = end - start
    return_pct = 0.0 if start == 0 else (end - start) / start * 100
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
        "return_pct": round(return_pct, 2),
        "max_drawdown_pct": round(max_drawdown, 2),
        "gross_pnl": round(gross, 2),
        "cagr_pct": _cagr_pct(balances, start, end),
        "sharpe": _sharpe(equities),
        "num_trades": len(closed),
        "num_trades_won": len(wins),
        "num_trades_lost": len(losses),
        "avg_win_amount": round(sum(wins) / len(wins), 2) if wins else None,
        "avg_loss_amount": round(sum(losses) / len(losses), 2) if losses else None,
        "expected_pnl_per_trade": round(sum(closed) / len(closed), 2) if closed else None,
        "trade_returns": [round(pnl, 2) for pnl in closed],
    }


def get_backtest(viewer_id: int, backtest_id: int) -> dict[str, Any]:
    """One stored run, including orders, balances, and derived metrics."""
    conn = connect()
    try:
        row = conn.execute(
            """
            SELECT b.id, b.user_id, b.created_at, b.strategy_version_id,
                   v.strategy_id, s.name, s.user_id, s.visibility
            FROM backtests b
            JOIN strategy_versions v ON v.id = b.strategy_version_id
            JOIN strategies s ON s.id = v.strategy_id
            WHERE b.id = %s
            """,
            (backtest_id,),
        ).fetchone()
        if row is None:
            raise BacktestNotFound()
        runner_id = int(row[1])
        if runner_id != viewer_id and not can_view(int(row[6]), str(row[7]), viewer_id):
            raise BacktestNotFound()
        order_rows = conn.execute(
            """
            SELECT ts, symbol, side, quantity, price
            FROM backtest_orders
            WHERE backtest_id = %s
            ORDER BY ts, id
            """,
            (backtest_id,),
        ).fetchall()
        balance_rows = conn.execute(
            """
            SELECT ts, cash, equity
            FROM backtest_balances
            WHERE backtest_id = %s
            ORDER BY ts, id
            """,
            (backtest_id,),
        ).fetchall()
    finally:
        conn.close()
    orders = [_order_row(item) for item in order_rows]
    balances = [_balance_row(item) for item in balance_rows]
    return {
        "id": int(row[0]),
        "user_id": runner_id,
        "strategy_id": int(row[4]),
        "strategy_name": str(row[5]),
        "strategy_version_id": int(row[3]),
        "created_at": row[2].isoformat(),
        "dummy": False,
        "orders": orders,
        "balances": balances,
        "metrics": performance(orders, balances),
    }


def run_backtest(
    user_id: int,
    strategy_id: int,
    start: date | None = None,
    end: date | None = None,
    capital: float | None = None,
) -> dict[str, Any]:
    """Compile ``strategy_id``, replay it over market bars, and store the run.

    ``start`` and ``end`` are inclusive exchange-calendar dates. Either may be
    omitted to use all stored bars on that side. ``capital`` replaces the
    Start block's starting balance for this run only.
    """
    if start is not None and end is not None and end < start:
        raise BacktestFailed("End date must be on or after the start date")
    if capital is not None and not 0 < capital <= MAX_CAPITAL:
        raise BacktestFailed(f"Capital must be more than $0 and at most ${MAX_CAPITAL:,}")

    strategy = _load_strategy(user_id, strategy_id)
    document = strategy["document"]
    run_document = _with_capital(document, capital) if capital is not None else document

    # Compile once at the default exponents to learn the symbols and resolution,
    # then again with exponents that fit each symbol's prices into int16.
    manifest = _compile(run_document, {}).manifest
    symbols = _used_symbols(manifest)
    if not symbols:
        raise BacktestFailed("The strategy does not read any ticker, so there is nothing to backtest")
    bars = _load_bars(symbols, manifest["resolution"], start, end)
    exponents = {buf: _price_exponent(symbol, bars) for buf, symbol in symbols.items()}
    result = _compile(run_document, exponents)

    orders, balances = simulate(result.words, result.manifest, bars)
    backtest_id, version_id = _store_run(user_id, strategy_id, strategy, orders, balances)
    public_orders = [_public_row(order) for order in orders]
    public_balances = [_public_row(point) for point in balances]
    return {
        "id": backtest_id,
        "user_id": user_id,
        "strategy_id": strategy_id,
        "strategy_version_id": version_id,
        "dummy": False,
        "resolution": result.manifest["resolution"],
        "bars": len(bars),
        "orders": public_orders,
        "balances": public_balances,
        "metrics": performance(public_orders, public_balances),
    }


def simulate(
    words: list[int],
    manifest: dict[str, Any],
    bars: list[tuple[datetime, dict[str, float]]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Run a compiled program over aligned bars on the golden model.

    ``bars`` is ``[(ts, {symbol: close})]`` in time order. Returns orders and a
    thinned equity path. Positions are marked to each bar's close.
    """
    buffers = {int(item["buf"]): item for item in manifest["buffers"] if item["symbol"]}
    history = int(manifest["historyTicks"])
    if len(bars) < history:
        raise BacktestFailed(
            f"The strategy needs {history} bars of history, but the range only has {len(bars)}"
        )

    cpu = TradeCPU(words)
    try:
        cpu.run_until_blocked()
    except SimError as exc:
        raise BacktestFailed(f"The program did not start: {exc}") from exc
    cash = _last_balance(cpu.drain(), float(manifest["startingBalance"]))

    positions: dict[str, float] = {}
    orders: list[dict[str, Any]] = []
    path: list[dict[str, Any]] = []
    for ts, closes in bars:
        scaled: dict[int, int] = {}
        for buf in range(NUM_BUFFERS):
            item = buffers.get(buf)
            price = 0
            if item is not None and item["symbol"] in closes:
                price = round(closes[item["symbol"]] * 10 ** int(item["priceExponent"]))
            scaled[buf] = price
            cpu.tick(buf, price)
        try:
            cpu.run_until_blocked()
        except SimError as exc:
            raise BacktestFailed(f"The program stopped at {ts.isoformat()}: {exc}") from exc
        messages = cpu.drain()
        for message in messages:
            if not isinstance(message, Decision):
                continue
            item = buffers.get(message.buf)
            if item is None:
                continue
            # The price the CPU charged, not the raw close.
            price = scaled[message.buf] / 10 ** int(item["priceExponent"])
            symbol = str(item["symbol"])
            signed = message.quantity if message.action == "buy" else -message.quantity
            held = positions.get(symbol, 0.0)
            # The CPU does not track shares, so selling more than is held would be a short sale.
            if message.action == "sell" and message.quantity > held:
                raise ShortSale(
                    f"The strategy tried to sell {message.quantity} {symbol} at {ts.isoformat()} "
                    f"but held {held:g}. Short selling is not allowed, so the backtest was stopped "
                    "and nothing was saved. Only sell after a buy, for example by tracking a "
                    "holding flag in a variable."
                )
            # The CPU does not check cash, so a buy it cannot afford ends the run.
            cash = round(cash - signed * price, 2)
            if cash < 0:
                raise NegativeCash(
                    f"Cash went negative (${cash:,.2f}) at {ts.isoformat()} when the strategy "
                    f"bought {message.quantity} {symbol} at ${price:,.2f}. The backtest was stopped "
                    "and nothing was saved. Lower the order size or add a balance check before buying."
                )
            positions[symbol] = positions.get(symbol, 0.0) + signed
            orders.append(
                {
                    "ts": ts,
                    "symbol": symbol,
                    "side": message.action,
                    "quantity": message.quantity,
                    "price": price,
                }
            )
        cash = _last_balance(messages, cash)
        held = sum(quantity * closes.get(symbol, 0.0) for symbol, quantity in positions.items())
        path.append({"ts": ts, "cash": round(cash, 2), "equity": round(cash + held, 2)})
    return orders, _thin(path, MAX_BALANCE_POINTS)


def _last_balance(messages: list[Any], fallback: float) -> float:
    """Cash from the last EMIT_BALANCE in ``messages``. Balance is kept in cents."""
    for message in reversed(messages):
        if isinstance(message, BalanceMsg):
            return message.value / 100
    return fallback


def _thin(path: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    if len(path) <= limit:
        return path
    step = math.ceil(len(path) / limit)
    thinned = path[::step]
    if thinned[-1] is not path[-1]:
        thinned.append(path[-1])
    return thinned


def _compile(document: Any, exponents: dict[int, int]) -> CompileResult:
    try:
        return compile_strategy(document, CompileOptions(price_exponents=dict(exponents)))
    except CompileError as exc:
        raise compile_helpers.CompilationFailed([d.to_json() for d in exc.diagnostics]) from exc
    except (TypeError, AttributeError, KeyError, ValueError) as exc:
        raise compile_helpers.CompilationFailed([{"level": "error", "message": str(exc)}]) from exc


def _with_capital(document: Any, capital: float) -> Any:
    """Copy of ``document`` whose Start block starts with ``capital``."""
    if not isinstance(document, dict) or not isinstance(document.get("flow"), dict):
        return document
    changed = copy.deepcopy(document)
    for node in changed["flow"].get("nodes") or []:
        if isinstance(node, dict) and node.get("type") == "start":
            data = node.setdefault("data", {})
            if isinstance(data, dict) and isinstance(data.setdefault("params", {}), dict):
                data["params"]["startingBalance"] = capital
    return changed


def _used_symbols(manifest: dict[str, Any]) -> dict[int, str]:
    return {
        int(item["buf"]): str(item["symbol"])
        for item in manifest["buffers"]
        if item["used"] and item["symbol"]
    }


def _load_bars(
    symbols: dict[int, str],
    resolution: str,
    start: date | None,
    end: date | None,
) -> list[tuple[datetime, dict[str, float]]]:
    """Closes for every symbol at ``resolution``, kept only where all symbols have a bar."""
    bar_resolution = BAR_RESOLUTIONS.get(resolution)
    if bar_resolution is None:
        raise BacktestFailed(f"Resolution {resolution!r} cannot be backtested")
    since = datetime.combine(start, time(), MARKET_TZ) if start is not None else None
    until = datetime.combine(end + timedelta(days=1), time(), MARKET_TZ) if end is not None else None

    series: dict[str, dict[datetime, float]] = {}
    for symbol in sorted(set(symbols.values())):
        closes: dict[datetime, float] = {}
        for bar in stream_ticker_data(symbol, bar_resolution, since, until):
            closes[bar["ts"]] = float(bar["close"])
            if len(closes) > MAX_BARS:
                raise BacktestFailed(
                    f"The range has more than {MAX_BARS:,} {resolution} bars. "
                    "Pick a shorter range or a coarser resolution."
                )
        if not closes:
            raise BacktestFailed(f"No market data for {symbol} in that range")
        series[symbol] = closes

    shared = set.intersection(*(set(closes) for closes in series.values()))
    if not shared:
        raise BacktestFailed("The symbols have no bars in common in that range")
    return [
        (ts, {symbol: closes[ts] for symbol, closes in series.items()})
        for ts in sorted(shared)
    ]


def _price_exponent(symbol: str, bars: list[tuple[datetime, dict[str, float]]]) -> int:
    """Largest exponent (2 = cents) at which every close for ``symbol`` fits in int16."""
    highest = max(closes[symbol] for _, closes in bars)
    for exponent in (2, 1, 0):
        if round(highest * 10**exponent) <= IMM16_MAX:
            return exponent
    raise BacktestFailed(f"{symbol} trades above ${IMM16_MAX:,}, which the TradeCPU cannot represent")


def _load_strategy(user_id: int, strategy_id: int) -> dict[str, Any]:
    conn = connect()
    try:
        if conn.execute("SELECT 1 FROM users WHERE id = %s", (user_id,)).fetchone() is None:
            raise UserNotFound()
        row = conn.execute(
            "SELECT user_id, visibility, document, ir FROM strategies WHERE id = %s",
            (strategy_id,),
        ).fetchone()
    finally:
        conn.close()
    if row is None or not can_view(int(row[0]), str(row[1]), user_id):
        raise StrategyNotFound()
    return {"document": row[2], "ir": row[3]}


def _store_run(
    user_id: int,
    strategy_id: int,
    strategy: dict[str, Any],
    orders: list[dict[str, Any]],
    balances: list[dict[str, Any]],
) -> tuple[int, int]:
    """Snapshot the strategy that was run, then write its orders and balances."""
    conn = connect()
    try:
        # connect() already ran SET TIME ZONE, which opens a transaction.
        # transaction() would only be a savepoint, and close() would roll the run back.
        conn.commit()
        with conn.transaction():
            version = conn.execute(
                """
                INSERT INTO strategy_versions (strategy_id, document, ir, kind)
                VALUES (%s, %s, %s, 'backtest')
                RETURNING id
                """,
                (
                    strategy_id,
                    Jsonb(strategy["document"]),
                    Jsonb(strategy["ir"]) if strategy["ir"] is not None else None,
                ),
            ).fetchone()
            backtest = conn.execute(
                """
                INSERT INTO backtests (strategy_version_id, user_id)
                VALUES (%s, %s)
                RETURNING id
                """,
                (int(version[0]), user_id),
            ).fetchone()
            backtest_id = int(backtest[0])
            # COPY sends every row in one stream. A long run can have tens of
            # thousands of orders, and the database is remote.
            with conn.cursor() as cur:
                with cur.copy(
                    "COPY backtest_orders (backtest_id, ts, symbol, side, quantity, price) FROM STDIN"
                ) as copy_rows:
                    for order in orders:
                        copy_rows.write_row(
                            (
                                backtest_id,
                                order["ts"],
                                order["symbol"],
                                order["side"],
                                order["quantity"],
                                order["price"],
                            )
                        )
                with cur.copy(
                    "COPY backtest_balances (backtest_id, ts, cash, equity) FROM STDIN"
                ) as copy_rows:
                    for point in balances:
                        copy_rows.write_row(
                            (backtest_id, point["ts"], point["cash"], point["equity"])
                        )
    finally:
        conn.close()
    return backtest_id, int(version[0])


def _public_row(row: dict[str, Any]) -> dict[str, Any]:
    copied = dict(row)
    copied["ts"] = copied["ts"].isoformat()
    return copied


def _order_row(row: tuple) -> dict[str, Any]:
    return {
        "ts": row[0].isoformat(),
        "symbol": str(row[1]),
        "side": str(row[2]),
        "quantity": float(row[3]),
        "price": float(row[4]),
    }


def _balance_row(row: tuple) -> dict[str, Any]:
    return {"ts": row[0].isoformat(), "cash": float(row[1]), "equity": float(row[2])}


def _moment(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        return datetime.fromisoformat(value)
    return None


def _closed_trades(orders: list[dict[str, Any]]) -> list[float]:
    """FIFO round trips. A sell against an earlier buy records the cash P&L."""
    lots: dict[str, list[list[float]]] = {}
    closed: list[float] = []
    for order in orders:
        symbol = str(order["symbol"])
        quantity = float(order["quantity"])
        price = float(order["price"])
        book = lots.setdefault(symbol, [])
        if order["side"] == "buy":
            book.append([quantity, price])
            continue
        if order["side"] != "sell":
            continue
        remaining = quantity
        while remaining > 0 and book:
            lot_qty, lot_price = book[0]
            matched = min(remaining, lot_qty)
            closed.append((price - lot_price) * matched)
            remaining -= matched
            leftover = lot_qty - matched
            if leftover <= 1e-9:
                book.pop(0)
            else:
                book[0][0] = leftover
    return closed


def _cagr_pct(balances: list[dict[str, Any]], start: float, end: float) -> float | None:
    if len(balances) < 2 or start <= 0 or end <= 0:
        return None
    opened = _moment(balances[0]["ts"])
    closed = _moment(balances[-1]["ts"])
    if opened is None or closed is None:
        return None
    years = (closed - opened).total_seconds() / (365.25 * 24 * 60 * 60)
    if years <= 0:
        return None
    return round(((end / start) ** (1 / years) - 1) * 100, 2)


def _sharpe(equities: list[float]) -> float | None:
    """Per-step equity returns, scaled by the square root of the step count. Risk-free rate is 0."""
    returns = [
        (equities[index] - equities[index - 1]) / equities[index - 1]
        for index in range(1, len(equities))
        if equities[index - 1] != 0
    ]
    if len(returns) < 2:
        return None
    mean = sum(returns) / len(returns)
    variance = sum((item - mean) ** 2 for item in returns) / (len(returns) - 1)
    deviation = variance**0.5
    if deviation == 0:
        return None
    return round(mean / deviation * (len(returns) ** 0.5), 2)
