"""Block reads of secrets and bulk raw downloads.

Runs from the beforeReadFile hook. Cursor sends an absolute path, so the
check looks at the file name and path components, not a fixed prefix. `.` and
`..` are collapsed in the path string only: the hook never touches the
filesystem. When the payload is unclear, deny.
"""

import json
import posixpath
import sys
from typing import TextIO

ENV_DENY_MESSAGE = "Reading .env files is blocked so secrets stay off the model."
RAW_DENY_MESSAGE = (
    "Reading files under data/raw/ is blocked so bulk downloads stay off the model."
)
UNUSABLE_MESSAGE = "Reading was blocked because the hook input had no usable file path."
FAILED_MESSAGE = "Reading was blocked because the file check failed."


def read_file_path(raw: str) -> str | None:
    """Return file_path from a hook payload, or None when the payload is unusable."""
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    path = payload.get("file_path")
    if not isinstance(path, str) or path.strip() == "":
        return None
    return path


def _normalized(path: str) -> str:
    """Collapse . and .. and accept Windows separators, without reading the disk."""
    return posixpath.normpath(path.replace("\\", "/"))


def _is_secret_env(path: str) -> bool:
    """True for .env and .env.* files, with .env.example left readable."""
    name = posixpath.basename(_normalized(path))
    if name == ".env":
        return True
    return name.startswith(".env.") and name != ".env.example"


def _is_under_data_raw(path: str) -> bool:
    """True when a data/raw directory contains this path.

    Matching components (not a substring) keeps data/rawfile readable, and
    still matches absolute paths such as /workspace/data/raw/page.json.
    """
    parts = _normalized(path).split("/")
    return any(
        parts[index] == "data" and parts[index + 1] == "raw"
        for index in range(len(parts) - 1)
    )


def _deny(user_message: str) -> dict[str, str]:
    return {"permission": "deny", "user_message": user_message}


def evaluate(raw: str) -> dict[str, str]:
    """Decide whether a beforeReadFile event may read the path."""
    path = read_file_path(raw)
    if path is None:
        return _deny(UNUSABLE_MESSAGE)
    if _is_secret_env(path):
        return _deny(ENV_DENY_MESSAGE)
    if _is_under_data_raw(path):
        return _deny(RAW_DENY_MESSAGE)
    return {"permission": "allow"}


def main(stdin: TextIO | None = None) -> int:
    """Read one hook event and print an allow or deny decision. Always returns 0."""
    try:
        stream = sys.stdin if stdin is None else stdin
        result = evaluate(stream.read())
    except Exception:  # noqa: BLE001 - a security hook must still print JSON
        result = _deny(FAILED_MESSAGE)
    print(json.dumps(result), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
