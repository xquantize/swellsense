"""Format a Python file after a Cursor agent edit.

Runs from the afterFileEdit hook. Every failure is swallowed so a formatting
problem can never block the agent.
"""

import json
import subprocess
import sys
from typing import TextIO


def read_file_path(raw: str) -> str | None:
    """Return file_path from a hook payload, or None when the payload is unusable."""
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    path = payload.get("file_path")
    if not isinstance(path, str):
        return None
    return path


def format_python(path: str) -> None:
    """Autofix, then format. Format runs second so it has the last word on layout."""
    subprocess.run(
        ["uv", "run", "ruff", "check", "--fix", "--quiet", path],
        check=False,
    )
    subprocess.run(
        ["uv", "run", "ruff", "format", "--quiet", path],
        check=False,
    )


def main(stdin: TextIO | None = None) -> int:
    """Read one hook event and format the file when it is Python. Always returns 0."""
    try:
        stream = sys.stdin if stdin is None else stdin
        path = read_file_path(stream.read())
        if path is not None and path.endswith(".py"):
            format_python(path)
    except Exception:  # noqa: BLE001 - a hook failure must never block the agent
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
