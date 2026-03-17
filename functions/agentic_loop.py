import logging
import re
from dataclasses import dataclass, field
from typing import Literal

logger = logging.getLogger(__name__)


@dataclass
class LoopState:
    plan: list[str] = field(default_factory=list)
    current_step: int = 0
    iteration: int = 0
    max_iterations: int = 5
    completed: bool = False


# Keywords grouped by tool domain
_DOMAIN_KEYWORDS = {
    "exercise": {"exercise", "workout", "training", "muscle", "gym", "cardio", "strength", "reps", "sets", "routine"},
    "nutrition": {"meal", "diet", "calories", "protein", "nutrition", "food", "recipe", "grocery", "macros", "eating"},
    "health": {"health", "blood", "cholesterol", "weight", "bmi", "lab", "test", "diagnosis", "symptoms", "medical"},
    "memory": {"remember", "forget", "preference", "goal", "allergy", "recall"},
    "plan": {"plan", "schedule", "weekly", "calendar", "create", "modify"},
}

_MULTI_STEP_CONNECTORS = [
    "and then",
    "based on that",
    "after that",
    "use that to",
    "using those",
    "then use",
    "followed by",
    "once you have",
    "with those results",
    "taking into account",
]


def classify_query(query: str) -> Literal["simple", "complex"]:
    """Classify a user query as simple or complex based on heuristics."""
    lower_query = query.lower()

    # Check for multi-step connectors
    for connector in _MULTI_STEP_CONNECTORS:
        if connector in lower_query:
            return "complex"

    # Check for length + multi-domain signals
    query_tokens = set(re.findall(r"[a-z]+", lower_query))
    matched_domains = set()
    for domain, keywords in _DOMAIN_KEYWORDS.items():
        if query_tokens & keywords:
            matched_domains.add(domain)

    # Long query referencing 2+ different tool domains
    if len(query) > 150 and len(matched_domains) >= 2:
        return "complex"

    # References 3+ distinct domains regardless of length
    if len(matched_domains) >= 3:
        return "complex"

    return "simple"


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


def should_continue(state: LoopState, has_tool_calls: bool, has_content: bool) -> bool:
    """Decide whether the agentic loop should continue iterating."""
    if state.completed:
        return False
    if state.iteration >= state.max_iterations:
        return False
    if not has_tool_calls and has_content:
        return False
    return True


def generate_plan(query: str, client, model: str = "gpt-4o-mini") -> list[str]:
    """Use a lightweight LLM call to produce 3-5 bullet plan steps."""
    try:
        response = client.chat.completions.create(
            model=model,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a planning assistant. Given a user query, produce a concise plan "
                        "of 3-5 numbered steps to answer it using available tools (exercise_search, "
                        "manage_workout_plan, manage_nutrition, manage_memory). "
                        "Return ONLY the numbered steps, one per line, no other text."
                    ),
                },
                {"role": "user", "content": query},
            ],
            temperature=0,
            max_tokens=300,
        )
        raw = response.choices[0].message.content or ""
        steps = []
        for line in raw.strip().splitlines():
            cleaned = re.sub(r"^\d+[\.\)]\s*", "", line.strip())
            if cleaned:
                steps.append(cleaned)
        if steps:
            return steps[:5]
    except Exception:
        logger.warning("Plan generation failed", exc_info=True)
    return ["Answer the user's query directly"]
