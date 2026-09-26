-- Delete extra stock_minute_bars rows that share (symbol, ts), keeping one.
--
-- Safe to run more than once. A unique index on (symbol, ts) already makes
-- exact duplicates impossible, so this returns immediately. Otherwise it
-- counts duplicates with a normal aggregate. That aggregate works on a
-- columnstore chunk. ctid does not: transparent decompression only supports
-- the tableoid system column, and selecting ctid raises InvalidColumnReference.
--
-- ctid is used only after a duplicate exists. Compressed chunks are
-- decompressed first so the earliest stored copy (smallest ctid) can be kept.
-- A later columnstore policy compresses those chunks again.

CREATE OR REPLACE FUNCTION dedupe_stock_minute_bars()
RETURNS bigint
LANGUAGE plpgsql
AS $$
DECLARE
    removed bigint := 0;
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

    -- Planned only when Timescale is installed and a duplicate minute exists.
    IF EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'timescaledb') THEN
        PERFORM decompress_chunk(chunk, if_compressed => true)
        FROM show_chunks('stock_minute_bars') AS chunk;
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
