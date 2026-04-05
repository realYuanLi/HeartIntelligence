"""MCP server exposing DREAM-Chat health AI as structured tools.

Registers with OpenClaw so the agent gets a first-class tool instead of
relying on shell `exec` commands and AGENTS.md instructions.

Supports:
- Image input: food photos forwarded from WhatsApp for calorie analysis
- Image output: exercise images returned alongside text responses

Usage:
    python -m dreamchat.mcp_server          # stdio transport (for OpenClaw)
    dreamchat-mcp                           # via entry point script
"""

from __future__ import annotations

import base64
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from mcp.server.fastmcp import FastMCP
from mcp.types import ImageContent, TextContent

from dreamchat.client import DreamChatClient, DreamChatError

mcp = FastMCP(
    "dreamchat-health",
    instructions=(
        "Personal health AI with access to the user's medical records, "
        "wearable data (heart rate, blood pressure, sleep, steps), nutrition, "
        "exercise plans, and clinical guardrails. Use this tool for ANY "
        "health-related question. Present the response directly to the user "
        "without modification."
    ),
)


def _fetch_image_as_base64(base_url: str, path: str) -> tuple[str, str] | None:
    """Fetch an image from the Flask server and return (base64_data, mime_type).

    Returns None if the image can't be fetched.
    """
    url = base_url.rstrip("/") + "/" + path.lstrip("/")
    try:
        req = Request(url, method="GET")
        resp = urlopen(req, timeout=10)
        data = resp.read()
        content_type = resp.headers.get("Content-Type", "image/gif")
        mime = content_type.split(";")[0].strip()
        return base64.b64encode(data).decode(), mime
    except (HTTPError, URLError, OSError):
        return None


@mcp.tool()
def health_ask(question: str, image_base64: str | None = None,
               image_mime_type: str | None = None) -> list[TextContent | ImageContent]:
    """Ask the user's personal health AI a question.

    Routes through their medical records, wearable data, and clinical
    guardrails. Returns a natural-language response ready to send to the user.

    Use for: health questions, symptoms, medications, heart rate, blood
    pressure, sleep, steps, nutrition, exercise, lab results, conditions.

    For food photo analysis, pass the image as base64 with its MIME type.

    Args:
        question: The health question to ask.
        image_base64: Optional base64-encoded image data (e.g., food photo).
        image_mime_type: MIME type of the image (e.g., "image/jpeg"). Required
            if image_base64 is provided.
    """
    if not question or not question.strip():
        return [TextContent(type="text", text="Error: No question provided.")]

    image_data_uri = None
    if image_base64:
        mime = image_mime_type or "image/jpeg"
        image_data_uri = f"data:{mime};base64,{image_base64}"

    try:
        client = DreamChatClient(source="whatsapp")
        result = client.chat(question.strip(), image_data_uri=image_data_uri)
    except DreamChatError as exc:
        return [TextContent(type="text", text=f"Health system error: {exc}")]
    except Exception as exc:
        return [TextContent(type="text", text=f"Health system unavailable: {exc}")]

    if not result.get("success"):
        error = result.get("message") or result.get("assistant_message") or "unknown error"
        return [TextContent(type="text", text=f"Health system error: {error}")]

    response = result.get("assistant_message", "")
    if not response:
        return [TextContent(type="text",
                            text="The health system processed your question but returned no response.")]

    # Build response: text first, then any exercise images
    parts: list[TextContent | ImageContent] = [
        TextContent(type="text", text=response)
    ]

    exercise_images = result.get("exercise_images", [])
    if exercise_images:
        base_url = client.base_url
        for img in exercise_images:
            url = img if isinstance(img, str) else img.get("url", "")
            if not url:
                continue
            fetched = _fetch_image_as_base64(base_url, url)
            if fetched:
                b64_data, mime = fetched
                parts.append(ImageContent(type="image", data=b64_data, mimeType=mime))

    return parts


@mcp.tool()
def health_status() -> str:
    """Get current health metrics snapshot (heart rate, blood pressure, steps, HRV).

    Returns structured health data. Use health_ask for questions that need
    clinical reasoning or personalized advice.
    """
    try:
        client = DreamChatClient(source="whatsapp")
        mobile = client.health_data()
    except DreamChatError as exc:
        return f"Health system error: {exc}"
    except Exception as exc:
        return f"Health system unavailable: {exc}"

    if not mobile.get("success"):
        return f"Failed to fetch health data: {mobile.get('message', 'unknown')}"

    data = mobile.get("data", {})
    lines = []

    hr = data.get("heart_rate", {})
    if hr.get("has_data") and hr.get("daily_stats"):
        latest = hr["daily_stats"][-1]
        lines.append(
            f"Heart rate: avg {latest.get('avg')} bpm "
            f"(min {latest.get('min')}, max {latest.get('max')}) "
            f"on {latest.get('date', 'today')}"
        )

    bp = data.get("blood_pressure", {})
    if bp.get("has_data") and bp.get("readings"):
        latest = bp["readings"][-1]
        lines.append(
            f"Blood pressure: {latest.get('systolic')}/{latest.get('diastolic')} mmHg"
        )

    hrv = data.get("hrv", {})
    if hrv.get("has_data") and hrv.get("daily_averages"):
        latest = hrv["daily_averages"][-1]
        lines.append(f"HRV: {latest.get('avg')} ms")

    activity = data.get("activity", {})
    if activity.get("has_data") and activity.get("daily_steps"):
        latest = activity["daily_steps"][-1]
        lines.append(f"Steps: {latest.get('steps')}")

    if not lines:
        return "No health data available."

    return "\n".join(lines)


def main():
    """Run the MCP server over stdio."""
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
