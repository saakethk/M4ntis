-- Delete extra stock_minute_bars rows that share (symbol, ts), keeping one.
--
-- A columnstore chunk cannot expose ctid. Selecting it raises
-- InvalidColumnReference: transparent decompression only supports tableoid.
-- This function never reads ctid. When duplicate minutes exist it rewrites
-- one row per (symbol, ts) from the real columns, which decompression can read.

CREATE OR REPLACE FUNCTION dedupe_stock_minute_bars()
RETURNS bigint
LANGUAGE plpgsql
AS $$
DECLARE
    removed bigint := 0;
    total_rows bigint;
    kept_rows bigint;
    has_duplicate boolean;
BEGIN
    IF to_regclass('stock_minute_bars') IS NULL THEN
        RETURN 0;
    END IF;

    IF EXISTS (
        SELECT 1
        FROM pg_index AS index
        JOIN pg_class AS table_class ON table_class.oid = index.indrelid
        WHERE table_class.oid = 'stock_minute_bars'::regclass
          AND index.indisunique
          AND index.indisvalid
          AND index.indpred IS NULL
          AND index.indnkeyatts = 2
          AND EXISTS (
              SELECT 1
              FROM pg_attribute AS attribute
              WHERE attribute.attrelid = table_class.oid
                AND attribute.attname = 'symbol'
                AND attribute.attnum = ANY (index.indkey)
                AND attribute.attnum > 0
          )
          AND EXISTS (
              SELECT 1
              FROM pg_attribute AS attribute
              WHERE attribute.attrelid = table_class.oid
                AND attribute.attname = 'ts'
                AND attribute.attnum = ANY (index.indkey)
                AND attribute.attnum > 0
          )
    ) THEN
        RETURN 0;
    END IF;

    SELECT EXISTS (
        SELECT 1
        FROM stock_minute_bars
        GROUP BY symbol, ts
        HAVING count(*) > 1
    )
    INTO has_duplicate;

    IF NOT has_duplicate THEN
        RETURN 0;
    END IF;

    DROP TABLE IF EXISTS pg_temp.stock_minute_bars_dedupe_keep;
    CREATE TEMP TABLE stock_minute_bars_dedupe_keep ON COMMIT DROP AS
    SELECT DISTINCT ON (symbol, ts)
        symbol,
        ts,
        open,
        high,
        low,
        close,
        volume,
        trade_count,
        vwap
    FROM stock_minute_bars
    ORDER BY symbol, ts;

    SELECT count(*) INTO total_rows FROM stock_minute_bars;
    SELECT count(*) INTO kept_rows FROM stock_minute_bars_dedupe_keep;
    removed := total_rows - kept_rows;

    TRUNCATE stock_minute_bars;
    INSERT INTO stock_minute_bars (
        symbol, ts, open, high, low, close, volume, trade_count, vwap
    )
    SELECT
        symbol, ts, open, high, low, close, volume, trade_count, vwap
    FROM stock_minute_bars_dedupe_keep;

    RETURN removed;
END;
$$;
