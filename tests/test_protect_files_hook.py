"""Tests for the beforeReadFile protection hook. No network."""

import importlib.util
import json
from io import StringIO
from pathlib import Path
from unittest.mock import patch

import pytest

HOOK_PATH = (
    Path(__file__).resolve().parents[1] / ".cursor" / "hooks" / "protect_files.py"
)


def _load_hook():
    spec = importlib.util.spec_from_file_location("protect_files_hook", HOOK_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load hook at {HOOK_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


hook = _load_hook()


def _run(raw: str, capsys: pytest.CaptureFixture[str]) -> tuple[int, dict]:
    code = hook.main(StringIO(raw))
    captured = capsys.readouterr()
    return code, json.loads(captured.out)


@pytest.mark.parametrize(
    "path",
    [
        ".env",
        ".env.local",
        "config/.env",
        "/workspace/.env",
        "/workspace/app/.env.production",
        "subdir/../.env",
    ],
)
def test_env_files_are_denied(path: str, capsys: pytest.CaptureFixture[str]) -> None:
    code, body = _run(json.dumps({"file_path": path, "content": "KEY=value"}), capsys)

    assert code == 0
    assert body == {"permission": "deny", "user_message": hook.ENV_DENY_MESSAGE}


@pytest.mark.parametrize(
    "path",
    [".ENV", ".Env.local", "/workspace/app/.ENV.production"],
)
def test_env_match_is_case_insensitive(
    path: str, capsys: pytest.CaptureFixture[str]
) -> None:
    code, body = _run(json.dumps({"file_path": path}), capsys)

    assert code == 0
    assert body == {"permission": "deny", "user_message": hook.ENV_DENY_MESSAGE}


@pytest.mark.parametrize("path", [".ENV.example", "/workspace/.Env.Example"])
def test_env_example_match_is_case_insensitive(
    path: str, capsys: pytest.CaptureFixture[str]
) -> None:
    code, body = _run(json.dumps({"file_path": path}), capsys)

    assert code == 0
    assert body == {"permission": "allow"}


def test_env_example_is_allowed(capsys: pytest.CaptureFixture[str]) -> None:
    payload = json.dumps({"file_path": ".env.example", "content": "KEY="})
    code, body = _run(payload, capsys)

    assert code == 0
    assert body == {"permission": "allow"}


def test_absolute_env_example_is_allowed(capsys: pytest.CaptureFixture[str]) -> None:
    payload = json.dumps({"file_path": "/workspace/.env.example"})
    code, body = _run(payload, capsys)

    assert code == 0
    assert body == {"permission": "allow"}


@pytest.mark.parametrize(
    "path",
    ["DATA/RAW/wikipedia/x.json", "Data/Raw/page.json"],
)
def test_data_raw_match_is_case_insensitive(
    path: str, capsys: pytest.CaptureFixture[str]
) -> None:
    code, body = _run(json.dumps({"file_path": path}), capsys)

    assert code == 0
    assert body == {"permission": "deny", "user_message": hook.RAW_DENY_MESSAGE}


def test_data_raw_is_denied(capsys: pytest.CaptureFixture[str]) -> None:
    payload = json.dumps({"file_path": "data/raw/wikipedia/x.json"})
    code, body = _run(payload, capsys)

    assert code == 0
    assert body == {"permission": "deny", "user_message": hook.RAW_DENY_MESSAGE}


@pytest.mark.parametrize(
    "path",
    [
        "/workspace/data/raw/wikipedia/x.json",
        "data\\raw\\wikipedia\\x.json",
    ],
)
def test_absolute_and_windows_data_raw_are_denied(
    path: str, capsys: pytest.CaptureFixture[str]
) -> None:
    code, body = _run(json.dumps({"file_path": path}), capsys)

    assert code == 0
    assert body == {"permission": "deny", "user_message": hook.RAW_DENY_MESSAGE}


@pytest.mark.parametrize(
    "path",
    [
        "src/swellsense/llm/client.py",
        "/workspace/src/swellsense/llm/client.py",
        "data/sources.yaml",
        "data/rawfile.txt",
        "notdata/raw/x.json",
    ],
)
def test_ordinary_files_are_allowed(
    path: str, capsys: pytest.CaptureFixture[str]
) -> None:
    code, body = _run(json.dumps({"file_path": path}), capsys)

    assert code == 0
    assert body == {"permission": "allow"}


def test_symlink_into_data_raw_is_denied(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    target_dir = tmp_path / "data" / "raw" / "wikipedia"
    target_dir.mkdir(parents=True)
    target = target_dir / "x.json"
    target.write_text("{}", encoding="utf-8")
    link = tmp_path / "notes.json"
    link.symlink_to(target)

    code, body = _run(json.dumps({"file_path": str(link)}), capsys)

    assert code == 0
    assert body == {"permission": "deny", "user_message": hook.RAW_DENY_MESSAGE}


def test_symlink_out_of_data_raw_is_allowed(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    outside = tmp_path / "sources.yaml"
    outside.write_text("ok", encoding="utf-8")
    raw = tmp_path / "data" / "raw"
    raw.mkdir(parents=True)
    link = raw / "sources.yaml"
    link.symlink_to(outside)

    code, body = _run(json.dumps({"file_path": str(link)}), capsys)

    assert code == 0
    assert body == {"permission": "allow"}


def test_env_example_inside_data_raw_is_denied(
    capsys: pytest.CaptureFixture[str],
) -> None:
    payload = json.dumps({"file_path": "data/raw/.env.example"})
    code, body = _run(payload, capsys)

    assert code == 0
    assert body["permission"] == "deny"


def test_path_tricks_do_not_hide_raw_or_escape_it(
    capsys: pytest.CaptureFixture[str],
) -> None:
    denied = _run(json.dumps({"file_path": "data/./raw/wikipedia/x.json"}), capsys)
    assert denied[0] == 0
    assert denied[1]["permission"] == "deny"

    allowed = _run(json.dumps({"file_path": "data/raw/../sources.yaml"}), capsys)
    assert allowed[0] == 0
    assert allowed[1] == {"permission": "allow"}


def test_bad_json_is_denied(capsys: pytest.CaptureFixture[str]) -> None:
    code, body = _run("{", capsys)

    assert code == 0
    assert body == {"permission": "deny", "user_message": hook.UNUSABLE_MESSAGE}


@pytest.mark.parametrize(
    "raw",
    [
        "",
        "not json",
        "[]",
        "null",
        "{}",
        json.dumps({"file_path": 3}),
        json.dumps({"file_path": "  "}),
    ],
)
def test_unusable_input_is_denied(raw: str, capsys: pytest.CaptureFixture[str]) -> None:
    code, body = _run(raw, capsys)

    assert code == 0
    assert body == {"permission": "deny", "user_message": hook.UNUSABLE_MESSAGE}


def test_main_denies_when_the_check_raises(capsys: pytest.CaptureFixture[str]) -> None:
    payload = json.dumps({"file_path": "src/swellsense/llm/client.py"})
    with patch.object(hook, "evaluate", side_effect=RuntimeError("boom")):
        code = hook.main(StringIO(payload))

    assert code == 0
    assert json.loads(capsys.readouterr().out) == {
        "permission": "deny",
        "user_message": hook.FAILED_MESSAGE,
    }
