"""Physical examination interpreter: finding search, clinical significance, structured documentation.

Clinician-support / medical-education skill that interprets physical exam findings,
highlights possible significance, and structures them into useful outputs.

This is NOT a direct diagnostic tool. All outputs include appropriate clinical
context and emphasize that findings must be interpreted within the full clinical picture.
"""

import json
import logging
import re
from pathlib import Path

import openai
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

_FINDINGS: list[dict] | None = None
_FINDINGS_DB_PATH = (
    Path(__file__).resolve().parent.parent / "resources" / "physical_exam" / "findings_reference.json"
)

# ---------- stop words & synonyms ----------

_STOP_WORDS = frozenset({
    "a", "an", "the", "is", "are", "was", "were", "be", "been", "being",
    "do", "does", "did", "have", "has", "had", "will", "would", "could",
    "should", "may", "might", "can", "shall", "to", "of", "in", "for",
    "on", "with", "at", "by", "from", "as", "into", "about", "between",
    "and", "or", "but", "not", "no", "nor", "so", "if", "then",
    "i", "me", "my", "we", "us", "you", "your", "he", "she", "it",
    "show", "give", "tell", "find", "get", "want", "need", "like",
    "what", "how", "which", "some", "good", "best", "great", "recommend",
    "please", "help", "exam", "examination", "physical", "finding",
    "findings", "patient", "found", "noted", "present", "interpret",
    "mean", "means", "significance", "significant",
})

_SYSTEM_SYNONYMS: dict[str, list[str]] = {
    "heart": ["cardiovascular"],
    "cardiac": ["cardiovascular"],
    "lung": ["respiratory"],
    "pulmonary": ["respiratory"],
    "chest": ["respiratory", "cardiovascular"],
    "breath": ["respiratory"],
    "belly": ["abdomen"],
    "abdominal": ["abdomen"],
    "stomach": ["abdomen"],
    "GI": ["abdomen"],
    "neuro": ["neurological"],
    "brain": ["neurological"],
    "nerve": ["neurological"],
    "skin": ["dermatological"],
    "rash": ["dermatological"],
    "lesion": ["dermatological"],
    "eye": ["HEENT"],
    "ear": ["HEENT"],
    "throat": ["HEENT"],
    "neck": ["HEENT", "vascular"],
    "thyroid": ["HEENT", "endocrine"],
    "joint": ["musculoskeletal"],
    "knee": ["musculoskeletal"],
    "shoulder": ["musculoskeletal"],
    "spine": ["musculoskeletal", "neurological"],
    "back": ["musculoskeletal"],
    "artery": ["vascular"],
    "vein": ["vascular"],
    "pulse": ["vascular", "cardiovascular"],
    "blood pressure": ["cardiovascular", "vascular"],
    "sugar": ["endocrine"],
    "diabetes": ["endocrine"],
    "hormone": ["endocrine"],
}


def _load_findings() -> list[dict]:
    """Lazy-load the physical examination findings reference database."""
    global _FINDINGS
    if _FINDINGS is not None:
        return _FINDINGS
    try:
        with open(_FINDINGS_DB_PATH, "r", encoding="utf-8") as f:
            _FINDINGS = json.load(f)
    except Exception as exc:
        logger.error("Failed to load physical exam findings database: %s", exc)
        _FINDINGS = []
    return _FINDINGS


# ---------- text helpers ----------

def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").lower()).strip()


def _stem(token: str) -> str:
    if len(token) > 3 and token.endswith("s") and not token.endswith("ss"):
        return token[:-1]
    return token


def _tokenize(text: str) -> list[str]:
    raw = re.findall(r"[a-z0-9]+", _normalize(text))
    return [_stem(t) for t in raw]


# ---------- gate function ----------

