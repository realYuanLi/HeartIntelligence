"""dreamchat CLI -- command dispatcher.

Usage:
    dreamchat [--json] server status
    dreamchat [--json] health status
    dreamchat [--json] health trends
    dreamchat [--json] reminders list
    dreamchat [--json] heartbeat status
    dreamchat [--json] digest daily
    dreamchat [--json] chat ask "question" [--image path]
    dreamchat [--json] chat history
    dreamchat [--json] chat reset
    dreamchat configure
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime

from dreamchat.client import DreamChatClient, DreamChatError, load_config, save_config


# ---------------------------------------------------------------------------
# ANSI colors (only when stdout is a terminal)
# ---------------------------------------------------------------------------

_USE_COLOR = hasattr(sys.stdout, "isatty") and sys.stdout.isatty()


def _c(code: str, text: str) -> str:
    """Wrap text in ANSI escape codes if color is enabled."""
    if not _USE_COLOR:
        return text
    return f"\033[{code}m{text}\033[0m"


def _bold(text: str) -> str:
    return _c("1", text)


def _blue(text: str) -> str:
    return _c("1;34", text)


def _green(text: str) -> str:
    return _c("32", text)


def _red(text: str) -> str:
    return _c("1;31", text)


def _dim(text: str) -> str:
    return _c("2", text)


def _cyan(text: str) -> str:
    return _c("36", text)


# ---------------------------------------------------------------------------
# Output helpers
# ---------------------------------------------------------------------------

def _out(data: dict, as_json: bool) -> None:
    """Print result in --json or human-friendly format."""
    if as_json:
        print(json.dumps({"ok": True, "data": data}, indent=2))
    else:
        _print_human(data)


def _err(msg: str, as_json: bool) -> None:
    if as_json:
        print(json.dumps({"ok": False, "error": msg}, indent=2))
    else:
        print(f"{_red('Error')}: {msg}", file=sys.stderr)
    sys.exit(1)


def _print_human(data: dict, indent: int = 0) -> None:
    """Best-effort human-readable output."""
    prefix = "  " * indent
    for k, v in data.items():
        label = _blue(k)
        if isinstance(v, dict):
            print(f"{prefix}{label}:")
            _print_human(v, indent + 1)
        elif isinstance(v, list):
            print(f"{prefix}{label}: {_dim(f'({len(v)} items)')}")
            for i, item in enumerate(v[:5]):
                if isinstance(item, dict):
                    print(f"{prefix}  {_dim(f'[{i}]')}")
                    _print_human(item, indent + 2)
                else:
                    print(f"{prefix}  - {item}")
            if len(v) > 5:
                print(f"{prefix}  {_dim(f'... and {len(v) - 5} more')}")
        else:
            print(f"{prefix}{label}: {v}")


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

def cmd_configure(_args: argparse.Namespace) -> None:
    """Interactive configuration."""
    cfg = load_config()
    print(_bold("DREAM-Chat CLI Configuration"))
    print(_dim("Press Enter to keep current value.") + "\n")

    url = input(f"  {_blue('Server URL')} [{cfg.get('base_url', 'http://localhost:8000')}]: ").strip()
    if url:
        cfg["base_url"] = url

    email = input(f"  {_blue('Email')} [{cfg.get('email', '')}]: ").strip()
    if email:
        cfg["email"] = email

    password = input(f"  {_blue('Password')} [****]: ").strip()
    if password:
        cfg["password"] = password

    save_config(cfg)
    from dreamchat.client import CONFIG_FILE
    print(f"\n{_green('Saved')} to {CONFIG_FILE}. Testing connection...")

    client = DreamChatClient()
    status = client.server_status()
    if status.get("status") == "healthy":
        print(f"{_green('OK')} Server is reachable.")
    else:
        print(f"{_red('Warning')}: server returned {status}")


def cmd_server_status(args: argparse.Namespace) -> None:
    client = DreamChatClient()
    result = client.server_status()
    if result.get("error"):
        _err(f"Server unreachable: {result['error']}", args.json)
    if not args.json:
        status = result.get("status", "unknown")
        tag = _green("healthy") if status == "healthy" else _red(status)
        patient = result.get("patient_name", "")
        print(f"{_blue('Server')}: {tag}")
        if patient:
            print(f"{_blue('Patient')}: {_bold(patient)}")
        for k, v in result.items():
            if k not in ("status", "patient_name"):
                print(f"{_blue(k)}: {v}")
    else:
        _out(result, args.json)


def cmd_health_status(args: argparse.Namespace) -> None:
    client = DreamChatClient()
    mobile = client.health_data()
    if not mobile.get("success"):
        _err(mobile.get("message", "Failed to fetch health data"), args.json)

    data = mobile.get("data", {})
    summary: dict = {}

    # Heart rate
    hr = data.get("heart_rate", {})
    if hr.get("has_data") and hr.get("daily_stats"):
        latest = hr["daily_stats"][-1] if hr["daily_stats"] else {}
        summary["heart_rate"] = {
            "date": latest.get("date", ""),
            "avg": latest.get("avg"),
            "min": latest.get("min"),
            "max": latest.get("max"),
        }

    # Blood pressure
    bp = data.get("blood_pressure", {})
    if bp.get("has_data") and bp.get("readings"):
        latest = bp["readings"][-1] if bp["readings"] else {}
        summary["blood_pressure"] = latest

    # HRV
    hrv = data.get("hrv", {})
    if hrv.get("has_data") and hrv.get("daily_averages"):
        latest = hrv["daily_averages"][-1] if hrv["daily_averages"] else {}
        summary["hrv"] = latest

    # Steps
    activity = data.get("activity", {})
    if activity.get("has_data") and activity.get("daily_steps"):
        latest = activity["daily_steps"][-1] if activity["daily_steps"] else {}
        summary["steps"] = latest

    summary["date_range"] = data.get("date_range", {})

    _out(summary, args.json)


def cmd_health_trends(args: argparse.Namespace) -> None:
    client = DreamChatClient()
    mobile = client.health_data()
    if not mobile.get("success"):
        _err(mobile.get("message", "Failed to fetch health data"), args.json)

    data = mobile.get("data", {})
    trends: dict = {"date_range": data.get("date_range", {})}

    for key in ("heart_rate", "blood_pressure", "hrv", "activity"):
        section = data.get(key, {})
        if section.get("has_data"):
            trends[key] = section.get("trends", section)

    _out(trends, args.json)


def cmd_reminders_list(args: argparse.Namespace) -> None:
    client = DreamChatClient()
    result = client.cron_jobs()
    if not result.get("success"):
        _err(result.get("message", "Failed to fetch reminders"), args.json)

    jobs = result.get("jobs", [])
    # Filter to enabled jobs only for the summary
    summary = []
    for job in jobs:
        summary.append({
            "job_id": job.get("job_id"),
            "message": job.get("message", "")[:80],
            "schedule_type": job.get("schedule_type"),
            "enabled": job.get("enabled", True),
            "time_of_day": job.get("time_of_day"),
            "frequency": job.get("frequency"),
        })
    _out({"reminders": summary, "total": len(jobs)}, args.json)


def cmd_heartbeat_status(args: argparse.Namespace) -> None:
    client = DreamChatClient()
    result = client.heartbeat_status()
    if not result.get("success"):
        _err(result.get("message", "Failed to fetch heartbeat status"), args.json)
    _out(result.get("status", {}), args.json)


def cmd_digest_daily(args: argparse.Namespace) -> None:
    client = DreamChatClient()

    digest: dict = {"generated_at": datetime.now().isoformat()}

    # Health status
    mobile = client.health_data()
    if mobile.get("success"):
        data = mobile.get("data", {})
        metrics: dict = {}
        hr = data.get("heart_rate", {})
        if hr.get("has_data") and hr.get("daily_stats"):
            latest = hr["daily_stats"][-1]
            metrics["heart_rate_avg"] = latest.get("avg")
        bp = data.get("blood_pressure", {})
        if bp.get("has_data") and bp.get("readings"):
            latest = bp["readings"][-1]
            metrics["blood_pressure"] = latest
        activity = data.get("activity", {})
        if activity.get("has_data") and activity.get("daily_steps"):
            latest = activity["daily_steps"][-1]
            metrics["steps"] = latest.get("steps")
        digest["health_metrics"] = metrics

    # Reminders
    cron = client.cron_jobs()
    if cron.get("success"):
        jobs = cron.get("jobs", [])
        active = [j for j in jobs if j.get("enabled", True)]
        digest["active_reminders"] = len(active)
        digest["upcoming"] = [
            {"message": j.get("message", "")[:60],
             "time": j.get("time_of_day") or j.get("scheduled_at", "")}
            for j in active[:5]
        ]

    # Heartbeat
    hb = client.heartbeat_status()
    if hb.get("success"):
        status = hb.get("status", {})
        digest["heartbeat"] = {
            "enabled": status.get("enabled", False),
            "messages_today": status.get("messages_today", 0),
            "last_message": status.get("last_message_preview"),
        }

    _out(digest, args.json)


def cmd_chat_ask(args: argparse.Namespace) -> None:
    client = DreamChatClient()
    message = args.message
    if not message:
        _err("No message provided", args.json)

    if not args.json:
        print(_dim("Thinking..."), end="", flush=True)

    result = client.chat(message, image_path=args.image)

    if not args.json:
        print("\r" + " " * 20 + "\r", end="", flush=True)

    if not result.get("success"):
        _err(result.get("assistant_message") or result.get("message", "Chat failed"),
             args.json)

    data: dict = {"response": result.get("assistant_message", "")}
    if result.get("exercise_images"):
        data["exercise_images"] = result["exercise_images"]

    if args.json:
        _out(data, args.json)
    else:
        print(data["response"])
        if data.get("exercise_images"):
            print(f"\n{_dim('Exercise images:')}")
            for img in data["exercise_images"]:
                print(f"  {_cyan(img)}")


def cmd_chat_history(args: argparse.Namespace) -> None:
    client = DreamChatClient()
    sid = client.ensure_session()
    result = client.get_session(sid)
    if not result.get("success"):
        _err(result.get("message", "Failed to fetch history"), args.json)

    conversation = result.get("conversation", [])
    # Return last N messages (keep it concise for CLI)
    recent = conversation[-20:]
    _out({"session_id": sid, "messages": recent,
          "total": len(conversation)}, args.json)


def cmd_chat_reset(args: argparse.Namespace) -> None:
    client = DreamChatClient()
    sid = client.reset_session()
    if args.json:
        _out({"session_id": sid, "message": "New session created"}, args.json)
    else:
        print(f"{_green('OK')} New session created {_dim(f'({sid})')}")


# ---------------------------------------------------------------------------
# Argument parser
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="dreamchat",
        description="CLI for DREAM-Chat health AI",
    )
    parser.add_argument("--json", action="store_true",
                        help="Output in JSON format (for machine consumption)")

    sub = parser.add_subparsers(dest="command")

    # -- configure --
    sub.add_parser("configure", help="Set up server URL and credentials")

    # -- server --
    srv = sub.add_parser("server", help="Server operations")
    srv_sub = srv.add_subparsers(dest="server_cmd")
    srv_sub.add_parser("status", help="Check if server is running")

    # -- health --
    health = sub.add_parser("health", help="Health data queries")
    health_sub = health.add_subparsers(dest="health_cmd")
    health_sub.add_parser("status", help="Current health metrics snapshot")
    health_sub.add_parser("trends", help="7-day health trends")

    # -- reminders --
    rem = sub.add_parser("reminders", help="Reminder management")
    rem_sub = rem.add_subparsers(dest="reminders_cmd")
    rem_sub.add_parser("list", help="List all reminders")

    # -- heartbeat --
    hb = sub.add_parser("heartbeat", help="Proactive messaging status")
    hb_sub = hb.add_subparsers(dest="heartbeat_cmd")
    hb_sub.add_parser("status", help="Current heartbeat status")

    # -- digest --
    dig = sub.add_parser("digest", help="Health digests")
    dig_sub = dig.add_subparsers(dest="digest_cmd")
    dig_sub.add_parser("daily", help="Daily health summary")

    # -- chat --
    chat = sub.add_parser("chat", help="Conversational health AI")
    chat_sub = chat.add_subparsers(dest="chat_cmd")

    ask = chat_sub.add_parser("ask", help="Ask a health question")
    ask.add_argument("message", nargs="?", help="The question to ask")
    ask.add_argument("--image", help="Path to image file (e.g., food photo)")

    chat_sub.add_parser("history", help="Show recent conversation")
    chat_sub.add_parser("reset", help="Start a fresh conversation")

    return parser


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)

    if not hasattr(args, "json"):
        args.json = False

    dispatch = {
        "configure": cmd_configure,
        "server": {
            "status": cmd_server_status,
        },
        "health": {
            "status": cmd_health_status,
            "trends": cmd_health_trends,
        },
        "reminders": {
            "list": cmd_reminders_list,
        },
        "heartbeat": {
            "status": cmd_heartbeat_status,
        },
        "digest": {
            "daily": cmd_digest_daily,
        },
        "chat": {
            "ask": cmd_chat_ask,
            "history": cmd_chat_history,
            "reset": cmd_chat_reset,
        },
    }

    if not args.command:
        parser.print_help()
        sys.exit(1)

    handler = dispatch.get(args.command)
    if handler is None:
        parser.print_help()
        sys.exit(1)

    try:
        if isinstance(handler, dict):
            sub_cmd = getattr(args, f"{args.command}_cmd", None)
            if sub_cmd and sub_cmd in handler:
                handler[sub_cmd](args)
            else:
                parser.parse_args([args.command, "--help"])
        else:
            handler(args)
    except DreamChatError as exc:
        _err(str(exc), args.json)
    except SystemExit:
        raise
    except Exception as exc:
        _err(str(exc) or type(exc).__name__, args.json)


if __name__ == "__main__":
    main()
