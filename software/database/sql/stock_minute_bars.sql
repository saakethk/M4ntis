CREATE EXTENSION IF NOT EXISTS timescaledb;

CREATE TABLE IF NOT EXISTS stock_minute_bars (
    symbol TEXT NOT NULL,
    ts TIMESTAMPTZ NOT NULL,
    open DOUBLE PRECISION NOT NULL,
    high DOUBLE PRECISION NOT NULL,
    low DOUBLE PRECISION NOT NULL,
    close DOUBLE PRECISION NOT NULL,
    volume BIGINT NOT NULL,
    trade_count BIGINT,
    vwap DOUBLE PRECISION,
    PRIMARY KEY (symbol, ts)
);

SELECT create_hypertable(
    'stock_minute_bars',
    'ts',
    if_not_exists => TRUE,
    migrate_data => TRUE
);
