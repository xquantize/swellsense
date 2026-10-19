"""The LLM client returns the message when a caller needs tool calls."""

from types import SimpleNamespace

from swellsense.llm import chat, complete_message


def _install(monkeypatch, message, created):
    def create(**kwargs):
        created.update(kwargs)
        return SimpleNamespace(
            choices=[SimpleNamespace(message=message)],
            usage=SimpleNamespace(prompt_tokens=3, completion_tokens=1),
        )

    client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=create))
    )
    monkeypatch.setattr("swellsense.llm.client.get_client", lambda: client)
    monkeypatch.setattr(
        "swellsense.llm.client.get_settings",
        lambda: SimpleNamespace(llm_model="test-model", llm_reasoning_effort=None),
    )


def test_complete_message_returns_the_assistant_message(monkeypatch):
    message = SimpleNamespace(content=None, tool_calls=["call"])
    created: dict = {}
    _install(monkeypatch, message, created)

    result = complete_message(
        [{"role": "user", "content": "hi"}],
        tools=[{"type": "function"}],
    )

    assert result is message
    assert created["model"] == "test-model"
    assert created["tools"] == [{"type": "function"}]
    assert created["messages"] == [{"role": "user", "content": "hi"}]


def test_chat_returns_text(monkeypatch):
    message = SimpleNamespace(content="hello", tool_calls=None)
    created: dict = {}
    _install(monkeypatch, message, created)

    assert chat("hi", system="be brief") == "hello"
    assert created["messages"][0] == {"role": "system", "content": "be brief"}
    assert created["messages"][1] == {"role": "user", "content": "hi"}
