CREATE TABLE IF NOT EXISTS trading_days (
    session_date DATE PRIMARY KEY,
    open_at TIMESTAMPTZ NOT NULL,
    close_at TIMESTAMPTZ NOT NULL
);
