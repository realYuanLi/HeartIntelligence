"""General health Q&A: MedlinePlus topic search, XML parsing, result formatting.

Answers common health questions -- symptoms, conditions, medications, preventive
care, mental health, first aid -- by fetching credible information from the
NIH/NLM MedlinePlus Connect API (free, no API key required).

All outputs include a medical disclaimer reminding users to consult a healthcare
professional for personal medical advice.
"""

import logging
import re
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

import openai
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

_MEDLINEPLUS_BASE = "https://wsearch.nlm.nih.gov/ws/query"


# ---------- text helpers ----------

def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").lower()).strip()


def _strip_html(text: str) -> str:
    """Remove HTML tags from a string, preserving readable structure.

    Converts <p>, <li>, and <br> into line breaks so the result reads as
    structured text rather than a wall of words.
    """
    if not text:
        return ""
    # Insert newlines before structural tags so content stays readable
    result = re.sub(r"<br\s*/?>", "\n", text)
    result = re.sub(r"</p>", "\n\n", result)
    result = re.sub(r"</li>", "\n", result)
    result = re.sub(r"<li>", "- ", result)
    # Strip all remaining tags
    result = re.sub(r"<[^>]+>", "", result)
    # Collapse excessive blank lines but keep paragraph breaks
    result = re.sub(r"\n{3,}", "\n\n", result)
    return result.strip()


# ---------- search term extraction ----------

def _extract_medical_terms(query: str) -> str:
    """Use a lightweight LLM call to extract 1-3 medical keywords from a
    conversational query, so MedlinePlus returns relevant results.

    Falls back to the original query (normalized) on any error.
    """
    try:
        client = openai.OpenAI()
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Extract 1-3 concise medical search terms from the user's query. "
                        "Return ONLY the keywords, nothing else. Use standard medical topic "
                        "names that would appear in a health encyclopedia.\n\n"
                        "Examples:\n"
                        '- "What are the symptoms of strep throat?" -> strep throat\n'
                        '- "my head hurts really bad and I see spots" -> headache visual disturbances\n'
                        '- "How do I manage type 2 diabetes?" -> type 2 diabetes management\n'
                        '- "what are side effects of ibuprofen?" -> ibuprofen side effects\n'
                        '- "I feel anxious all the time and can\'t sleep" -> anxiety insomnia\n'
                        '- "how to treat a burn at home" -> burns first aid\n'
                        '- "what is melatonin used for?" -> melatonin\n'
                        '- "what causes high blood pressure" -> high blood pressure\n'
                    ),
                },
                {"role": "user", "content": query},
            ],
            temperature=0,
            max_tokens=20,
        )
        terms = response.choices[0].message.content.strip()
        if terms:
            return terms
    except Exception as exc:
        logger.warning("Medical term extraction failed, using raw query: %s", exc)
    return _normalize(query)


# ---------- gate function ----------

def needs_health_qa(query: str) -> bool:
    """Use GPT-4o to decide if a query is a general health question."""
    try:
        client = openai.OpenAI()
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {
                    "role": "system",
                    "content": """You are a decision maker. Determine if a user query is a general health question that would benefit from medical reference information.

Return ONLY "YES" for:
- Questions about symptoms, conditions, or diseases (e.g., "what is diabetes?")
- Questions about medications or treatments (e.g., "what are side effects of ibuprofen?")
- Preventive care questions (e.g., "how often should I get a flu shot?")
- Mental health questions (e.g., "what are signs of anxiety?")
- First aid questions (e.g., "how to treat a burn?")
- Questions about medical procedures or tests
- Questions about wellness and healthy living

Return ONLY "NO" for:
- Exercise or workout requests (handled by workout skill)
- Nutrition, diet, or meal planning queries (handled by nutrition skill)
- Physical exam finding interpretation (handled by physical exam skill)
- Personal health data queries like "show me my lab results" (handled by personal health context)
- Simple greetings or casual conversation
- Questions unrelated to health
- Requests to set reminders or manage plans

Examples:
- "What causes high blood pressure?" -> YES
- "What are the symptoms of strep throat?" -> YES
- "How do I manage type 2 diabetes?" -> YES
- "What is melatonin used for?" -> YES
- "What should I do for a sprained ankle?" -> YES
- "What are signs of depression?" -> YES
- "What are good chest exercises?" -> NO
- "What does an S3 gallop mean?" -> NO
- "Show me my lab results" -> NO
- "What foods are high in iron?" -> NO
- "Create a meal plan for weight loss" -> NO
- "Hello, how are you?" -> NO""",
                },
                {"role": "user", "content": f"Query: {query}"},
            ],
            temperature=0,
            max_tokens=3,
        )
        decision = response.choices[0].message.content.strip().upper()
        return decision == "YES"
    except Exception as exc:
        logger.error("Error in needs_health_qa: %s", exc)
        return False


