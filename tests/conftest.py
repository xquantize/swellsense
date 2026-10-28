"""Shared pytest configuration."""

import os

import pytest

from swellsense.config import get_settings


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers",
        "db: integration test requiring Postgres (set DATABASE_URL)",
    )


def pytest_collection_modifyitems(
    config: pytest.Config, items: list[pytest.Item]
) -> None:
    if os.environ.get("DATABASE_URL"):
        return
    skip_db = pytest.mark.skip(reason="DATABASE_URL not set")
    for item in items:
        if item.get_closest_marker("db") is not None:
            item.add_marker(skip_db)


@pytest.fixture
def clear_settings_cache():
    """Clear cached settings after tests that patch environment or settings."""
    yield
    get_settings.cache_clear()
