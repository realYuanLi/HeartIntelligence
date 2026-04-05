import json
import logging
import re
import urllib.request
from pathlib import Path

import openai
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

_EXERCISES: list[dict] | None = None
_EXERCISE_DB_PATH = Path(__file__).resolve().parent.parent / "resources" / "exercises" / "exercises.json"
_IMAGE_CACHE_DIR = Path(__file__).resolve().parent.parent / "resources" / "exercises" / "images"
_IMAGE_REMOTE_BASE = "https://raw.githubusercontent.com/yuhonas/free-exercise-db/main/exercises"

# Words that add noise to scoring — filtered from query before matching
_STOP_WORDS = frozenset({
    "a", "an", "the", "is", "are", "was", "were", "be", "been", "being",
    "do", "does", "did", "have", "has", "had", "will", "would", "could",
    "should", "may", "might", "can", "shall", "to", "of", "in", "for",
    "on", "with", "at", "by", "from", "as", "into", "about", "between",
    "and", "or", "but", "not", "no", "nor", "so", "if", "then",
    "i", "me", "my", "we", "us", "you", "your", "he", "she", "it",
    "show", "give", "tell", "find", "get", "want", "need", "like",
    "what", "how", "which", "some", "good", "best", "great", "recommend",
    "exercise", "workout", "routine", "training", "please", "help",
})

# Maps common user terms to the exact values used in the exercise database
_MUSCLE_SYNONYMS: dict[str, list[str]] = {
    "ab": ["abdominals"],
    "abs": ["abdominals"],
    "abdominal": ["abdominals"],
    "core": ["abdominals", "lower back"],
    "tummy": ["abdominals"],
    "stomach": ["abdominals"],
    "arm": ["biceps", "triceps", "forearms"],
    "arms": ["biceps", "triceps", "forearms"],
    "back": ["lats", "middle back", "lower back", "traps"],
    "leg": ["quadriceps", "hamstrings", "calves", "glutes"],
    "legs": ["quadriceps", "hamstrings", "calves", "glutes"],
    "thigh": ["quadriceps", "hamstrings", "adductors"],
    "butt": ["glutes"],
    "rear": ["glutes"],
    "hip": ["glutes", "abductors", "adductors"],
    "trap": ["traps"],
    "lat": ["lats"],
    "quad": ["quadriceps"],
    "ham": ["hamstrings"],
    "hamstring": ["hamstrings"],
    "calf": ["calves"],
    "calve": ["calves"],
    "glute": ["glutes"],
    "forearm": ["forearms"],
    "bicep": ["biceps"],
    "tricep": ["triceps"],
    "pec": ["chest"],
    "delt": ["shoulders"],
    "shoulder": ["shoulders"],
    "neck": ["neck"],
}

_BODY_REGION_EXPANSION: dict[str, list[str]] = {
    "upper body": ["chest", "shoulders", "biceps", "triceps", "lats", "middle back", "traps", "forearms"],
    "lower body": ["quadriceps", "hamstrings", "calves", "glutes", "adductors", "abductors"],
    "full body": ["chest", "shoulders", "quadriceps", "hamstrings", "abdominals", "lats"],
    "push": ["chest", "shoulders", "triceps"],
    "pull": ["lats", "middle back", "biceps"],
}

_EQUIPMENT_SYNONYMS: dict[str, str] = {
    "bodyweight": "body only",
    "none": "body only",
    "band": "bands",
    "resistance band": "bands",
    "ez bar": "e-z curl bar",
    "curl bar": "e-z curl bar",
    "kettlebell": "kettlebells",
    "ball": "exercise ball",
    "stability ball": "exercise ball",
    "foam roller": "foam roll",
    "med ball": "medicine ball",
}

# Direct DB equipment values, for matching raw tokens in queries
_DB_EQUIPMENT_VALUES = frozenset({
    "bands", "barbell", "body only", "cable", "dumbbell",
    "e-z curl bar", "exercise ball", "foam roll", "kettlebells",
    "machine", "medicine ball", "other",
})

