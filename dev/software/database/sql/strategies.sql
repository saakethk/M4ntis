CREATE TABLE IF NOT EXISTS strategies (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    user_id BIGINT NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    visibility TEXT NOT NULL DEFAULT 'private' CONSTRAINT strategies_visibility_check CHECK (visibility IN ('private', 'public')),
    document JSONB NOT NULL,
    ir JSONB,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS strategies_user_id_idx ON strategies (user_id);
