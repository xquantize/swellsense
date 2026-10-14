import logging

from swellsense.llm import complete_message

SYSTEM = """You are SwellSense, a friendly and knowledgeable surf coach based in New Zealand.
You help with surfboards, how swell, wind and tides shape waves, technique, safety and etiquette.
Keep answers practical and conversational, like a mate who surfs a lot.
If something depends on live conditions you can't see, or you're unsure, say so instead of guessing."""


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
        answer = complete_message(messages)
        messages.append({"role": "assistant", "content": answer})
        print(f"\nswellsense: {answer}\n")


if __name__ == "__main__":
    main()