# Phrases that signal "body only" equipment preference
_BODYWEIGHT_PHRASES = ["at home", "no equipment", "without equipment", "bodyweight", "body weight", "no gym"]

_CATEGORY_SYNONYMS: dict[str, str] = {
    "stretch": "stretching",
    "stretching": "stretching",
    "flexibility": "stretching",
    "cardio": "cardio",
    "aerobic": "cardio",
    "plyo": "plyometrics",
    "plyometric": "plyometrics",
    "plyometrics": "plyometrics",
    "explosive": "plyometrics",
    "olympic": "olympic weightlifting",
    "weightlifting": "olympic weightlifting",
    "powerlifting": "powerlifting",
    "strongman": "strongman",
    "strength": "strength",
}


def _load_exercises() -> list[dict]:
    global _EXERCISES
    if _EXERCISES is not None:
        return _EXERCISES
    try:
        with open(_EXERCISE_DB_PATH, "r", encoding="utf-8") as f:
            _EXERCISES = json.load(f)
    except Exception as exc:
        logger.error("Failed to load exercise database: %s", exc)
        _EXERCISES = []
    return _EXERCISES


def needs_workout_data(query: str) -> bool:
    """Use GPT-4o to decide if a query needs exercise/workout information."""
    try:
        client = openai.OpenAI()
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {
                    "role": "system",
                    "content": """You are a decision maker. Determine if a user query requires exercise or workout information to answer accurately.

Return ONLY "YES" for:
- Requests for exercise recommendations or routines
- Questions about specific exercises, workouts, or training
- Queries mentioning muscle groups, body parts to train, or fitness equipment
- Requests for stretching, warm-up, or cool-down exercises
- Questions about exercise form, technique, or alternatives

Return ONLY "NO" for:
- General health questions not about exercise (diet, medication, symptoms)
- Questions unrelated to fitness or working out
- Simple greetings or casual conversation

Examples:
- "What are good chest exercises?" → YES
- "I want a beginner leg workout" → YES
- "Show me back exercises with dumbbells" → YES
- "How to stretch my hamstrings?" → YES
- "What is hypertension?" → NO
- "What should I eat for dinner?" → NO
- "Hello, how are you?" → NO""",
                },
                {"role": "user", "content": f"Query: {query}"},
            ],
            temperature=0,
            max_tokens=3,
        )
        decision = response.choices[0].message.content.strip().upper()
        return decision == "YES"
    except Exception as exc:
        logger.error("Error in needs_workout_data: %s", exc)
        return False


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").lower()).strip()


def _stem(token: str) -> str:
    """Minimal stemming: strip trailing 's' for plural matching."""
    if len(token) > 3 and token.endswith("s") and not token.endswith("ss"):
        return token[:-1]
    return token


def _tokenize(text: str) -> list[str]:
    """Tokenize, stem, return list (preserving order)."""
    raw = re.findall(r"[a-z0-9]+", _normalize(text))
    return [_stem(t) for t in raw]


