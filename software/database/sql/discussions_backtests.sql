CREATE TABLE IF NOT EXISTS discussion_posts (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    user_id BIGINT NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    strategy_id BIGINT REFERENCES strategies (id) ON DELETE SET NULL,
    parent_id BIGINT REFERENCES discussion_posts (id) ON DELETE CASCADE,
    body TEXT NOT NULL,
    likes_count INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS discussion_posts_parent_id_idx ON discussion_posts (parent_id);

CREATE INDEX IF NOT EXISTS discussion_posts_strategy_id_idx ON discussion_posts (strategy_id);

CREATE TABLE IF NOT EXISTS discussion_likes (
    post_id BIGINT NOT NULL REFERENCES discussion_posts (id) ON DELETE CASCADE,
    user_id BIGINT NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (post_id, user_id)
);

CREATE TABLE IF NOT EXISTS strategy_versions (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    strategy_id BIGINT NOT NULL REFERENCES strategies (id) ON DELETE CASCADE,
    document JSONB NOT NULL,
    ir JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS strategy_versions_strategy_id_idx ON strategy_versions (strategy_id);

CREATE TABLE IF NOT EXISTS backtests (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    strategy_version_id BIGINT NOT NULL REFERENCES strategy_versions (id) ON DELETE CASCADE,
    user_id BIGINT NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS backtests_strategy_version_id_idx ON backtests (strategy_version_id);

CREATE TABLE IF NOT EXISTS backtest_orders (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    backtest_id BIGINT NOT NULL REFERENCES backtests (id) ON DELETE CASCADE,
    ts TIMESTAMPTZ NOT NULL,
    symbol TEXT NOT NULL,
    side TEXT NOT NULL CHECK (side IN ('buy', 'sell')),
    quantity DOUBLE PRECISION NOT NULL,
    price DOUBLE PRECISION NOT NULL
);

CREATE INDEX IF NOT EXISTS backtest_orders_backtest_id_ts_idx ON backtest_orders (backtest_id, ts);

CREATE TABLE IF NOT EXISTS backtest_balances (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    backtest_id BIGINT NOT NULL REFERENCES backtests (id) ON DELETE CASCADE,
    ts TIMESTAMPTZ NOT NULL,
    cash DOUBLE PRECISION NOT NULL,
    equity DOUBLE PRECISION NOT NULL
);

CREATE INDEX IF NOT EXISTS backtest_balances_backtest_id_ts_idx ON backtest_balances (backtest_id, ts);
