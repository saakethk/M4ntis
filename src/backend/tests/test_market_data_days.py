"""Unit tests for trading-day intersection (no database)."""

from __future__ import annotations

from datetime import date

from src.backend.mantis.services.market_data import trading_days_all_symbols


def test_trading_days_all_symbols_intersects():
    aapl = {date(2024, 1, 2), date(2024, 1, 3), date(2024, 1, 5)}
    msft = {date(2024, 1, 2), date(2024, 1, 4), date(2024, 1, 5)}
    assert trading_days_all_symbols([aapl, msft]) == [date(2024, 1, 2), date(2024, 1, 5)]


def test_trading_days_all_symbols_empty():
    assert trading_days_all_symbols([]) == []
    assert trading_days_all_symbols([set(), {date(2024, 1, 1)}]) == []
