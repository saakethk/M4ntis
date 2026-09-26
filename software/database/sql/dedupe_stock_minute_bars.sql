-- Delete extra stock_minute_bars rows that share (symbol, ts), keeping one.
--
-- Safe to run more than once. A unique index on (symbol, ts) already makes
-- exact duplicates impossible, so this returns immediately. Otherwise it
-- counts duplicates with a normal aggregate. That aggregate works on a
-- columnstore chunk.
--
-- ctid does not. Transparent decompression only supports the tableoid system
-- column, and selecting ctid raises InvalidColumnReference. When any chunk is
-- compressed, duplicates are collapsed by rewriting distinct (symbol, ts)
-- rows. ctid is used only when every chunk is a normal row chunk, where it
-- identifies the earliest stored copy.

CREATE OR REPLACE FUNCTION dedupe_stock_minute_bars()
RETURNS bigint
LANGUAGE plpgsql
AS $$
DECLARE
    removed bigint := 0;
    total_rows bigint;
    kept_rows bigint;
    has_duplicate boolean;
    has_compressed boolean := false;
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

    IF EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'timescaledb') THEN
        SELECT EXISTS (
            SELECT 1
            FROM timescaledb_information.chunks
            WHERE hypertable_name = 'stock_minute_bars'
              AND is_compressed
        )
        INTO has_compressed;
    END IF;

    IF has_compressed THEN
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
    END IF;

    DROP TABLE IF EXISTS pg_temp.stock_minute_bars_dedupe_extra;
    CREATE TEMP TABLE stock_minute_bars_dedupe_extra ON COMMIT DROP AS
    SELECT symbol, ts, ctid AS row_ctid
    FROM (
        SELECT
            symbol,
            ts,
            ctid,
            row_number() OVER (
                PARTITION BY symbol, ts
                ORDER BY ctid
            ) AS rn
        FROM stock_minute_bars
    ) ranked
    WHERE rn > 1;

    DELETE FROM stock_minute_bars AS extra
    USING stock_minute_bars_dedupe_extra AS doomed
    WHERE extra.symbol = doomed.symbol
      AND extra.ts = doomed.ts
      AND extra.ctid = doomed.row_ctid;

    GET DIAGNOSTICS removed = ROW_COUNT;
    RETURN removed;
END;
$$;
