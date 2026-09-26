"""Checks for minute-bar de-duplication that do not call Alpaca."""

from __future__ import annotations

import logging
import sys
import unittest
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import load_minute_bars as loader


@contextmanager
def _capture_psycopg_warnings():
    """Record psycopg warnings, including transaction rollback failures."""
    records: list[logging.LogRecord] = []
    handler = logging.Handler()
    handler.setLevel(logging.DEBUG)
    handler.emit = records.append
    logger = logging.getLogger("psycopg")
    previous = logger.level
    logger.setLevel(logging.DEBUG)
    logger.addHandler(handler)
    try:
        yield records
    finally:
        logger.removeHandler(handler)
        logger.setLevel(previous)


def _rollback_warnings(records: list[logging.LogRecord]) -> list[str]:
    messages = []
    for record in records:
        message = record.getMessage()
        if "error ignored in rollback" in message or (
            "another command is already in progress" in message
            and "rollback" in message
        ):
            messages.append(message)
    return messages


def _bar(timestamp: str, close: float, volume: int = 10) -> dict:
    return {
        "t": timestamp,
        "o": close,
        "h": close,
        "l": close,
        "c": close,
        "v": volume,
        "n": 1,
        "vw": close,
    }


class ParseTimestampTests(unittest.TestCase):
    def test_naive_and_aware_utc_are_the_same_instant(self) -> None:
        aware = loader.parse_bar_ts("2024-01-02T14:30:00Z")
        naive = loader.parse_bar_ts("2024-01-02T14:30:00")
        offset = loader.parse_bar_ts("2024-01-02T09:30:00-05:00")
        self.assertEqual(aware, naive)
        self.assertEqual(aware, offset)
        self.assertEqual(aware.tzinfo, timezone.utc)

    def test_extra_fractional_digits_do_not_change_the_microsecond(self) -> None:
        short = loader.parse_bar_ts("2024-01-02T14:30:00.123456Z")
        long = loader.parse_bar_ts("2024-01-02T14:30:00.123456789Z")
        self.assertEqual(short, long)


class WindowTests(unittest.TestCase):
    def test_adjacent_windows_do_not_share_an_inclusive_end(self) -> None:
        start = datetime(2024, 6, 3, 14, 30, tzinfo=timezone.utc)
        end = start + timedelta(days=62)
        window_end = min(start + loader.WINDOW, end)
        next_start = window_end
        self.assertLess(loader.alpaca_inclusive_end(window_end), next_start)
        self.assertEqual(next_start, start + loader.WINDOW)

    def test_fetch_requests_a_half_open_interval(self) -> None:
        captured: list[dict] = []

        class FakeResponse:
            status_code = 200

            def json(self) -> dict:
                return {"bars": {}, "next_page_token": None}

            def raise_for_status(self) -> None:
                return None

        class FakeSession:
            def get(self, url: str, params: dict, timeout: int) -> FakeResponse:
                captured.append(params)
                return FakeResponse()

        start = datetime(2024, 6, 3, 14, 30, tzinfo=timezone.utc)
        end = start + timedelta(days=31)
        loader.fetch_bars(FakeSession(), ["AAPL"], start, end, "iex", False)
        self.assertEqual(len(captured), 1)
        self.assertEqual(captured[0]["start"], start.isoformat())
        self.assertEqual(
            captured[0]["end"],
            loader.alpaca_inclusive_end(end).isoformat(),
        )
        self.assertLess(captured[0]["end"], end.isoformat())


class MetaCollapseTests(unittest.TestCase):
    def test_native_meta_wins_over_fb_for_the_same_instant(self) -> None:
        native = loader.rows_from_bars(
            "META",
            [_bar("2022-06-08T14:30:00Z", close=2)],
            map_fb_to_meta=True,
        )
        mapped = loader.rows_from_bars(
            "FB",
            [_bar("2022-06-08T10:30:00-04:00", close=9)],
            map_fb_to_meta=True,
        )
        kept = loader.prefer_native_bars(mapped + native)
        self.assertEqual(len(kept), 1)
        self.assertEqual(kept[0][0], "META")
        self.assertEqual(kept[0][2], 2)
        self.assertEqual(kept[0][-1], 0)

    def test_fb_bars_on_or_after_the_rename_are_dropped(self) -> None:
        rows = loader.rows_from_bars(
            "FB",
            [_bar("2022-06-09T14:30:00Z", close=3)],
            map_fb_to_meta=True,
        )
        self.assertEqual(rows, [])


