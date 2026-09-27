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

-- CREATE TABLE IF NOT EXISTS does not change an existing column. A
-- timestamp without time zone stores session-local wall time, so the same
-- instant loaded under two time zones does not conflict.
DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM pg_attribute AS attribute
        JOIN pg_type AS column_type ON column_type.oid = attribute.atttypid
        WHERE attribute.attrelid = 'stock_minute_bars'::regclass
          AND attribute.attname = 'ts'
          AND NOT attribute.attisdropped
          AND column_type.typname = 'timestamp'
    ) THEN
        ALTER TABLE stock_minute_bars
            ALTER COLUMN ts TYPE timestamptz
            USING ts AT TIME ZONE 'UTC';
    END IF;
END $$;

-- Timescale requires every unique index to include the partition column.
-- (symbol, ts) includes ts. if_not_exists does not add a primary key when
-- this table is already a hypertable.
SELECT create_hypertable(
    'stock_minute_bars',
    'ts',
    if_not_exists => TRUE,
    migrate_data => TRUE
);

-- @@unique-index
-- Run sql/dedupe_stock_minute_bars.sql before this section when the table
-- may already contain duplicate (symbol, ts) rows. The loader does that.
-- CREATE TABLE IF NOT EXISTS will not add the primary key above to a table
-- that already existed without one, and ON CONFLICT (symbol, ts) cannot
-- match rows unless a unique index on exactly those columns is present.
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_index AS index
        JOIN pg_class AS table_class ON table_class.oid = index.indrelid
        WHERE table_class.oid = 'stock_minute_bars'::regclass
          AND index.indisunique
          AND index.indisvalid
          AND index.indpred IS NULL
          AND (
              SELECT array_agg(attribute.attname::text ORDER BY attribute.attname)
              FROM unnest(index.indkey::smallint[]) WITH ORDINALITY AS columns(attnum, ordinality)
              JOIN pg_attribute AS attribute
                ON attribute.attrelid = table_class.oid
               AND attribute.attnum = columns.attnum
              WHERE columns.ordinality <= index.indnkeyatts
                AND columns.attnum > 0
          ) = ARRAY['symbol', 'ts']::text[]
    ) THEN
        CREATE UNIQUE INDEX stock_minute_bars_symbol_ts_key
            ON stock_minute_bars (symbol, ts);
    END IF;
END $$;
