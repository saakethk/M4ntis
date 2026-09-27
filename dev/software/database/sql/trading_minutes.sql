CREATE TABLE IF NOT EXISTS trading_minutes (
    ts TIMESTAMPTZ PRIMARY KEY,
    session_date DATE NOT NULL
);

CREATE INDEX IF NOT EXISTS trading_minutes_session_date_idx
    ON trading_minutes (session_date);
