"""Token budget helpers for OpenAI-compatible chat requests."""

from __future__ import annotations

import json
import math
from typing import Any, Iterable


def estimate_text_tokens(text: Any) -> int:
    """Conservative token estimate without model-specific tokenizer dependency."""
    if text is None:
        return 0

    value = str(text)
    if not value:
        return 0

    ascii_count = 0
    non_ascii_count = 0
    for char in value:
        if ord(char) < 128:
            ascii_count += 1
        else:
            non_ascii_count += 1

    # Chinese text is often close to one token per character; ASCII JSON is denser.
    return int(math.ceil(non_ascii_count * 1.1 + ascii_count / 3.0))


def estimate_json_tokens(value: Any) -> int:
    try:
        text = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    except TypeError:
        text = str(value)
    return estimate_text_tokens(text)


def estimate_messages_tokens(messages: Iterable[dict]) -> int:
    total = 0
    for message in messages:
        total += 4
        total += estimate_text_tokens(message.get("role", ""))
        total += estimate_text_tokens(message.get("content", ""))
        if message.get("tool_calls"):
            total += estimate_json_tokens(message.get("tool_calls"))
        if message.get("tool_call_id"):
            total += estimate_text_tokens(message.get("tool_call_id"))
    return total + 3


def estimate_tools_tokens(tools: Any) -> int:
    if not tools:
        return 0
    return estimate_json_tokens(tools)