def _parse_query(query: str) -> dict:
    """Parse a user query into structured search intent."""
    normalized = _normalize(query)
    tokens = _tokenize(query)

    # Detect bodyweight intent from phrases
    prefer_bodyweight = any(phrase in normalized for phrase in _BODYWEIGHT_PHRASES)

    # Detect equipment from synonyms and direct DB values
    target_equipment: set[str] = set()
    token_set = set(tokens)
    for synonym, canonical in _EQUIPMENT_SYNONYMS.items():
        syn_tokens = set(_tokenize(synonym))
        if syn_tokens and syn_tokens.issubset(token_set):
            target_equipment.add(canonical)
    # Also match raw tokens against known DB equipment values
    for db_equip in _DB_EQUIPMENT_VALUES:
        equip_tokens = set(_tokenize(db_equip))
        if equip_tokens and equip_tokens.issubset(token_set):
            target_equipment.add(db_equip)
    if prefer_bodyweight:
        target_equipment.add("body only")

    # Detect category from synonyms (match against both raw and stemmed tokens)
    target_categories: set[str] = set()
    raw_tokens = set(re.findall(r"[a-z0-9]+", normalized))
    for synonym, canonical in _CATEGORY_SYNONYMS.items():
        if synonym in raw_tokens or synonym in token_set:
            target_categories.add(canonical)

    # Detect body region expansions (multi-word phrases)
    expanded_muscles: set[str] = set()
    for phrase, muscles in _BODY_REGION_EXPANSION.items():
        if phrase in normalized:
            expanded_muscles.update(muscles)

    # Detect individual muscle targets via synonyms
    target_muscles: set[str] = set()
    clean_tokens = {t for t in tokens if t not in _STOP_WORDS}
    clean_raw_tokens = {t for t in raw_tokens if t not in _STOP_WORDS}
    all_query_tokens = clean_tokens | clean_raw_tokens
    for token in all_query_tokens:
        if token in _MUSCLE_SYNONYMS:
            target_muscles.update(_MUSCLE_SYNONYMS[token])
    # Also check direct match against DB muscle names (stemmed)
    for db_muscle in [
        "abdominals", "hamstrings", "adductors", "quadriceps", "biceps",
        "shoulders", "chest", "middle back", "calves", "glutes",
        "lower back", "lats", "triceps", "traps", "forearms", "neck", "abductors",
    ]:
        db_tokens = set(_tokenize(db_muscle))
        if db_tokens and db_tokens.issubset(all_query_tokens):
            target_muscles.add(db_muscle)

    # Combine expanded muscles with individual targets
    all_target_muscles = target_muscles | expanded_muscles

    # Detect level
    target_level = ""
    for level in ["beginner", "intermediate", "expert", "advanced"]:
        if _stem(level) in clean_tokens:
            target_level = "expert" if level == "advanced" else level
            break

    # Clean tokens: remove stop words, equipment, and level for name matching
    equipment_tokens = set()
    for equip in target_equipment:
        equipment_tokens.update(_tokenize(equip))
    name_tokens = clean_tokens - equipment_tokens - {target_level}

    return {
        "target_muscles": all_target_muscles,
        "target_equipment": target_equipment,
        "target_categories": target_categories,
        "target_level": target_level,
        "prefer_bodyweight": prefer_bodyweight,
        "name_tokens": name_tokens,
    }


def search_exercises(query: str, max_results: int = 8) -> list[dict]:
    """Search exercises using structured query parsing and multi-field scoring."""
    exercises = _load_exercises()
    if not exercises:
        return []

    intent = _parse_query(query)
    target_muscles = intent["target_muscles"]
    target_equipment = intent["target_equipment"]
    target_categories = intent["target_categories"]
    target_level = intent["target_level"]
    prefer_bodyweight = intent["prefer_bodyweight"]
    name_tokens = intent["name_tokens"]

    # If nothing was parsed, fall back to raw token matching
    if not any([target_muscles, target_equipment, target_categories, target_level, name_tokens]):
        return []

    scored: list[tuple[dict, float]] = []

    for ex in exercises:
        score = 0.0

        # Primary muscle match (weight 5.0 per muscle)
        primary_muscles = {_normalize(m) for m in ex.get("primaryMuscles", [])}
        primary_hit = bool(primary_muscles & target_muscles)
        if primary_hit:
            score += 5.0

        # Secondary muscle match (weight 2.0)
        secondary_muscles = {_normalize(m) for m in ex.get("secondaryMuscles", [])}
        if secondary_muscles & target_muscles:
            score += 2.0

        # Equipment match (weight 4.0)
        ex_equipment = _normalize(ex.get("equipment") or "")
        if target_equipment and ex_equipment in target_equipment:
            score += 4.0
        # Penalty if user wants bodyweight but exercise needs equipment
        if prefer_bodyweight and ex_equipment and ex_equipment != "body only":
            score -= 3.0

        # Level match (weight 3.0)
        ex_level = _normalize(ex.get("level", ""))
        if target_level and ex_level == target_level:
            score += 3.0

        # Category match (weight 3.0)
        ex_category = _normalize(ex.get("category", ""))
        if target_categories and ex_category in target_categories:
            score += 3.0

        # Name token overlap (weight 2.0 per token) — only non-stop-word tokens
        ex_name_tokens = set(_tokenize(ex.get("name", "")))
        name_overlap = name_tokens & ex_name_tokens
        score += len(name_overlap) * 2.0

        if score > 0:
            scored.append((ex, score))

    scored.sort(key=lambda item: item[1], reverse=True)

    results = [ex for ex, _ in scored[:max_results]]

    # For body region queries, try to diversify across muscle groups
    if len(target_muscles) > 2 and len(results) >= 4:
        results = _diversify_by_muscle(scored, target_muscles, max_results)

    return results