class SqlScriptTests(unittest.TestCase):
    def test_schema_splits_around_the_unique_index_marker(self) -> None:
        schema = (loader.SQL_DIR / "stock_minute_bars.sql").read_text()
        before, marker, after = schema.partition(loader.UNIQUE_INDEX_MARKER)
        self.assertEqual(marker, loader.UNIQUE_INDEX_MARKER)
        before_sql = loader.split_sql(before)
        after_sql = loader.split_sql(after)
        self.assertTrue(any("create_hypertable" in statement for statement in before_sql))
        self.assertTrue(any("timestamptz" in statement for statement in before_sql))
        self.assertEqual(len(after_sql), 1)
        self.assertIn("CREATE UNIQUE INDEX stock_minute_bars_symbol_ts_key", after_sql[0])
        self.assertIn("(symbol, ts)", after_sql[0])

    def test_dedupe_function_is_one_statement(self) -> None:
        script = (loader.SQL_DIR / "dedupe_stock_minute_bars.sql").read_text()
        statements = loader.split_sql(script)
        self.assertEqual(len(statements), 1)
        self.assertIn("PARTITION BY symbol, ts", statements[0])
        self.assertIn("HAVING count(*) > 1", statements[0])
        self.assertIn("DISTINCT ON (symbol, ts)", statements[0])
        self.assertIn("is_compressed", statements[0])
        self.assertIn("dedupe_stock_minute_bars", statements[0])


