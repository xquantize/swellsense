"""Schema SQL checks and optional Postgres integration tests."""

from __future__ import annotations

from pathlib import Path

import psycopg
import pytest
from pgvector import Vector

from swellsense.cli import main
from swellsense.db.connection import init_schema

SCHEMA_PATH = Path(__file__).resolve().parents[1] / "src/swellsense/db/schema.sql"


def test_schema_sql_defines_tables_extension_and_index() -> None:
    sql = SCHEMA_PATH.read_text(encoding="utf-8")
    assert "CREATE EXTENSION IF NOT EXISTS vector" in sql
    assert "IF NOT EXISTS" in sql
    assert "documents" in sql
    assert "chunks" in sql
    assert "vector(768)" in sql
    assert "chunks_embedding_hnsw" in sql
    assert "vector_cosine_ops" in sql


def test_db_init_commits_before_close(capsys, monkeypatch) -> None:
    calls: list[str] = []

    class FakeConn:
        def commit(self) -> None:
            calls.append("commit")

        def close(self) -> None:
            calls.append("close")

    fake = FakeConn()

    def fake_connect():
        return fake

    def fake_init_schema(conn) -> None:
        assert conn is fake

    monkeypatch.setattr("swellsense.cli.connect", fake_connect)
    monkeypatch.setattr("swellsense.cli.init_schema", fake_init_schema)

    with pytest.raises(SystemExit) as caught:
        main(["db", "init"])

    assert caught.value.code == 0
    assert calls == ["commit", "close"]
    out = capsys.readouterr().out.strip()
    assert out == "database schema initialized"


def test_db_init_connection_failure_exits_1(capsys, monkeypatch) -> None:
    def fail_connect():
        raise psycopg.OperationalError("connection refused")

    monkeypatch.setattr("swellsense.cli.connect", fail_connect)

    with pytest.raises(SystemExit) as caught:
        main(["db", "init"])

    assert caught.value.code == 1
    err = capsys.readouterr().err.strip()
    assert err
    assert "\n" not in err


@pytest.mark.db
def test_db_init_persists_schema_on_new_connection(capsys) -> None:
    from swellsense.config import get_settings

    with pytest.raises(SystemExit) as caught:
        main(["db", "init"])
    assert caught.value.code == 0
    assert "database schema initialized" in capsys.readouterr().out

    conn = psycopg.connect(get_settings().database_url.get_secret_value())
    try:
        chunks = conn.execute("SELECT to_regclass('public.chunks')").fetchone()[0]
        documents = conn.execute("SELECT to_regclass('public.documents')").fetchone()[0]
        assert chunks == "chunks"
        assert documents == "documents"
    finally:
        conn.close()


@pytest.mark.db
def test_init_schema_is_idempotent_and_vector_round_trips() -> None:
    from swellsense.config import get_settings

    url = get_settings().database_url.get_secret_value()
    conn = psycopg.connect(url)
    try:
        init_schema(conn)
        init_schema(conn)
    finally:
        conn.close()

    conn = psycopg.connect(url)
    try:
        embedding = Vector([float(i) for i in range(768)])
        conn.execute("BEGIN")
        try:
            conn.execute(
                """
                INSERT INTO documents (
                    id, source_id, title, url, license, attribution, usage
                ) VALUES (%s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    "doc-test",
                    "wikipedia",
                    "Test",
                    "https://example.test/doc",
                    "CC BY-SA 4.0",
                    "Example attribution",
                    "open",
                ),
            )
            conn.execute(
                """
                INSERT INTO chunks (
                    id, document_id, "index", section, text, word_count,
                    content_hash, title, url, license, attribution, usage,
                    embedding, embedding_model
                ) VALUES (
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                )
                """,
                (
                    "doc-test#0",
                    "doc-test",
                    0,
                    "Intro",
                    "hello",
                    1,
                    "abc123",
                    "Test",
                    "https://example.test/doc",
                    "CC BY-SA 4.0",
                    "Example attribution",
                    "open",
                    embedding,
                    "nomic-embed-text",
                ),
            )
            row = conn.execute(
                "SELECT embedding FROM chunks WHERE id = %s",
                ("doc-test#0",),
            ).fetchone()
            assert row is not None
            assert row[0] == embedding
        finally:
            conn.execute("ROLLBACK")
    finally:
        conn.close()
