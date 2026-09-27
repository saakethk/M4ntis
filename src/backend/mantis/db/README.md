# Database

- `__init__.py`: `connect()` opens an autocommit connection in UTC from the
  `TIGER_DB_*` settings and raises `DatabaseUnavailable` (503) when they are missing
  or the server is unreachable. `session()` yields a connection with the schema in
  place and closes it afterwards.
- `schema.py`: on the first session in a process, applies `dev/software/database/sql/`
  `users.sql`, `strategies.sql`, `discussions_backtests.sql`, then `migrations.sql`.
  Every statement is idempotent.
- `migrations.sql`: upgrades older databases (visibility column and check, dropping
  the old sharing table) and adds the cached-summary columns on `discussion_posts`.

Market-data tables (`stock_symbols`, `stock_minute_bars`) are created and filled by
the loaders in `dev/software/database`, not here.
