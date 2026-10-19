"""The tool loop, with a fake model. No network."""

import copy
from types import SimpleNamespace

from swellsense.chat.tools import TOOLS
from swellsense.chatbot import LIMIT_MESSAGE, MAX_TOOL_ROUNDS, SYSTEM, run_turn


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
        "no surfable hours",
        "Open-Meteo",
        "LINZ",
        "above your level",
        "sandbank",
        "windswell",
        "already passed",
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
