-- Delete extra stock_minute_bars rows that share (symbol, ts), keeping one.
--
-- Safe to run more than once. When a unique index already exists, exact
-- duplicates cannot be stored and this deletes nothing. When the index is
-- missing, Timescale allows a second copy of the same minute; this removes
-- those copies before the unique index is created.
--
-- The row with the smallest ctid is kept. That is the earliest stored copy,
-- which is the original load when a later rerun inserted the duplicate.
-- Same (symbol, ts) values fall in one hypertable chunk, so ctid is unique
-- among the duplicates.

CREATE OR REPLACE FUNCTION dedupe_stock_minute_bars()
RETURNS bigint
LANGUAGE plpgsql
AS $$
DECLARE
    removed bigint := 0;
BEGIN
    IF to_regclass('stock_minute_bars') IS NULL THEN
        RETURN 0;
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
