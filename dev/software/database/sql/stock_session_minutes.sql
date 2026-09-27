CREATE TABLE IF NOT EXISTS stock_session_minutes (
    symbol TEXT NOT NULL,
    ts TIMESTAMPTZ NOT NULL,
    open DOUBLE PRECISION NOT NULL,
    high DOUBLE PRECISION NOT NULL,
    low DOUBLE PRECISION NOT NULL,
    close DOUBLE PRECISION NOT NULL,
    volume BIGINT NOT NULL,
    is_filled BOOLEAN NOT NULL,
    PRIMARY KEY (symbol, ts)
);

SELECT create_hypertable(
    'stock_session_minutes',
    'ts',
    if_not_exists => TRUE,
    migrate_data => TRUE
);
