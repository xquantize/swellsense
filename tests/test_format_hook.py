"""Tests for the afterFileEdit Python formatter. Subprocess is mocked: no real ruff."""

import importlib.util
import json
from io import StringIO
from pathlib import Path
from unittest.mock import patch

HOOK_PATH = (
    Path(__file__).resolve().parents[1] / ".cursor" / "hooks" / "format_python.py"
)


def _load_hook():
    spec = importlib.util.spec_from_file_location("format_python_hook", HOOK_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load hook at {HOOK_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


hook = _load_hook()


def test_read_file_path_from_hook_json():
    raw = json.dumps({"file_path": "src/swellsense/chatbot.py", "edits": []})
    assert hook.read_file_path(raw) == "src/swellsense/chatbot.py"


def test_read_file_path_rejects_unusable_payloads():
    assert hook.read_file_path("") is None
    assert hook.read_file_path("not json") is None
    assert hook.read_file_path("[]") is None
    assert hook.read_file_path("null") is None
    assert hook.read_file_path(json.dumps({})) is None
    assert hook.read_file_path(json.dumps({"file_path": 3})) is None
    assert hook.read_file_path(json.dumps({"file_path": None})) is None


def test_main_formats_only_python_files():
    python_payload = json.dumps({"file_path": "src/swellsense/chatbot.py"})
    with patch.object(hook.subprocess, "run") as run:
        code = hook.main(StringIO(python_payload))

    assert code == 0
    assert run.call_count == 2
    check, format_ = run.call_args_list
    assert check.args[0] == [
        "uv",
        "run",
        "ruff",
        "check",
        "--fix",
        "--quiet",
        "src/swellsense/chatbot.py",
    ]
    assert check.kwargs["check"] is False
    assert format_.args[0] == [
        "uv",
        "run",
        "ruff",
        "format",
        "--quiet",
        "src/swellsense/chatbot.py",
    ]
    assert format_.kwargs["check"] is False


def test_main_ignores_non_python_files():
    for path in ("README.md", "data/sources.yaml", "notes.py.txt", "script.pyx"):
        with patch.object(hook.subprocess, "run") as run:
            code = hook.main(StringIO(json.dumps({"file_path": path})))
        assert code == 0
        run.assert_not_called()


def test_main_exits_zero_when_ruff_cannot_start():
    payload = json.dumps({"file_path": "src/swellsense/chatbot.py"})
    with patch.object(hook.subprocess, "run", side_effect=OSError("uv missing")):
        code = hook.main(StringIO(payload))
    assert code == 0


def test_main_exits_zero_on_bad_stdin():
    with patch.object(hook.subprocess, "run") as run:
        code = hook.main(StringIO("{"))
    assert code == 0
    run.assert_not_called()