# ---------- search ----------

def search_health_topics(query: str, max_results: int = 3) -> list[dict]:
    """Search MedlinePlus health topics for the given query.

    First extracts focused medical keywords from the conversational query,
    then calls the NLM MedlinePlus web service, parses the XML response, and
    returns a list of dicts with keys: title, url, summary, source,
    also_called, category.
    """
    if not query or not query.strip():
        return []

    max_results = max(1, max_results)

    # Extract focused medical terms instead of sending raw conversational query
    search_term = _extract_medical_terms(query)
    if not search_term:
        return []

    params = urllib.parse.urlencode({
        "db": "healthTopics",
        "term": search_term,
        "retmax": str(max_results),
    })
    url = f"{_MEDLINEPLUS_BASE}?{params}"

    try:
        req = urllib.request.Request(url, headers={"Accept": "application/xml"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            raw_xml = resp.read()
    except Exception as exc:
        logger.error("MedlinePlus API request failed: %s", exc)
        return []

    return _parse_medlineplus_xml(raw_xml, max_results)


def _parse_medlineplus_xml(raw_xml: bytes, max_results: int) -> list[dict]:
    """Parse MedlinePlus XML response into a list of topic dicts."""
    if not raw_xml:
        return []

    try:
        root = ET.fromstring(raw_xml)
    except ET.ParseError as exc:
        logger.error("Failed to parse MedlinePlus XML: %s", exc)
        return []

    # MedlinePlus returns <nlmSearchResult> with <list> containing <document>
    results: list[dict] = []
    for doc in root.iter("document"):
        if len(results) >= max_results:
            break

        title = ""
        summary = ""
        doc_url = doc.get("url", "")
        also_called: list[str] = []
        categories: list[str] = []

        for content in doc.iter("content"):
            name = content.get("name", "")
            text = _strip_html(content.text or "")
            if name == "title":
                title = text
            elif name == "FullSummary":
                summary = text
            elif name == "snippet":
                if not summary:
                    summary = text
            elif name == "altTitle":
                if text and text not in also_called:
                    also_called.append(text)
            elif name == "groupName":
                if text and text not in categories:
                    categories.append(text)

        if not title:
            continue

        # Truncate long summaries for context window efficiency
        if len(summary) > 1200:
            summary = summary[:1200].rsplit(" ", 1)[0] + "..."

        results.append({
            "title": title,
            "url": doc_url,
            "summary": summary,
            "source": "MedlinePlus (U.S. National Library of Medicine)",
            "also_called": ", ".join(also_called) if also_called else "",
            "category": ", ".join(categories) if categories else "",
        })

    return results


# ---------- emergency keywords ----------

_EMERGENCY_KEYWORDS = frozenset({
    "chest pain", "can't breathe", "difficulty breathing", "shortness of breath",
    "heart attack", "stroke", "seizure", "unconscious", "unresponsive",
    "severe bleeding", "choking", "overdose", "poisoning", "suicide",
    "suicidal", "self harm", "anaphylaxis", "allergic reaction severe",
})

_URGENT_KEYWORDS = frozenset({
    "high fever", "severe pain", "blood in stool", "blood in urine",
    "sudden vision loss", "severe headache worst", "confusion sudden",
    "numbness one side", "slurred speech", "swelling throat",
})


def _detect_urgency(query: str) -> str | None:
    """Return 'emergency' or 'urgent' if query contains crisis language."""
    q = _normalize(query)
    for phrase in _EMERGENCY_KEYWORDS:
        if phrase in q:
            return "emergency"
    for phrase in _URGENT_KEYWORDS:
        if phrase in q:
            return "urgent"
    return None


# ---------- follow-up suggestions ----------

def _generate_follow_ups(results: list[dict], query: str) -> list[str]:
    """Generate 2-3 natural follow-up questions based on the topic results."""
    if not results:
        return []

    primary = results[0]
    title = primary.get("title", "")
    category = primary.get("category", "")
    summary_lower = primary.get("summary", "").lower()

    suggestions = []

    # Pattern-based follow-up generation (no LLM call needed)
    if any(w in summary_lower for w in ("symptom", "sign")):
        suggestions.append(f"When should I see a doctor about {title.lower()}?")
    if any(w in summary_lower for w in ("treatment", "medicine", "medication", "drug")):
        suggestions.append(f"What are the treatment options for {title.lower()}?")
    if any(w in summary_lower for w in ("cause", "risk factor", "risk")):
        suggestions.append(f"How can I reduce my risk of {title.lower()}?")
    if any(w in summary_lower for w in ("prevent", "vaccine", "screening")):
        suggestions.append(f"What preventive steps can I take for {title.lower()}?")
    if any(w in summary_lower for w in ("child", "infant", "baby", "pediatric")):
        suggestions.append(f"How does {title.lower()} affect children differently?")

    # Always offer a "tell me more" option if we don't have enough
    if len(suggestions) < 2:
        suggestions.append(f"What should I know about living with {title.lower()}?")
    if len(suggestions) < 2:
        suggestions.append(f"What are common misconceptions about {title.lower()}?")

    return suggestions[:3]


# ---------- formatting ----------

_DISCLAIMER = (
    "This information is from MedlinePlus, a service of the U.S. National "
    "Library of Medicine. It is for informational purposes only and is not a "
    "substitute for professional medical advice, diagnosis, or treatment. "
    "Always consult a qualified healthcare provider with questions about "
    "a medical condition."
)


def format_health_results(results: list[dict], query: str = "") -> str:
    """Format health topic results as structured markdown for LLM context injection.

    Includes urgency warnings, follow-up suggestions, and medical disclaimer.
    """
    if not results:
        return ""

    parts = []

    # Emergency/urgency banner
    if query:
        urgency = _detect_urgency(query)
        if urgency == "emergency":
            parts.append(
                "**IMPORTANT: If this is a medical emergency, call 911 (or your "
                "local emergency number) or go to the nearest emergency room "
                "immediately. Do not wait.**\n"
            )
        elif urgency == "urgent":
            parts.append(
                "**Note: The symptoms described may need prompt medical attention. "
                "Consider contacting your healthcare provider or visiting an urgent "
                "care clinic today.**\n"
            )

    sections = []
    for i, topic in enumerate(results, 1):
        title = topic.get("title", "Unknown")
        url = topic.get("url", "")
        summary = topic.get("summary", "")
        source = topic.get("source", "")
        also_called = topic.get("also_called", "")
        category = topic.get("category", "")

        section = f"### {i}. {title}\n"
        if also_called:
            section += f"**Also known as:** {also_called}\n"
        if category:
            section += f"**Category:** {category}\n"
        section += "\n"

        if summary:
            section += f"{summary}\n\n"

        if url:
            section += f"**Learn more:** [{source}]({url})\n"

        sections.append(section)

    header = f"**Health Reference -- {len(results)} topic(s) found:**\n\n"
    parts.append(header + "\n---\n\n".join(sections))

    # Follow-up suggestions
    follow_ups = _generate_follow_ups(results, query)
    if follow_ups:
        parts.append("\n**Suggested follow-up questions for the user:**")
        for q in follow_ups:
            parts.append(f"- {q}")

    # Disclaimer
    parts.append(f"\n---\n_{_DISCLAIMER}_")

    return "\n".join(parts)
