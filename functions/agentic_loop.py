import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class LoopState:
    iteration: int = 0
    max_iterations: int = 8


def summarize_tool_result(result: str, max_chars: int = 800) -> str:
    """Truncate a tool result at the last sentence boundary before the limit."""
    if len(result) <= max_chars:
        return result

    truncated = result[:max_chars]
    # Find the last sentence-ending punctuation
    last_period = -1
    for punct in [".", "!", "?"]:
        idx = truncated.rfind(punct)
        if idx > last_period:
            last_period = idx

    if last_period > 0:
        return truncated[: last_period + 1] + " [truncated]"
    return truncated + " [truncated]"



REFLECTION_CONTENT = (
    "You have gathered some information from tools. If you now have enough "
    "to fully answer the user's question, respond directly. If you need more "
    "data, call the appropriate tool."
)


def make_reflection_message(iteration: int) -> dict | None:
    """Return a reflection nudge for iteration >= 1, or None for iteration < 1."""
    if iteration < 1:
        return None
    return {"role": "system", "content": REFLECTION_CONTENT}
