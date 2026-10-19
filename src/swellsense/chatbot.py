"""Terminal chat.

Conditions questions go through the tool loop. The model chooses a tool and
phrases the JSON. The score itself is computed in the conditions code.
"""

import json
import logging
from collections.abc import Callable

from swellsense.chat.tools import DATA_CREDIT, TOOLS, dispatch
from swellsense.llm import complete_message

# A model that keeps calling tools has to stop. Five rounds is enough for
# list_spots, then a check or a ranking, then an answer.
MAX_TOOL_ROUNDS = 5

LIMIT_MESSAGE = "I couldn't finish the conditions check. Try asking in a shorter way."

# Added to the reply only after a tool actually returned forecast or tide data.
CREDIT_LINE = f"Data: {DATA_CREDIT}."

SYSTEM = """You are SwellSense, a friendly and knowledgeable surf coach based in New Zealand.
You help with surfboards, how swell, wind and tides shape waves, technique, safety and etiquette.
Keep answers practical and conversational, like a mate who surfs a lot. No emojis.
Units are metres for wave height, knots for wind, and seconds for the swell period.

Live conditions, such as whether a spot is worth surfing or where to go, come only from the tools.
You choose the tool. The score, the time window and the ranking are already decided in the result.
Do not invent heights, periods, wind, scores or times, and do not recompute them.

Speak to the surfer in ordinary words. Never say a tool name or a parameter name.
Say "the morning's gone", not the token you passed in for the window.

- Call list_spots to turn a name such as "the Mount" or "Papamoa" into a spot id.
- Call check_spot for one spot, and rank_spots when the question is where to go.
- Pass skill to rank_spots when the surfer has said their level.
- When two spots share a rank, say they are tied.
- If the result has a passed_note, say that the part of the day they asked about has gone, then answer from the window that was checked. The numbers belong to that later window.
- If a tool returns an error, say that plainly.
- Mention the swell size and period honestly, including a short-period windswell. Give the score and the main reasons from the tool.
- Mention hazards and the spot's minimum skill when the tool includes them. If the spot is above the surfer's stated level, or the tool lists it as above your level, warn them and do not encourage them to go.
- Mention uncertainties briefly, such as an unverified profile or a conflicting tide.
- Say what you cannot know from the tools, such as the sandbank shape and how crowded it is.
- If there are no surfable hours, say it is flat or not surfable, and do not name a best time.
- If there are no forecast hours, say the forecast does not cover that window.
- Do not write a data credit yourself. A short Open-Meteo and LINZ credit is added for you only when the answer used forecast or tide data.

If a question is not about live conditions, answer from general surf knowledge and say when you are unsure."""


def run_turn(
    messages: list[dict],
    *,
    complete: Callable[..., object] = complete_message,
    dispatch_tool: Callable[..., str] = dispatch,
) -> str:
    """Answer one turn, calling tools until the model writes text.

    ``messages`` gains the assistant turn and any tool results. After five
    rounds that still call a tool, stop with a fixed sentence. A short data
    credit is added only when a tool returned forecast or tide data.
    """
    used_conditions = False
    for _ in range(MAX_TOOL_ROUNDS):
        message = complete(messages, tools=TOOLS)
        calls = _tool_calls(message)
        if not calls:
            text = _apply_credit(
                getattr(message, "content", None) or "", used_conditions
            )
            messages.append({"role": "assistant", "content": text})
            return text
        messages.append(_assistant_message(message, calls))
        for call_id, name, arguments in calls:
            result = dispatch_tool(name, arguments)
            used_conditions = used_conditions or _used_conditions(result)
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": call_id,
                    "content": result,
                }
            )
    messages.append({"role": "assistant", "content": LIMIT_MESSAGE})
    return LIMIT_MESSAGE


def _used_conditions(raw: str) -> bool:
    """True when this tool result carries a forecast or a tide attribution."""
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return False
    return isinstance(payload, dict) and "attributions" in payload


def _apply_credit(text: str, used: bool) -> str:
    """Keep the data credit off answers that never used a forecast or tide."""
    stripped = _strip_credit(text)
    if not used:
        return stripped
    if not stripped:
        return CREDIT_LINE
    return f"{stripped}\n{CREDIT_LINE}"


def _strip_credit(text: str) -> str:
    kept = [line for line in text.splitlines() if not _is_credit_line(line)]
    return "\n".join(kept).strip()


def _is_credit_line(line: str) -> bool:
    # A short line that names both sources is the credit, not a forecast.
    folded = " ".join(line.casefold().split())
    if "open-meteo" not in folded or "linz" not in folded:
        return False
    return len(folded) <= 80


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