def _diversify_by_muscle(
    scored: list[tuple[dict, float]],
    target_muscles: set[str],
    max_results: int,
) -> list[dict]:
    """Pick top exercises while spreading across different muscle groups."""
    selected: list[dict] = []
    muscles_covered: dict[str, int] = {}
    max_per_muscle = max(1, max_results // max(1, len(target_muscles))) + 1

    for ex, _score in scored:
        if len(selected) >= max_results:
            break
        primary = {_normalize(m) for m in ex.get("primaryMuscles", [])}
        # Check if we've already filled this muscle group
        dominated = any(muscles_covered.get(m, 0) >= max_per_muscle for m in primary)
        if dominated and len(selected) >= len(target_muscles):
            continue
        selected.append(ex)
        for m in primary:
            muscles_covered[m] = muscles_covered.get(m, 0) + 1

    return selected


def ensure_exercise_image(image_path: str) -> bool:
    """Download an exercise image to local cache if not already present.

    Returns True if the local file exists (either already cached or just downloaded).
    """
    local_path = _IMAGE_CACHE_DIR / image_path
    if local_path.exists():
        return True
    try:
        local_path.parent.mkdir(parents=True, exist_ok=True)
        remote_url = f"{_IMAGE_REMOTE_BASE}/{image_path}"
        urllib.request.urlretrieve(remote_url, local_path)
        return True
    except Exception as exc:
        logger.warning("Failed to download exercise image %s: %s", image_path, exc)
        return False


def get_exercise_image_path(image_path: str) -> Path | None:
    """Return the local filesystem path for an exercise image, or None."""
    local_path = _IMAGE_CACHE_DIR / image_path
    return local_path if local_path.exists() else None


def format_exercise_results(exercises: list[dict]) -> str:
    """Format exercise results as concise structured markdown for LLM context."""
    if not exercises:
        return ""

    sections = []
    for i, ex in enumerate(exercises, 1):
        name = ex.get("name", "Unknown")
        level = ex.get("level", "N/A").capitalize()
        category = ex.get("category", "N/A").capitalize()
        equipment = (ex.get("equipment") or "None").capitalize()
        primary = ", ".join(m.capitalize() for m in ex.get("primaryMuscles", []))
        secondary = ", ".join(m.capitalize() for m in ex.get("secondaryMuscles", []))
        instructions = ex.get("instructions", [])
        images = ex.get("images", [])

        section = f"### {i}. {name}\n"
        section += f"**{level} | {category} | {equipment}**\n"
        section += f"Targets: {primary}"
        if secondary:
            section += f" (also: {secondary})"
        section += "\n"

        if instructions:
            # Keep instructions concise: combine into flowing text
            section += "\n**How to:**\n"
            for step_num, step in enumerate(instructions, 1):
                section += f"{step_num}. {step}\n"

        if images:
            # Pre-cache first image locally; serve via Flask route
            img_path = images[0]
            ensure_exercise_image(img_path)
            img_url = f"/exercises/images/{img_path}"
            section += f"\n![{name}]({img_url})\n"

        sections.append(section)

    header = f"**Exercise Database — {len(exercises)} results:**\n\n"
    return header + "\n---\n\n".join(sections)