def needs_physical_exam_data(query: str) -> bool:
    """Use GPT-4o to decide if a query involves physical examination findings interpretation."""
    try:
        client = openai.OpenAI()
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {
                    "role": "system",
                    "content": """You are a decision maker. Determine if a user query involves interpreting, explaining, or documenting physical examination findings.

Return ONLY "YES" for:
- Questions about physical exam findings (e.g., "what does an S3 gallop mean?")
- Requests to interpret exam results (e.g., "patient has crackles at bilateral bases")
- Clinical documentation of physical findings
- Questions about exam techniques or maneuvers
- Asking about significance of findings (murmurs, reflexes, palpation results, etc.)
- Requests to structure exam findings into notes or assessments
- Questions about normal vs abnormal exam findings
- Differential diagnosis based on physical findings

Return ONLY "NO" for:
- Lab result interpretation (blood tests, imaging reports)
- Medication questions
- Exercise or nutrition queries
- General health information not about physical examination
- Simple greetings or casual conversation

Examples:
- "What does a positive Babinski sign indicate?" → YES
- "I heard crackles in the lung bases, what could this mean?" → YES
- "Patient has JVD, S3, and bilateral edema" → YES
- "How do I perform the Romberg test?" → YES
- "What are my cholesterol levels?" → NO
- "Recommend a workout plan" → NO""",
                },
                {"role": "user", "content": f"Query: {query}"},
            ],
            temperature=0,
            max_tokens=3,
        )
        decision = response.choices[0].message.content.strip().upper()
        return decision == "YES"
    except Exception as exc:
        logger.error("Error in needs_physical_exam_data: %s", exc)
        return False


# ---------- search ----------

def search_findings(query: str, max_results: int = 8) -> list[dict]:
    """Search the findings reference database using keyword scoring."""
    findings = _load_findings()
    if not findings:
        return []

    normalized = _normalize(query)
    tokens = _tokenize(query)
    clean_tokens = {t for t in tokens if t not in _STOP_WORDS}

    if not clean_tokens:
        return []

    # Detect target body systems
    target_systems: set[str] = set()
    raw_tokens = set(re.findall(r"[a-z0-9]+", normalized))
    for synonym, systems in _SYSTEM_SYNONYMS.items():
        syn_tokens = set(_tokenize(synonym))
        if syn_tokens and syn_tokens.issubset(raw_tokens | clean_tokens):
            target_systems.update(s.lower() for s in systems)

    # Detect severity filter
    severity_filter = None
    if any(w in raw_tokens for w in ("urgent", "emergency", "critical", "emergent", "dangerous", "serious")):
        severity_filter = {"critical", "high"}

    scored: list[tuple[dict, float]] = []

    for finding in findings:
        score = 0.0

        # Finding name match (weight 5.0)
        name_tokens = set(_tokenize(finding.get("finding", "")))
        name_overlap = clean_tokens & name_tokens
        score += len(name_overlap) * 5.0

        # Alias match (weight 4.0)
        for alias in finding.get("aliases", []):
            alias_tokens = set(_tokenize(alias))
            alias_overlap = clean_tokens & alias_tokens
            if alias_overlap:
                score += len(alias_overlap) * 4.0

        # Description match (weight 2.0)
        desc_tokens = set(_tokenize(finding.get("description", "")))
        desc_overlap = clean_tokens & desc_tokens
        score += len(desc_overlap) * 2.0

        # System match (weight 3.0)
        finding_system = finding.get("system", "").lower()
        if target_systems and finding_system in target_systems:
            score += 3.0

        # Clinical significance keywords (weight 2.5)
        sig_text = " ".join(finding.get("clinical_significance", []))
        sig_tokens = set(_tokenize(sig_text))
        sig_overlap = clean_tokens & sig_tokens
        score += len(sig_overlap) * 2.5

        # Associated conditions match (weight 2.0)
        cond_text = " ".join(finding.get("associated_conditions", []))
        cond_tokens = set(_tokenize(cond_text))
        cond_overlap = clean_tokens & cond_tokens
        score += len(cond_overlap) * 2.0

        # Severity filter bonus
        if severity_filter and finding.get("severity_indicator") in severity_filter:
            score += 2.0

        if score > 0:
            scored.append((finding, score))

    scored.sort(key=lambda item: item[1], reverse=True)

    results = [finding for finding, _ in scored[:max_results]]

    # If no results from keyword matching but we have system targets, return all from that system
    if not results and target_systems:
        system_findings = [
            f for f in findings if f.get("system", "").lower() in target_systems
        ]
        results = system_findings[:max_results]

    return results


# ---------- formatting ----------

_SEVERITY_LABELS = {
    "critical": "CRITICAL — Requires urgent evaluation",
    "high": "HIGH — Warrants prompt further workup",
    "moderate": "MODERATE — Evaluate in clinical context",
    "low": "LOW — Usually benign, confirm with pattern recognition",
}


