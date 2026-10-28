"""OpenAI-compatible embeddings for chunk storage and retrieval."""

from typing import Literal

from swellsense.config import get_settings
from swellsense.llm.client import get_client

_PREFIX: dict[Literal["document", "query"], str] = {
    "document": "search_document: ",
    "query": "search_query: ",
}


def embed(texts: list[str], kind: Literal["document", "query"]) -> list[list[float]]:
    """Return embedding vectors for ``texts``.

    ``nomic-embed-text`` expects task prefixes on each input; we apply the
    document or query prefix before calling the API. Vector length is checked
    in code because Ollama does not accept OpenAI's ``dimensions`` parameter.
    """
    if not texts:
        return []

    settings = get_settings()
    client = get_client()
    prefix = _PREFIX[kind]
    batch_size = settings.embedding_batch_size
    expected = settings.embedding_dimensions
    out: list[list[float]] = []

    for start in range(0, len(texts), batch_size):
        batch = texts[start : start + batch_size]
        prefixed = [prefix + t for t in batch]
        response = client.embeddings.create(
            model=settings.embedding_model,
            input=prefixed,
        )
        items = sorted(response.data, key=lambda d: d.index)
        for item in items:
            vector = list(item.embedding)
            if len(vector) != expected:
                raise ValueError(
                    f"embedding length {len(vector)} != expected {expected}"
                )
            out.append(vector)

    return out