class PostgresDedupeTests(unittest.TestCase):
    dsn = "dbname=minute_bars_test user=ubuntu"

    @classmethod
    def setUpClass(cls) -> None:
        try:
            cls.conn = loader.psycopg.connect(cls.dsn, autocommit=True)
        except Exception as exc:  # noqa: BLE001 - skip when Postgres is absent
            raise unittest.SkipTest(f"Postgres is not available: {exc}") from exc
        cls.conn.execute("SET TIME ZONE 'UTC'")

    @classmethod
    def tearDownClass(cls) -> None:
        conn = getattr(cls, "conn", None)
        if conn is not None:
            conn.close()

    def setUp(self) -> None:
        self.conn.execute("DROP TABLE IF EXISTS stock_minute_bars CASCADE")
        loader.execute_sql_script(
            self.conn,
            (loader.SQL_DIR / "dedupe_stock_minute_bars.sql").read_text(),
        )

    def _schema_sections(self) -> tuple[list[str], list[str]]:
        schema = (loader.SQL_DIR / "stock_minute_bars.sql").read_text()
        before, _, after = schema.partition(loader.UNIQUE_INDEX_MARKER)
        return loader.split_sql(before), loader.split_sql(after)

    def _alter_timestamp_column(self) -> None:
        before, _ = self._schema_sections()
        alter = next(statement for statement in before if "AT TIME ZONE 'UTC'" in statement)
        self.conn.execute(alter)

    def _ensure_unique_index(self) -> None:
        _, after = self._schema_sections()
        loader.execute_sql_script(self.conn, after[0])

    def _unique_index_count(self) -> int:
        row = self.conn.execute(
            """
            SELECT count(*)
            FROM pg_index AS index
            JOIN pg_class AS table_class ON table_class.oid = index.indrelid
            WHERE table_class.oid = 'stock_minute_bars'::regclass
              AND index.indisunique
            """
        ).fetchone()
        return int(row[0])

    def test_dedupe_keeps_the_first_copy_and_conflict_skips_a_rerun(self) -> None:
        self.conn.execute(
            """
            CREATE TABLE stock_minute_bars (
                symbol TEXT NOT NULL,
                ts TIMESTAMP NOT NULL,
                open DOUBLE PRECISION NOT NULL,
                high DOUBLE PRECISION NOT NULL,
                low DOUBLE PRECISION NOT NULL,
                close DOUBLE PRECISION NOT NULL,
                volume BIGINT NOT NULL,
                trade_count BIGINT,
                vwap DOUBLE PRECISION
            )
            """
        )
        self.conn.execute(
            """
            INSERT INTO stock_minute_bars
            VALUES
                ('AAPL', '2024-01-02 14:30:00', 1, 1, 1, 1, 10, 1, 1),
                ('AAPL', '2024-01-02 14:30:00', 9, 9, 9, 9, 99, 9, 9),
                ('META', '2024-01-02 14:31:00', 3, 3, 3, 3, 30, 3, 3)
            """
        )
        self._alter_timestamp_column()
        column_type = self.conn.execute(
            """
            SELECT typname
            FROM pg_attribute AS attribute
            JOIN pg_type AS column_type ON column_type.oid = attribute.atttypid
            WHERE attribute.attrelid = 'stock_minute_bars'::regclass
              AND attribute.attname = 'ts'
            """
        ).fetchone()[0]
        self.assertEqual(column_type, "timestamptz")

        removed = self.conn.execute("SELECT dedupe_stock_minute_bars()").fetchone()[0]
        self.assertEqual(removed, 1)
        kept = self.conn.execute(
            """
            SELECT symbol, open
            FROM stock_minute_bars
            WHERE symbol = 'AAPL'
            """
        ).fetchall()
        self.assertEqual(kept, [("AAPL", 1.0)])
        self.assertEqual(
            self.conn.execute("SELECT dedupe_stock_minute_bars()").fetchone()[0],
            0,
        )

        self._ensure_unique_index()
        self.assertEqual(self._unique_index_count(), 1)
        # Running the unique-index section again must not add a second index.
        self._ensure_unique_index()
        self.assertEqual(self._unique_index_count(), 1)

        rows = loader.rows_from_bars(
            "AAPL",
            [_bar("2024-01-02T14:30:00Z", close=5)],
            map_fb_to_meta=False,
        )
        inserted = loader.insert_rows(self.conn, rows)
        self.assertEqual(inserted, 0)
        self.assertEqual(
            self.conn.execute("SELECT count(*) FROM stock_minute_bars").fetchone()[0],
            2,
        )
        self.assertEqual(
            self.conn.execute(
                "SELECT open FROM stock_minute_bars WHERE symbol = 'AAPL'"
            ).fetchone()[0],
            1.0,
        )

        self.conn.execute("SET TIME ZONE 'America/New_York'")
        inserted_again = loader.insert_rows(self.conn, rows)
        self.conn.execute("SET TIME ZONE 'UTC'")
        self.assertEqual(inserted_again, 0)
        self.assertEqual(
            self.conn.execute("SELECT count(*) FROM stock_minute_bars").fetchone()[0],
            2,
        )

    def test_existing_primary_key_is_left_in_place(self) -> None:
        before, _ = self._schema_sections()
        create_table = next(
            statement for statement in before if statement.startswith("CREATE TABLE")
        )
        self.conn.execute(create_table)
        self._ensure_unique_index()
        self.assertEqual(self._unique_index_count(), 1)
        index_name = self.conn.execute(
            """
            SELECT index_class.relname
            FROM pg_index AS index
            JOIN pg_class AS table_class ON table_class.oid = index.indrelid
            JOIN pg_class AS index_class ON index_class.oid = index.indexrelid
            WHERE table_class.oid = 'stock_minute_bars'::regclass
              AND index.indisunique
            """
        ).fetchone()[0]
        self.assertEqual(index_name, "stock_minute_bars_pkey")

    def _stage_row(self, *, volume: object = 10):
        return (
            "AAPL",
            datetime(2024, 1, 2, 14, 30, tzinfo=timezone.utc),
            1.0,
            1.0,
            1.0,
            1.0,
            volume,
            1,
            1.0,
            0,
        )

    def _create_bars_table(self, *, unique: bool) -> None:
        self.conn.execute(
            """
            CREATE TABLE stock_minute_bars (
                symbol TEXT NOT NULL,
                ts TIMESTAMPTZ NOT NULL,
                open DOUBLE PRECISION NOT NULL,
                high DOUBLE PRECISION NOT NULL,
                low DOUBLE PRECISION NOT NULL,
                close DOUBLE PRECISION NOT NULL,
                volume BIGINT NOT NULL,
                trade_count BIGINT,
                vwap DOUBLE PRECISION
            )
            """
        )
        if unique:
            self.conn.execute(
                """
                ALTER TABLE stock_minute_bars
                ADD PRIMARY KEY (symbol, ts)
                """
            )

    def _assert_connection_usable(self) -> None:
        self.assertTrue(self.conn.autocommit)
        self.assertEqual(self.conn.info.transaction_status, 0)
        self.assertEqual(self.conn.execute("SELECT 1").fetchone()[0], 1)
        self.assertFalse(self.conn.pgconn.pipeline_status)

    def test_failed_copy_does_not_break_rollback(self) -> None:
        self._create_bars_table(unique=True)
        with _capture_psycopg_warnings() as records:
            with self.assertRaises(loader.psycopg.Error):
                loader.insert_rows(self.conn, [self._stage_row(volume="lots")])
        self.assertEqual(_rollback_warnings(records), [])
        self._assert_connection_usable()
        self.assertEqual(
            self.conn.execute("SELECT count(*) FROM stock_minute_bars").fetchone()[0],
            0,
        )

    def test_failed_insert_does_not_break_rollback(self) -> None:
        # COPY succeeds. INSERT fails because ON CONFLICT has no unique index.
        self._create_bars_table(unique=False)
        with _capture_psycopg_warnings() as records:
            with self.assertRaises(loader.psycopg.Error):
                loader.insert_rows(self.conn, [self._stage_row()])
        self.assertEqual(_rollback_warnings(records), [])
        self._assert_connection_usable()
        self.assertEqual(
            self.conn.execute("SELECT count(*) FROM stock_minute_bars").fetchone()[0],
            0,
        )

    def test_copy_flush_failure_is_finished_before_rollback(self) -> None:
        """A COPY flush that never reaches PQputCopyEnd must not block ROLLBACK.

        psycopg buffers COPY rows and sends them from Copy.finish. If that
        send fails, finish returns before put_copy_end and the connection
        stays ACTIVE. transaction() would then log "another command is
        already in progress" while rolling back.
        """
        from psycopg._copy import LibpqWriter

        self._create_bars_table(unique=True)
        original = LibpqWriter.write

        def fail_flush(writer, data):
            raise loader.psycopg.OperationalError(
                "sending copy data failed: another command is already in progress"
            )

        LibpqWriter.write = fail_flush
        try:
            with _capture_psycopg_warnings() as records:
                with self.assertRaises(loader.psycopg.OperationalError):
                    loader.insert_rows(self.conn, [self._stage_row()])
        finally:
            LibpqWriter.write = original

        self.assertEqual(_rollback_warnings(records), [])
        self._assert_connection_usable()
        inserted = loader.insert_rows(self.conn, [self._stage_row()])
        self.assertEqual(inserted, 1)
        self._assert_connection_usable()

    def test_pipeline_mode_is_rejected_before_copy(self) -> None:
        self._create_bars_table(unique=True)
        with self.conn.pipeline():
            with self.assertRaises(RuntimeError):
                loader.insert_rows(self.conn, [self._stage_row()])
        self._assert_connection_usable()
        self.assertEqual(
            self.conn.execute("SELECT count(*) FROM stock_minute_bars").fetchone()[0],
            0,
        )

    def test_dedupe_helper_reads_its_result_before_the_next_command(self) -> None:
        self.conn.execute(
            """
            CREATE TABLE stock_minute_bars (
                symbol TEXT NOT NULL,
                ts TIMESTAMP NOT NULL,
                open DOUBLE PRECISION NOT NULL,
                high DOUBLE PRECISION NOT NULL,
                low DOUBLE PRECISION NOT NULL,
                close DOUBLE PRECISION NOT NULL,
                volume BIGINT NOT NULL,
                trade_count BIGINT,
                vwap DOUBLE PRECISION
            )
            """
        )
        self.conn.execute(
            """
            INSERT INTO stock_minute_bars
            VALUES
                ('AAPL', '2024-01-02 14:30:00', 1, 1, 1, 1, 10, 1, 1),
                ('AAPL', '2024-01-02 14:30:00', 9, 9, 9, 9, 99, 9, 9)
            """
        )
        self.assertEqual(loader.delete_duplicate_rows(self.conn), 1)
        self.assertEqual(
            self.conn.execute("SELECT count(*) FROM stock_minute_bars").fetchone()[0],
            1,
        )
        self._assert_connection_usable()


if __name__ == "__main__":
    unittest.main()