def format_finding_results(findings: list[dict]) -> str:
    """Format findings as structured markdown for LLM context injection."""
    if not findings:
        return ""

    sections = []
    for i, f in enumerate(findings, 1):
        name = f.get("finding", "Unknown")
        system = f.get("system", "").replace("_", " ").title()
        severity = f.get("severity_indicator", "moderate")
        severity_label = _SEVERITY_LABELS.get(severity, severity)

        section = f"### {i}. {name}\n"
        section += f"**System:** {system} | **Clinical Priority:** {severity_label}\n\n"

        # Description
        desc = f.get("description", "")
        if desc:
            section += f"**Description:** {desc}\n\n"

        # Technique
        technique = f.get("technique", "")
        if technique:
            section += f"**Examination Technique:** {technique}\n\n"

        # Normal variants FIRST — benign-first ordering to reduce anxiety
        normal = f.get("normal_variants", "")
        if normal:
            section += f"**Normal Variants / When This May Be Benign:** {normal}\n\n"

        # Clinical significance — ordered with common causes first
        significance = f.get("clinical_significance", [])
        if significance:
            section += "**Differential Considerations (common → less common):**\n"
            for item in significance:
                section += f"- {item}\n"
            section += "\n"

        # Follow-up assessments
        followup = f.get("follow_up_assessments", [])
        if followup:
            section += "**Suggested Follow-Up Assessments:**\n"
            for item in followup:
                section += f"- {item}\n"
            section += "\n"

        # Documentation note
        doc_note = f.get("documentation_note", "")
        if doc_note:
            section += f"**Documentation Guidance:** {doc_note}\n\n"

        # References
        refs = f.get("references", [])
        if refs:
            section += f"**References:** {'; '.join(refs)}\n"

        sections.append(section)

    header = f"**Physical Exam Findings Reference — {len(findings)} results:**\n\n"
    header += "_IMPORTANT INSTRUCTIONS FOR USING THIS REFERENCE:_\n"
    header += "- _ONLY use information contained in this reference when interpreting findings. Do NOT add conditions or associations from outside this data._\n"
    header += "- _Lead with Normal Variants (benign causes) BEFORE discussing serious possibilities._\n"
    header += "- _Present differential considerations from most common/benign to least common/serious._\n"
    header += "- _If the user's finding is not covered here, state that explicitly rather than guessing._\n"
    header += "- _This reference supports clinical reasoning and documentation — it is not a diagnostic tool._\n\n"

    footer = "\n\n---\n_All findings above must be interpreted by the treating clinician "
    footer += "in the context of the full clinical picture, history, and additional diagnostics._"

    return header + "\n---\n\n".join(sections) + footer


def format_structured_exam_note(findings: list[dict], query: str = "") -> str:
    """Format findings into a structured clinical documentation template.

    Organizes matched findings by body system for exam note integration.
    """
    if not findings:
        return ""

    # Group by system
    by_system: dict[str, list[dict]] = {}
    for f in findings:
        system = f.get("system", "other")
        by_system.setdefault(system, []).append(f)

    lines = ["## Structured Physical Examination Findings\n"]
    if query:
        lines.append(f"**Query/Context:** {query}\n")
    lines.append("_For clinical documentation support. Verify all findings against direct patient assessment._\n")

    system_order = [
        "HEENT", "cardiovascular", "respiratory", "abdomen",
        "neurological", "musculoskeletal", "dermatological",
        "vascular", "endocrine",
    ]

    for system in system_order:
        system_findings = by_system.get(system, [])
        if not system_findings:
            continue

        display_name = system.replace("_", " ").title()
        lines.append(f"\n### {display_name}")

        for f in system_findings:
            name = f.get("finding", "")
            severity = f.get("severity_indicator", "moderate")
            severity_icon = {"critical": "[!]", "high": "[*]", "moderate": "[-]", "low": "[ ]"}.get(severity, "[-]")
            lines.append(f"- {severity_icon} **{name}** — {f.get('description', '')[:120]}...")

            conditions = f.get("associated_conditions", [])
            if conditions:
                lines.append(f"  Consider: {', '.join(conditions[:5])}")

            followup = f.get("follow_up_assessments", [])
            if followup:
                lines.append(f"  Workup: {', '.join(followup[:4])}")

    lines.append("\n---")
    lines.append("_Priority key: [!] Critical/Urgent, [*] High, [-] Moderate, [ ] Low_")
    return "\n".join(lines)
