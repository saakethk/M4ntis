-- Upgrades applied after the base schema in software/database/sql.

-- Sharing used to be a separate table. Visibility on the strategy replaced it.
DROP TABLE IF EXISTS strategy_shares;

ALTER TABLE strategies
ADD COLUMN IF NOT EXISTS visibility TEXT NOT NULL DEFAULT 'private';

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'strategies_visibility_check'
          AND conrelid = 'strategies'::regclass
    ) THEN
        ALTER TABLE strategies
        ADD CONSTRAINT strategies_visibility_check CHECK (visibility IN ('private', 'public'));
    END IF;
END
$$;

-- Cached AI thread summaries. reply_count records how many replies the summary saw,
-- so a newer reply marks it stale.
ALTER TABLE discussion_posts ADD COLUMN IF NOT EXISTS ai_summary TEXT;
ALTER TABLE discussion_posts ADD COLUMN IF NOT EXISTS ai_summary_model TEXT;
ALTER TABLE discussion_posts ADD COLUMN IF NOT EXISTS ai_summary_reply_count INTEGER;
ALTER TABLE discussion_posts ADD COLUMN IF NOT EXISTS ai_summary_at TIMESTAMPTZ;

-- Where a backtest ran. Runs before FPGA execution replayed a fixed sample series.
ALTER TABLE backtests ADD COLUMN IF NOT EXISTS source TEXT NOT NULL DEFAULT 'sample';
