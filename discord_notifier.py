"""
discord_notifier.py — Discord webhook notification for Vlaamse Chroniqueur.

Public function:
    post_to_discord(week_start_date, script, doc_url)

Posts a plain-text message to the configured Discord webhook with the
topic, filming schedule summary, and a link to the Google Doc.
"""

from __future__ import annotations

import os
from datetime import date

import requests

REQUEST_TIMEOUT = 10


def post_to_discord(week_start_date: date, script: dict, doc_url: str) -> None:
    """
    Send a summary message to the Discord webhook.
    Raises requests.HTTPError on non-2xx response.
    """
    webhook_url = os.environ.get("DISCORD_WEBHOOK_URL", "").strip()
    if not webhook_url:
        print("Warning: DISCORD_WEBHOOK_URL is not set. Skipping Discord notification.")
        return

    message = _build_message(week_start_date, script, doc_url)

    resp = requests.post(
        webhook_url,
        json={"content": message},
        timeout=REQUEST_TIMEOUT,
    )
    resp.raise_for_status()
    print("Discord notification sent.")


def _build_message(week_start_date: date, script: dict, doc_url: str) -> str:
    monday_str = week_start_date.strftime("%d %B %Y").lstrip("0")
    topic = script.get("topic", "Unknown Topic")
    period = script.get("period", "")
    location = script.get("location", "")

    lines = [
        f"**Vlaamse Chroniqueur \u2014 Week of {monday_str}**",
        "",
        f"Topic: {topic} ({period})" if period else f"Topic: {topic}",
    ]

    if location:
        lines.append(f"Location: {location}")

    filming_lines = []
    for day_plan in script.get("shooting_plan", []):
        day = day_plan.get("day", "")
        day_date = day_plan.get("date", "")
        weather = day_plan.get("weather", {})
        condition = weather.get("condition", "unknown")
        temp = weather.get("temp_c")
        venue = day_plan.get("venue", "outdoor")

        temp_str = f"{temp}\u00b0C" if temp is not None else "?"
        filming_lines.append(f"  {day} {day_date}: {condition} {temp_str} \u2014 {venue}")

    if filming_lines:
        lines.append("")
        lines.append("Filming days:")
        lines.extend(filming_lines)

    lines.extend([
        "",
        "Full script + editing guide:",
        doc_url,
    ])

    return "\n".join(lines)
