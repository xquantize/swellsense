"""Terminal chat.

Conditions questions go through the tool loop. The model chooses a tool and
phrases the JSON. The score itself is computed in the conditions code.
"""

import json
import logging
from collections.abc import Callable

from swellsense.chat.tools import TOOLS, dispatch
from swellsense.llm import complete_message

# A model that keeps calling tools has to stop. Five rounds is enough for
# list_spots, then a check or a ranking, then an answer.
MAX_TOOL_ROUNDS = 5

LIMIT_MESSAGE = "I couldn't finish the conditions check. Try asking in a shorter way."

SYSTEM = """You are SwellSense, a friendly and knowledgeable surf coach based in New Zealand.
You help with surfboards, how swell, wind and tides shape waves, technique, safety and etiquette.
Keep answers practical and conversational, like a mate who surfs a lot. No emojis.
Units are metres for wave height, knots for wind, and seconds for the swell period.

Live conditions, such as whether a spot is worth surfing or where to go, come only from the tools.
You choose the tool. The score, the time window and the ranking are already decided in the result.
Do not invent heights, periods, wind, scores or times, and do not recompute them.

- Call list_spots to turn a name such as "the Mount" or "Papamoa" into a spot id.
- Call check_spot for one spot, and rank_spots when the question is where to go.
- Pass skill to rank_spots when the surfer has said their level.
- When two spots share a rank, say they are tied.
- If a tool returns an error, including a time window that has already passed, say that plainly. Do not quietly switch the question to tomorrow.
- Mention the swell size and period honestly, including a short-period windswell. Give the score and the main reasons from the tool.
- Mention hazards and the spot's minimum skill when the tool includes them. If the spot is above the surfer's stated level, or the tool lists it as above your level, warn them and do not encourage them to go.
- Mention uncertainties briefly, such as an unverified profile or a conflicting tide.
- Say what you cannot know from the tools, such as the sandbank shape and how crowded it is.
- If best_hour is "no surfable hours", say it is flat or not surfable, and do not name a best time.
- If best_hour is "no forecast hours", say the forecast does not cover that window.
- End every conditions answer with a short data credit for Open-Meteo and LINZ.

If a question is not about live conditions, answer from general surf knowledge and say when you are unsure."""


def run_turn(
    messages: list[dict],
    *,
    complete: Callable[..., object] = complete_message,
    dispatch_tool: Callable[..., str] = dispatch,
) -> str:
    """Answer one turn, calling tools until the model writes text.

    ``messages`` gains the assistant turn and any tool results. After five
    rounds that still call a tool, stop with a fixed sentence.
    """
    for _ in range(MAX_TOOL_ROUNDS):
        message = complete(messages, tools=TOOLS)
        calls = _tool_calls(message)
        if not calls:
            text = getattr(message, "content", None) or ""
            messages.append({"role": "assistant", "content": text})
            return text
        messages.append(_assistant_message(message, calls))
        for call_id, name, arguments in calls:
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": call_id,
                    "content": dispatch_tool(name, arguments),
                }
            )
    messages.append({"role": "assistant", "content": LIMIT_MESSAGE})
    return LIMIT_MESSAGE


def _tool_calls(message: object) -> list[tuple[str, str, object]]:
    raw = getattr(message, "tool_calls", None)
    if not raw:
        return []
    calls: list[tuple[str, str, object]] = []
    for index, call in enumerate(raw):
        if isinstance(call, dict):
            function = call.get("function") or {}
            call_id = call.get("id") or f"call-{index}"
            name = function.get("name") or ""
            arguments = function.get("arguments")
        else:
            function = call.function
            call_id = getattr(call, "id", None) or f"call-{index}"
            name = function.name
            arguments = function.arguments
        calls.append((str(call_id), str(name), arguments))
    return calls


def _assistant_message(message: object, calls: list[tuple[str, str, object]]) -> dict:
    payload: dict = {
        "role": "assistant",
        "content": getattr(message, "content", None) or "",
        "tool_calls": [
            {
                "id": call_id,
                "type": "function",
                "function": {
                    "name": name,
                    "arguments": _arguments_text(arguments),
                },
            }
            for call_id, name, arguments in calls
        ],
    }
    return payload


def _arguments_text(arguments: object) -> str:
    if isinstance(arguments, str):
        return arguments
    return json.dumps(arguments if arguments is not None else {})


def main() -> None:
    logging.basicConfig(level="WARNING")
    messages = [{"role": "system", "content": SYSTEM}]
    print("SwellSense: ask me anything about surfing (Ctrl+C to quit)\n")

    while True:
        try:
            question = input("you: ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\nCatch you in the water.")
            break
        if not question:
            continue

        messages.append({"role": "user", "content": question})
        answer = run_turn(messages)
        print(f"\nswellsense: {answer}\n")


if __name__ == "__main__":
    main()
