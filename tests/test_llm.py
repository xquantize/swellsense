"""The LLM client returns the message when a caller needs tool calls."""

from types import SimpleNamespace

import pytest

from swellsense.llm import chat, complete_message, embed


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


def _embed_settings(*, batch_size: int = 32, dimensions: int = 768):
    return SimpleNamespace(
        embedding_model="nomic-embed-text",
        embedding_dimensions=dimensions,
        embedding_batch_size=batch_size,
    )


def _vector(dimensions: int, seed: float) -> list[float]:
    return [seed + i * 0.001 for i in range(dimensions)]


def _install_embed(monkeypatch, *, batch_size: int = 32, dimensions: int = 768):
    create_calls: list[dict] = []

    def create(**kwargs):
        create_calls.append(kwargs)
        prefixed: list[str] = kwargs["input"]
        data = [
            SimpleNamespace(
                index=i,
                embedding=_vector(dimensions, float(len(create_calls)) + i * 0.1),
            )
            for i in range(len(prefixed))
        ]
        return SimpleNamespace(data=data)

    client = SimpleNamespace(embeddings=SimpleNamespace(create=create))
    monkeypatch.setattr("swellsense.llm.embeddings.get_client", lambda: client)
    monkeypatch.setattr(
        "swellsense.llm.embeddings.get_settings",
        lambda: _embed_settings(batch_size=batch_size, dimensions=dimensions),
    )
    return create_calls


def test_embed_empty_returns_without_api_call(monkeypatch):
    create_calls = _install_embed(monkeypatch)

    assert embed([], "document") == []
    assert create_calls == []


def test_embed_applies_document_prefix(monkeypatch):
    create_calls = _install_embed(monkeypatch)

    embed(["alpha", "beta"], "document")

    assert len(create_calls) == 1
    assert create_calls[0]["model"] == "nomic-embed-text"
    assert create_calls[0]["input"] == [
        "search_document: alpha",
        "search_document: beta",
    ]
    assert "dimensions" not in create_calls[0]


def test_embed_applies_query_prefix(monkeypatch):
    create_calls = _install_embed(monkeypatch)

    embed(["where to surf"], "query")

    assert create_calls[0]["input"] == ["search_query: where to surf"]


def test_embed_batches_across_multiple_create_calls(monkeypatch):
    create_calls = _install_embed(monkeypatch, batch_size=2)

    texts = ["a", "b", "c", "d", "e"]
    result = embed(texts, "document")

    assert len(create_calls) == 3
    assert [len(c["input"]) for c in create_calls] == [2, 2, 1]
    assert len(result) == 5


def test_embed_preserves_order_when_batch_indexes_shuffled(monkeypatch):
    dimensions = 768
    create_calls: list[dict] = []

    def create(**kwargs):
        create_calls.append(kwargs)
        # Return indexes out of order; embed() must sort by index.
        data = [
            SimpleNamespace(index=1, embedding=_vector(dimensions, 1.0)),
            SimpleNamespace(index=0, embedding=_vector(dimensions, 0.0)),
        ]
        return SimpleNamespace(data=data)

    client = SimpleNamespace(embeddings=SimpleNamespace(create=create))
    monkeypatch.setattr("swellsense.llm.embeddings.get_client", lambda: client)
    monkeypatch.setattr(
        "swellsense.llm.embeddings.get_settings",
        lambda: _embed_settings(batch_size=32, dimensions=dimensions),
    )

    result = embed(["first", "second"], "document")

    assert result[0][0] == pytest.approx(0.0)
    assert result[1][0] == pytest.approx(1.0)


def test_embed_raises_on_dimension_mismatch(monkeypatch):
    _install_embed(monkeypatch, dimensions=768)

    def create(**kwargs):
        return SimpleNamespace(data=[SimpleNamespace(index=0, embedding=[0.0] * 4)])

    client = SimpleNamespace(embeddings=SimpleNamespace(create=create))
    monkeypatch.setattr("swellsense.llm.embeddings.get_client", lambda: client)

    with pytest.raises(ValueError, match="4 != expected 768"):
        embed(["x"], "document")
