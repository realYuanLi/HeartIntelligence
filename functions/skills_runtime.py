import json
import logging
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

from .health_analyzer import analyze_health_query_with_raw_data
from .food_image_analyzer import analyze_food_image, format_food_image_analysis
from .md_utils import _parse_bool, _parse_frontmatter
from .web_search import format_search_results, needs_web_search, web_search
from .workout_search import needs_workout_data, search_exercises, format_exercise_results
from .nutrition_search import needs_nutrition_data, search_foods, format_food_results
from .physical_exam_search import needs_physical_exam_data, search_findings, format_finding_results
from .health_qa_search import needs_health_qa, search_health_topics, format_health_results

logger = logging.getLogger(__name__)
SKILL_STATE_PATH = Path(__file__).resolve().parent.parent / "config" / "skills_settings.json"
_skill_state_lock = threading.Lock()


@dataclass
class SkillDefinition:
    skill_id: str
    title: str
    executor: str
    kind: str
    enabled_by_default: bool
    description: str
    instructions: str
    routing_text: str = ""
    routing_tokens: frozenset[str] = frozenset()
    routing_phrases: frozenset[str] = frozenset()


def _normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", (value or "").lower()).strip()


def _tokenize(value: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", _normalize_text(value))


def _phrase_set(tokens: list[str], n: int) -> set[str]:
    if len(tokens) < n:
        return set()
    return {" ".join(tokens[idx : idx + n]) for idx in range(len(tokens) - n + 1)}


def _load_skill_state(path: Path = SKILL_STATE_PATH) -> dict[str, bool]:
    if not path.exists():
        return {}
    try:
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return {}
        return {str(k): bool(v) for k, v in data.items()}
    except Exception as exc:
        logger.warning("Failed to load skill state from %s: %s", path, exc)
        return {}


def _save_skill_state(state: dict[str, bool], path: Path = SKILL_STATE_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)


def get_skill_state(path: Path = SKILL_STATE_PATH) -> dict[str, bool]:
    with _skill_state_lock:
        return _load_skill_state(path)


def set_skill_enabled(skill_id: str, enabled: bool, path: Path = SKILL_STATE_PATH) -> None:
    with _skill_state_lock:
        state = _load_skill_state(path)
        state[skill_id] = bool(enabled)
        _save_skill_state(state, path)


class SkillRuntime:
    """Markdown-driven skill runtime for routing and execution."""

    def __init__(
        self,
        ehr_data: Optional[dict] = None,
        mobile_data: Optional[dict] = None,
        skills_dir: Optional[Path] = None,
    ):
        self.ehr_data = ehr_data or {}
        self.mobile_data = mobile_data or {}
        self.skills_dir = skills_dir or (Path(__file__).resolve().parent.parent / "skills")
        self.skill_state_path = SKILL_STATE_PATH
        self.always_include_skills = {"set_reminder"}
        self.skills = self._load_skills()
        self.executors: dict[str, Callable[..., dict]] = {
            "set_reminder": self._run_set_reminder,
            "web_search": self._run_web_search,
            "personal_health_context": self._run_personal_health_context,
            "workout_guidance": self._run_workout_guidance,
            "workout_calendar": self._run_workout_calendar,
            "nutrition_guidance": self._run_nutrition_guidance,
            "physical_exam_interpreter": self._run_physical_exam_interpreter,
            "health_qa": self._run_health_qa,
            "external_calendar": self._run_external_calendar,
            "food_image_analysis": self._run_food_image_analysis,
        }

    def _load_skills(self) -> dict[str, SkillDefinition]:
        loaded: dict[str, SkillDefinition] = {}
        if not self.skills_dir.exists():
            logger.warning("Skills directory not found: %s", self.skills_dir)
            return loaded

        for path in sorted(self.skills_dir.glob("*.md")):
            try:
                raw = path.read_text(encoding="utf-8")
                meta, body = _parse_frontmatter(raw)
                skill_id = meta.get("id") or path.stem
                title = meta.get("title", skill_id)
                description = meta.get("description", "")
                routing_text = _normalize_text(f"{title} {description} {body} {skill_id}")
                routing_token_list = _tokenize(routing_text)
                routing_tokens = frozenset(routing_token_list)
                routing_phrases = frozenset(_phrase_set(routing_token_list, 2))
                loaded[skill_id] = SkillDefinition(
                    skill_id=skill_id,
                    title=title,
                    executor=meta.get("executor", ""),
                    kind=meta.get("kind", "context"),
                    enabled_by_default=_parse_bool(meta.get("enabled_by_default", "true"), True),
                    description=description,
                    instructions=body,
                    routing_text=routing_text,
                    routing_tokens=routing_tokens,
                    routing_phrases=routing_phrases,
                )
            except Exception as exc:
                logger.error("Failed to load skill file %s: %s", path, exc)
        return loaded

    def _score_skill_for_query(self, skill: SkillDefinition, query: str) -> float:
        query_tokens_list = _tokenize(query)
        if not query_tokens_list:
            return 0.0

        query_tokens = set(query_tokens_list)
        overlap = query_tokens.intersection(skill.routing_tokens)
        token_score = len(overlap) / max(1, len(query_tokens))

        query_bigrams = _phrase_set(query_tokens_list, 2)
        phrase_overlap = query_bigrams.intersection(skill.routing_phrases)
        phrase_score = 0.3 if phrase_overlap else 0.0

        id_or_executor_bonus = 0.0
        query_text = _normalize_text(query)
        if skill.skill_id in query_text or skill.executor in query_text:
            id_or_executor_bonus = 0.25

        return token_score + phrase_score + id_or_executor_bonus

    def _prefilter_by_description(
        self,
        query: str,
        selected_skills: list[SkillDefinition],
        kind: str,
        top_k: int,
        min_score: float,
    ) -> list[SkillDefinition]:
        if not selected_skills:
            return []

        always_include = {
            skill.skill_id
            for skill in selected_skills
            if skill.skill_id in self.always_include_skills and skill.kind == kind
        }

        scored = []
        for skill in selected_skills:
            score = self._score_skill_for_query(skill, query)
            if score >= min_score:
                scored.append((skill, score))

        scored.sort(key=lambda item: item[1], reverse=True)
        limited = [skill for skill, _ in scored[: max(1, top_k)]]

        for skill in selected_skills:
            if skill.skill_id in always_include and skill not in limited:
                limited.append(skill)
        return limited

    def _should_run(self, skill: SkillDefinition, query: str, runtime_context: dict | None = None) -> bool:
        executor = skill.executor
        if executor == "set_reminder":
            return True
        if executor == "web_search":
            return needs_web_search(query)
        if executor == "personal_health_context":
            needs_health, _, _, _ = analyze_health_query_with_raw_data(
                query,
                self.ehr_data,
                show_raw_data=False,
                mobile_data=self.mobile_data,
            )
            return needs_health
        if executor == "workout_guidance":
            return needs_workout_data(query)
        if executor == "workout_calendar":
            return self._needs_workout_completion(query)
        if executor == "nutrition_guidance":
            return needs_nutrition_data(query)
        if executor == "physical_exam_interpreter":
            return needs_physical_exam_data(query)
        if executor == "health_qa":
            return needs_health_qa(query)
        if executor == "external_calendar":
            return self._needs_calendar_context(query)
        if executor == "food_image_analysis":
            return bool((runtime_context or {}).get("images"))
        return False

    def _is_skill_enabled(self, skill: SkillDefinition, overrides: dict[str, bool]) -> bool:
        if skill.skill_id in overrides:
            return bool(overrides[skill.skill_id])
        return skill.enabled_by_default

    def get_instructions(self) -> str:
        """Return concatenated bodies of all enabled 'instructions' kind skills."""
        overrides = get_skill_state(self.skill_state_path)
        bodies = []
        for skill in self.skills.values():
            if skill.kind != "instructions":
                continue
            if not self._is_skill_enabled(skill, overrides):
                continue
            bodies.append(skill.instructions)
        return "\n\n".join(bodies)

    def get_skill_descriptions(self) -> str:
        """Build a capabilities summary from enabled non-instruction skill descriptions."""
        overrides = get_skill_state(self.skill_state_path)
        lines = []
        for skill in sorted(self.skills.values(), key=lambda s: s.title.lower()):
            if skill.kind == "instructions":
                continue
            if not self._is_skill_enabled(skill, overrides):
                continue
            lines.append(f"- **{skill.title}**: {skill.description}")
        if not lines:
            return ""
        return "# Available Skills\n\n" + "\n".join(lines)

    def list_skills(self) -> list[dict]:
        overrides = get_skill_state(self.skill_state_path)
        items = []
        for skill in self.skills.values():
            items.append(
                {
                    "id": skill.skill_id,
                    "name": skill.title,
                    "description": skill.description,
                    "kind": skill.kind,
                    "enabled": self._is_skill_enabled(skill, overrides),
                }
            )
        items.sort(key=lambda item: item["name"].lower())
        return items

    def run(
        self,
        query: str,
        kind: str,
        runtime_context: Optional[dict] = None,
        status_updater: Optional[Callable[[str], None]] = None,
    ) -> dict[str, dict]:
        start_total = time.time()
        runtime_context = runtime_context or {}
        state_overrides = get_skill_state(self.skill_state_path)
        selected = [
            skill
            for skill in self.skills.values()
            if self._is_skill_enabled(skill, state_overrides)
            and skill.kind == kind
            and skill.executor in self.executors
        ]

        if not selected:
            return {}

        prefilter_enabled = runtime_context.get("prefilter_enabled", True)
        prefilter_top_k = int(runtime_context.get("prefilter_top_k", 5))
        prefilter_min_score = float(runtime_context.get("prefilter_min_score", 0.0))
        prefilter_empty_fallback = runtime_context.get("prefilter_empty_fallback", "top2")

        start_prefilter = time.time()
        shortlisted = selected
        if prefilter_enabled:
            shortlisted = self._prefilter_by_description(
                query=query,
                selected_skills=selected,
                kind=kind,
                top_k=prefilter_top_k,
                min_score=prefilter_min_score,
            )
            if not shortlisted:
                if prefilter_empty_fallback == "full":
                    shortlisted = selected
                elif prefilter_empty_fallback == "top2":
                    top_n = min(2, len(selected))
                    shortlisted = selected[:top_n]
        prefilter_ms = (time.time() - start_prefilter) * 1000

        start_gate = time.time()
        runnable = [skill for skill in shortlisted if self._should_run(skill, query, runtime_context)]
        gate_ms = (time.time() - start_gate) * 1000
        if not runnable:
            logger.info(
                "skill_routing kind=%s selected=%d shortlisted=%d runnable=0 prefilter_ms=%.1f gate_ms=%.1f total_ms=%.1f",
                kind,
                len(selected),
                len(shortlisted),
                prefilter_ms,
                gate_ms,
                (time.time() - start_total) * 1000,
            )
            return {}

        start_execute = time.time()
        results: dict[str, dict] = {}
        max_workers = min(4, len(runnable))
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_skill = {
                executor.submit(
                    self.executors[skill.executor],
                    query,
                    runtime_context,
                    status_updater,
                    skill,
                ): skill
                for skill in runnable
            }
            for future in as_completed(future_to_skill):
                skill = future_to_skill[future]
                try:
                    results[skill.skill_id] = future.result()
                except Exception as exc:
                    logger.error("Skill %s failed: %s", skill.skill_id, exc)
                    results[skill.skill_id] = {"activated": False, "error": str(exc)}

        execute_ms = (time.time() - start_execute) * 1000
        activated_skills = sorted(
            [skill_id for skill_id, payload in results.items() if payload.get("activated")]
        )
        logger.info(
            "skill_routing kind=%s selected=%d shortlisted=%d runnable=%d activated=%s prefilter_ms=%.1f gate_ms=%.1f execute_ms=%.1f total_ms=%.1f",
            kind,
            len(selected),
            len(shortlisted),
            len(runnable),
            activated_skills,
            prefilter_ms,
            gate_ms,
            execute_ms,
            (time.time() - start_total) * 1000,
        )
        return results

    def _run_set_reminder(
        self,
        query: str,
        runtime_context: dict,
        _status_updater: Optional[Callable[[str], None]],
        _skill: SkillDefinition,
    ) -> dict:
        from .cron_jobs import create_reminder_from_chat

        job = create_reminder_from_chat(
            user_message=query,
            user=runtime_context.get("user", ""),
            sender_jid=runtime_context.get("sender_jid", ""),
            session_id=runtime_context.get("session_id", ""),
        )
        return {"activated": bool(job), "job": job}

    def _run_web_search(
        self,
        query: str,
        _runtime_context: dict,
        status_updater: Optional[Callable[[str], None]],
        _skill: SkillDefinition,
    ) -> dict:
        if status_updater:
            status_updater("searching_web")
        search_results = web_search(query)
        if status_updater:
            status_updater("analyzing_web_data")
        return {
            "activated": True,
            "search_results": search_results,
            "web_summary": format_search_results(search_results),
        }

    def _run_personal_health_context(
        self,
        query: str,
        _runtime_context: dict,
        _status_updater: Optional[Callable[[str], None]],
        _skill: SkillDefinition,
    ) -> dict:
        needs_health, patient_profile, formatted_output, patient_data_formatted = (
            analyze_health_query_with_raw_data(
                query,
                self.ehr_data,
                show_raw_data=True,
                mobile_data=self.mobile_data,
            )
        )
        if not needs_health:
            return {"activated": False}

        health_summary = patient_data_formatted or formatted_output
        return {
            "activated": True,
            "health_analysis": {
                "needs_health": needs_health,
                "patient_profile": patient_profile,
                "formatted_output": formatted_output,
                "patient_data_formatted": patient_data_formatted,
            },
            "health_summary": health_summary,
        }

    def _run_workout_guidance(
        self,
        query: str,
        _runtime_context: dict,
        status_updater: Optional[Callable[[str], None]],
        _skill: SkillDefinition,
    ) -> dict:
        if status_updater:
            status_updater("searching_exercises")
        exercises = search_exercises(query)
        if not exercises:
            return {"activated": False}
        if status_updater:
            status_updater("formatting_exercises")
        workout_summary = format_exercise_results(exercises)
        return {
            "activated": True,
            "exercises": exercises,
            "workout_summary": workout_summary,
        }

    def _run_nutrition_guidance(
        self,
        query: str,
        _runtime_context: dict,
        status_updater: Optional[Callable[[str], None]],
        _skill: SkillDefinition,
    ) -> dict:
        if status_updater:
            status_updater("searching_foods")
        foods = search_foods(query)
        if not foods:
            return {"activated": False}
        if status_updater:
            status_updater("formatting_nutrition")
        nutrition_summary = format_food_results(foods)
        return {
            "activated": True,
            "foods": foods,
            "nutrition_summary": nutrition_summary,
        }

    def _run_physical_exam_interpreter(
        self,
        query: str,
        _runtime_context: dict,
        status_updater: Optional[Callable[[str], None]],
        _skill: SkillDefinition,
    ) -> dict:
        if status_updater:
            status_updater("interpreting_exam_findings")
        findings = search_findings(query)
        if not findings:
            return {"activated": False}
        if status_updater:
            status_updater("formatting_exam_findings")
        exam_summary = format_finding_results(findings)
        return {
            "activated": True,
            "findings": findings,
            "exam_summary": exam_summary,
        }

    def _run_health_qa(
        self,
        query: str,
        _runtime_context: dict,
        status_updater: Optional[Callable[[str], None]],
        _skill: SkillDefinition,
    ) -> dict:
        if status_updater:
            status_updater("searching_health_topics")
        topics = search_health_topics(query)
        if not topics:
            return {"activated": False}
        if status_updater:
            status_updater("formatting_health_topics")
        health_qa_summary = format_health_results(topics, query=query)
        return {
            "activated": True,
            "topics": topics,
            "health_qa_summary": health_qa_summary,
        }

    def _run_food_image_analysis(
        self,
        query: str,
        runtime_context: dict,
        status_updater: Optional[Callable[[str], None]],
        _skill: SkillDefinition,
    ) -> dict:
        images = runtime_context.get("images", [])
        if not images:
            return {"activated": False}

        if status_updater:
            status_updater("analyzing_food_image")
        username = runtime_context.get("user", "")
        analysis = analyze_food_image(images[0], username=username)

        if not analysis.get("detected"):
            return {"activated": False}

        formatted = format_food_image_analysis(analysis)
        return {
            "activated": True,
            "food_image_analysis": analysis,
            "food_image_summary": formatted,
        }

    _COMPLETION_PATTERNS = re.compile(
        r"\b(finished|done|completed|did)\b.{0,20}\b(workout|exercise|training|gym|session|today)\b"
        r"|\b(worked out|just trained|hit the gym)\b",
        re.IGNORECASE,
    )

    def _needs_workout_completion(self, query: str) -> bool:
        return bool(self._COMPLETION_PATTERNS.search(query))

    def _run_workout_calendar(
        self,
        query: str,
        runtime_context: dict,
        _status_updater: Optional[Callable[[str], None]],
        _skill: SkillDefinition,
    ) -> dict:
        username = runtime_context.get("user", "")
        if not username:
            return {"activated": False}

        from .workout_plans import mark_day_complete, _get_active_plan
        plan = _get_active_plan(username)
        if not plan:
            return {"activated": False}

        from datetime import datetime
        today = datetime.now().strftime("%Y-%m-%d")
        mark_day_complete(username, today, True)
        return {"activated": True, "marked_date": today}

    _CALENDAR_PATTERNS = re.compile(
        r"\b(schedule|busy|free|available|calendar|meeting|appointment|"
        r"plan|today|tomorrow|this week|next week|slot|conflict|"
        r"when.{0,10}(am i|can i|should i)|what.{0,10}(do i have|is on)|"
        r"make.{0,10}(plan|schedule)|create.{0,10}(plan|schedule))\b",
        re.IGNORECASE,
    )

    def _needs_calendar_context(self, query: str) -> bool:
        """Check if the query might benefit from calendar context."""
        if not self._CALENDAR_PATTERNS.search(query):
            return False
        # Only activate if user actually has feeds configured
        from .external_calendar import has_feeds
        # Use the username from the runtime context — checked by run()
        # For gating, we just check if any user has feeds (lightweight)
        return True

    def _run_external_calendar(
        self,
        query: str,
        runtime_context: dict,
        status_updater: Optional[Callable[[str], None]],
        _skill: SkillDefinition,
    ) -> dict:
        username = runtime_context.get("user", "")
        if not username:
            return {"activated": False}

        from .external_calendar import get_upcoming_events, format_events_for_context, has_feeds
        if not has_feeds(username):
            return {"activated": False}

        if status_updater:
            status_updater("loading_calendar")
        events = get_upcoming_events(username)
        if not events:
            return {"activated": False}

        calendar_summary = format_events_for_context(events)
        return {
            "activated": True,
            "events": events,
            "calendar_summary": calendar_summary,
        }
