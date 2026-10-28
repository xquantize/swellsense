"""Postgres connection and idempotent schema setup for chunk storage."""

from __future__ import annotations

import re
from pathlib import Path

import psycopg
from pgvector.psycopg import register_vector

from swellsense.config import get_settings

_SCHEMA_PATH = Path(__file__).with_name("schema.sql")
_VECTOR_DIM_RE = re.compile(r"^vector\((\d+)\)$")


def connect() -> psycopg.Connection:
    """Open a Psycopg 3 connection with pgvector types registered."""
    conn = psycopg.connect(get_settings().database_url.get_secret_value())
    try:
        register_vector(conn)
    except psycopg.ProgrammingError as exc:
        # Fresh databases have no vector type until init_schema runs CREATE EXTENSION.
        if "vector type not found" not in str(exc):
            raise
    return conn


def init_schema(conn: psycopg.Connection) -> None:
    """Apply schema.sql and verify the embedding column matches settings."""
    sql = _SCHEMA_PATH.read_text(encoding="utf-8")
    for statement in _split_sql_statements(sql):
        conn.execute(statement)
    _check_embedding_dimension(conn)
    register_vector(conn)


def _split_sql_statements(sql: str) -> list[str]:
    """Split SQL into statements for Psycopg's extended query protocol."""
    statements: list[str] = []
    for part in sql.split(";"):
        statement = part.strip()
        if statement:
            statements.append(statement)
    return statements


def _check_embedding_dimension(conn: psycopg.Connection) -> None:
    expected = get_settings().embedding_dimensions
    row = conn.execute(
        """
        SELECT format_type(a.atttypid, a.atttypmod)
        FROM pg_attribute AS a
        JOIN pg_class AS c ON c.oid = a.attrelid
        JOIN pg_namespace AS n ON n.oid = c.relnamespace
        WHERE n.nspname = 'public'
          AND c.relname = 'chunks'
          AND a.attname = 'embedding'
          AND a.attnum > 0
          AND NOT a.attisdropped
        """
    ).fetchone()
    if row is None:
        msg = "chunks.embedding column not found after schema init"
        raise ValueError(msg)
    actual = _parse_vector_dimension(row[0])
    if actual != expected:
        msg = (
            f"chunks.embedding dimension is {actual}, expected {expected} "
            f"(embedding_dimensions setting)"
        )
        raise ValueError(msg)


def _parse_vector_dimension(pg_type: str) -> int:
    match = _VECTOR_DIM_RE.match(pg_type.strip())
    if match is None:
        msg = f"chunks.embedding has unexpected type {pg_type!r}"
        raise ValueError(msg)
    return int(match.group(1))
