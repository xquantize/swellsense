"""The tool loop, with a fake model. No network."""

import copy
import json
from types import SimpleNamespace

from swellsense.chat.tools import TOOLS
from swellsense.chatbot import (
    CREDIT_LINE,
    LIMIT_MESSAGE,
    MAX_TOOL_ROUNDS,
    SYSTEM,
    run_turn,
)


def _call(name: str, arguments: str, call_id: str = "call-1"):
    return SimpleNamespace(
        id=call_id,
        type="function",
        function=SimpleNamespace(name=name, arguments=arguments),
    )


def _message(content: str | None = None, tool_calls=None):
    return SimpleNamespace(content=content, tool_calls=tool_calls)


def test_system_prompt_keeps_conditions_answers_honest():
    # The model phrases the tool JSON. These lines are what stop it inventing
    # a session when the code has already decided the surf.
    for phrase in (
        "the morning's gone",
        "Never say a tool name",
        "passed_note",
        "Open-Meteo",
        "LINZ",
        "only when the answer used forecast or tide data",
        "above your level",
        "sandbank",
        "windswell",
        "tied",
    ):
        assert phrase in SYSTEM


def test_tool_loop_calls_a_tool_then_answers():
    seen: list[list[dict]] = []

    def complete(messages, **kwargs):
        seen.append(copy.deepcopy(messages))
        names = [tool["function"]["name"] for tool in kwargs["tools"]]
        assert names == [tool["function"]["name"] for tool in TOOLS]
        if len(seen) == 1:
            return _message(tool_calls=[_call("list_spots", "{}")])
        return _message(content="Papamoa is a 6 this morning, short-period windswell.")

    def dispatch_tool(name, arguments):
        assert name == "list_spots"
        assert arguments == "{}"
        return '{"spots": []}'

    messages = [{"role": "user", "content": "where should I go this morning?"}]
    text = run_turn(messages, complete=complete, dispatch_tool=dispatch_tool)

    assert text == "Papamoa is a 6 this morning, short-period windswell."
    assert seen[1][-2]["tool_calls"][0]["function"]["name"] == "list_spots"
    assert seen[1][-1] == {
        "role": "tool",
        "tool_call_id": "call-1",
        "content": '{"spots": []}',
    }
    assert messages[-1] == {"role": "assistant", "content": text}
    assert len(seen) == 2


def test_tool_loop_stops_after_five_rounds():
    calls = {"n": 0}

    def complete(messages, **kwargs):
        calls["n"] += 1
        return _message(
            tool_calls=[_call("list_spots", "{}", call_id=f"call-{calls['n']}")]
        )

    dispatched = {"n": 0}

    def dispatch_tool(name, arguments):
        dispatched["n"] += 1
        return "{}"

    text = run_turn(
        [{"role": "user", "content": "where?"}],
        complete=complete,
        dispatch_tool=dispatch_tool,
    )

    assert calls["n"] == MAX_TOOL_ROUNDS == 5
    assert dispatched["n"] == 5
    assert text == LIMIT_MESSAGE


def test_passed_window_is_answered_in_ordinary_words():
    """A fake model asks for the morning after it has passed, then phrases the note."""
    from datetime import datetime

    from test_chat_tools import _deps, _forecast, _hour

    from swellsense.chat.tools import dispatch
    from swellsense.forecast.models import AUCKLAND

    now = datetime(2026, 1, 15, 14, 10, tzinfo=AUCKLAND)
    deps = _deps(
        forecast=lambda spot, count: _forecast(
            spot.id, _hour(datetime(2026, 1, 15, 15, 0, tzinfo=AUCKLAND))
        )
    )

    def complete(messages, **kwargs):
        if not any(message.get("role") == "tool" for message in messages):
            return _message(
                tool_calls=[
                    _call(
                        "check_spot",
                        '{"spot_id": "example", "when": "this_morning"}',
                    )
                ]
            )
        payload = json.loads(messages[-1]["content"])
        assert payload["checked"] == "the rest of today"
        assert "this_morning" not in messages[-1]["content"]
        return _message(content=f"{payload['passed_note']} The rest of the day is a 6.")

    text = run_turn(
        [{"role": "user", "content": "Is it worth surfing this morning?"}],
        complete=complete,
        dispatch_tool=lambda name, arguments: dispatch(
            name, arguments, deps=deps, now=now
        ),
    )

    assert "The morning's gone." in text
    assert "the rest of today" in text.casefold()
    assert "this_morning" not in text
    assert text.endswith(CREDIT_LINE)


def test_evening_request_moves_on_to_tomorrow_morning():
    from datetime import datetime

    from test_chat_tools import _deps, _forecast, _hour

    from swellsense.chat.tools import dispatch
    from swellsense.forecast.models import AUCKLAND

    now = datetime(2026, 1, 15, 19, 0, tzinfo=AUCKLAND)
    deps = _deps(
        forecast=lambda spot, count: _forecast(
            spot.id, _hour(datetime(2026, 1, 16, 8, 0, tzinfo=AUCKLAND))
        )
    )

    def complete(messages, **kwargs):
        if not any(message.get("role") == "tool" for message in messages):
            return _message(
                tool_calls=[
                    _call(
                        "check_spot",
                        '{"spot_id": "example", "when": "this_afternoon"}',
                    )
                ]
            )
        payload = json.loads(messages[-1]["content"])
        return _message(content=payload["passed_note"])

    text = run_turn(
        [{"role": "user", "content": "How is this afternoon?"}],
        complete=complete,
        dispatch_tool=lambda name, arguments: dispatch(
            name, arguments, deps=deps, now=now
        ),
    )

    assert text.startswith("The afternoon's gone. Here's tomorrow morning.")
    assert "this_afternoon" not in text
    assert "tomorrow_morning" not in text
    assert text.endswith(CREDIT_LINE)


def test_credit_is_left_off_when_no_forecast_was_used():
    def complete(messages, **kwargs):
        return _message(content=f"A fish is the board.\n{CREDIT_LINE}")

    text = run_turn(
        [{"role": "user", "content": "What board should I ride?"}],
        complete=complete,
    )

    assert text == "A fish is the board."
    assert "Open-Meteo" not in text
    assert "LINZ" not in text


def test_credit_is_added_when_the_forecast_was_used():
    def complete(messages, **kwargs):
        if not any(message.get("role") == "tool" for message in messages):
            return _message(
                tool_calls=[
                    _call("check_spot", '{"spot_id": "example", "when": "now"}')
                ]
            )
        return _message(content="It's a 6, 1.2 m at 7 s, windswell.")

    def dispatch_tool(name, arguments):
        assert name == "check_spot"
        return '{"best_hour": {"score": 6}, "attributions": ["Open-Meteo", "LINZ"]}'

    text = run_turn(
        [{"role": "user", "content": "Is it worth it?"}],
        complete=complete,
        dispatch_tool=dispatch_tool,
    )

    assert text == f"It's a 6, 1.2 m at 7 s, windswell.\n{CREDIT_LINE}"
