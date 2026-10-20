"""Runtime feature selection shared by API entrypoints and the chat integration."""
import os


def graphkit_enabled() -> bool:
    value = os.getenv("GRAPHKIT_ENABLED", "true").strip().lower()
    if value not in {"true", "false", "1", "0"}:
        raise ValueError("GRAPHKIT_ENABLED must be true/false or 1/0.")
    return value in {"true", "1"}


def chat_enabled() -> bool:
    value = os.getenv("CHAT_ENABLED", "false").strip().lower()
    if value not in {"true", "false", "1", "0"}:
        raise ValueError("CHAT_ENABLED must be true/false or 1/0.")
    return value in {"true", "1"}
