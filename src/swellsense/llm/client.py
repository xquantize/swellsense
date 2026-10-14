import logging
import time

from openai import OpenAI
from pydantic import BaseModel, ValidationError

from swellsense.config import get_settings

log = logging.getLogger(__name__)


def get_client() -> OpenAI:
    s = get_settings()
    return OpenAI(
        base_url=s.llm_base_url,
        api_key=s.llm_api_key.get_secret_value(),
        max_retries=3,
        timeout=120,
    )


def _complete(messages: list[dict], **kwargs) -> str:
    s = get_settings()
    if s.llm_reasoning_effort:
        kwargs["reasoning_effort"] = s.llm_reasoning_effort

    start = time.perf_counter()
    response = get_client().chat.completions.create(
        model=s.llm_model, messages=messages, **kwargs
    )
    elapsed = time.perf_counter() - start

    usage = response.usage
    log.info(
        "%s: %d in / %d out tokens, %.1fs (%.1f tok/s)",
        s.llm_model,
        usage.prompt_tokens,
        usage.completion_tokens,
        elapsed,
        usage.completion_tokens / elapsed,
    )
    return response.choices[0].message.content


def chat(prompt: str, system: str | None = None) -> str:
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})
    return _complete(messages)


def respond(messages: list[dict]) -> str:
    """Continue a conversation, given the full message history."""
    return _complete(messages)


def extract[T: BaseModel](
    text: str, schema: type[T], instructions: str, max_attempts: int = 3
) -> T:
    messages = [
        {"role": "system", "content": instructions},
        {"role": "user", "content": text},
    ]
    response_format = {
        "type": "json_schema",
        "json_schema": {"name": schema.__name__, "schema": schema.model_json_schema()},
    }

    for attempt in range(1, max_attempts + 1):
        content = _complete(messages, response_format=response_format)
        try:
            return schema.model_validate_json(content)
        except ValidationError as err:
            log.warning(
                "Attempt %d/%d failed validation: %s", attempt, max_attempts, err
            )
            messages += [
                {"role": "assistant", "content": content},
                {
                    "role": "user",
                    "content": f"That output failed validation:\n{err}\n"
                    "Fix the errors and return the corrected JSON.",
                },
            ]

    raise ValueError(f"No valid {schema.__name__} after {max_attempts} attempts")
