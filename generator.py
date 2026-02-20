"""
generator.py — Anthropic API calls for Vlaamse Chroniqueur.

Two-step pipeline:
  1. select_topic(week_start_date)       → topic dict
  2. generate_script(topic, weather)     → full production package dict

Both steps use claude-sonnet-4-6.
"""

from __future__ import annotations

import json
import os
import re
from datetime import date

import anthropic

MODEL = "claude-sonnet-4-6"

REQUIRED_TOPIC_KEYS = {"topic", "location", "period", "wikipedia_url", "wikimedia_search_query"}
REQUIRED_SCRIPT_KEYS = {"shooting_plan", "script", "editing_guide", "resources"}
REQUIRED_INNER_SCRIPT_KEYS = {"intro", "sections", "outro"}
REQUIRED_SECTION_KEYS = {"title", "commentary", "location_notes"}


def select_topic(week_start_date: date) -> dict:
    """
    Ask Claude to pick one Flemish history topic for the week.

    Returns a dict with keys:
        topic, location, period, wikipedia_url, wikimedia_search_query, rationale
    """
    client = _build_client()

    system_msg = (
        "You are a researcher for 'Vlaamse Chroniqueur', a Flemish history YouTube channel. "
        "Each week the host films on location in Flanders (modern Belgium, primarily "
        "Ghent, Bruges, Antwerp, Ypres, Mechelen, or surrounding rural areas).\n\n"
        "Your task: select ONE topic for this week's video.\n\n"
        "The topic must be:\n"
        "- A specific city district, building, monument, battlefield, castle, abbey, canal, "
        "market square, or historical event rooted in Flanders\n"
        "- Visually compelling — the host will film on location, so there must be something "
        "to point a camera at\n"
        "- Historically rich enough to fill 10-15 minutes of commentary (~1,600 spoken words)\n"
        "- Spanning any era from Roman Flanders through the 20th century\n"
        "- Not a generic national topic — keep it specifically Flemish\n\n"
        "Respond with ONLY a valid JSON object. No prose before or after."
    )

    user_msg = (
        f"Week starting: {week_start_date.strftime('%A %d %B %Y')}\n\n"
        "Pick one Flemish history topic for this week's video. Return JSON only:\n"
        "{\n"
        '  "topic": "Name of the topic (e.g., \'Gravensteen Castle\')",\n'
        '  "location": "Specific filming location (e.g., \'Sint-Veerleplein 11, 9000 Ghent\')",\n'
        '  "period": "Historical era and dates (e.g., \'Medieval, c. 1180-1350\')",\n'
        '  "wikipedia_url": "https://en.wikipedia.org/wiki/EXACT_ARTICLE_TITLE",\n'
        '  "wikimedia_search_query": "3-5 search keywords for Wikimedia Commons images",\n'
        '  "rationale": "One sentence explaining why this topic suits this week"\n'
        "}\n\n"
        "Important: only include a wikipedia_url if you are certain the article exists "
        "and covers this topic substantively. When in doubt, use: "
        "\"https://en.wikipedia.org/wiki/Flanders\""
    )

    message = client.messages.create(
        model=MODEL,
        max_tokens=512,
        system=system_msg,
        messages=[{"role": "user", "content": user_msg}],
    )

    raw = message.content[0].text
    topic = _parse_json_response(raw, context="select_topic")
    _validate_keys(topic, REQUIRED_TOPIC_KEYS, context="topic")
    print(f"Topic selected: {topic['topic']} — {topic.get('rationale', '')}")
    return topic


def generate_script(topic: dict, weather_data: list[dict]) -> dict:
    """
    Ask Claude to write the full weekly production package.

    Returns a dict with keys:
        shooting_plan, script (intro/sections/outro), editing_guide, resources
    """
    client = _build_client()

    system_msg = (
        "You are the scriptwriter for 'Vlaamse Chroniqueur', a Flemish history YouTube channel.\n\n"
        "Write in the style of Dan Jones:\n"
        "- Concrete names, dates, and numbers — not 'many soldiers' but 'around 4,000 men'\n"
        "- Human scale — what did it feel like to be there?\n"
        "- Short declarative sentences alongside longer ones\n"
        "- No breathless superlatives ('the greatest', 'forever changed history')\n"
        "- Historical context without turning it into a lecture\n\n"
        "The host films on Monday, Wednesday, and Friday each week. "
        "Weather data for the upcoming filming days is provided.\n\n"
        "Target length: ~1,600 words of spoken commentary total (130 wpm × 12 min).\n"
        "Word distribution: intro ~200 words, 4-5 sections ~300 words each, outro ~150 words.\n\n"
        "Filming rule: if rain_mm > 2.0, recommend an indoor venue (nearby museum, archive, "
        "library, or church related to the topic). Otherwise recommend outdoor filming.\n\n"
        "Respond with ONLY a valid JSON object. No prose before or after."
    )

    user_msg = (
        f"Topic:\n{json.dumps(topic, indent=2, ensure_ascii=False)}\n\n"
        f"Filming days and weather forecast:\n{json.dumps(weather_data, indent=2)}\n\n"
        "Generate the complete weekly production package as a single JSON object.\n"
        "Use this exact structure:\n\n"
        "{\n"
        '  "shooting_plan": [\n'
        "    {\n"
        '      "day": "Monday",\n'
        '      "date": "YYYY-MM-DD",\n'
        '      "weather": {"condition": "...", "temp_c": N, "rain_mm": N},\n'
        '      "recommended": true,\n'
        '      "venue": "outdoor",\n'
        '      "shots": [\n'
        '        "Wide establishing shot of the main facade",\n'
        '        "Close-up of the entrance stonework"\n'
        "      ],\n"
        '      "indoor_alternative": null\n'
        "    }\n"
        "  ],\n"
        '  "script": {\n'
        '    "intro": "Full spoken intro (~200 words). Greet viewers and set the scene.",\n'
        '    "sections": [\n'
        "      {\n"
        '        "title": "Section title",\n'
        '        "commentary": "Full spoken commentary (~300 words).",\n'
        '        "location_notes": "Stand at [specific spot]. Frame [feature] over your left shoulder."\n'
        "      }\n"
        "    ],\n"
        '    "outro": "Full spoken outro (~150 words). Close with a reflection and call to action."\n'
        "  },\n"
        '  "editing_guide": {\n'
        '    "structure": "Describe the overall edit flow.",\n'
        '    "transitions": "Specific transition style recommendations.",\n'
        '    "b_roll_suggestions": [\n'
        '      "Drone shot over the roofline at golden hour"\n'
        "    ],\n"
        '    "music_timing": "Where music swells, drops, or silence works better."\n'
        "  },\n"
        '  "resources": {\n'
        '    "footage_tips": [\n'
        '      "Beeldbank Erfgoed Gent: https://beeldbank.gent.be — historical photos"\n'
        "    ],\n"
        '    "music_suggestions": [\n'
        '      "Free Music Archive — Medieval Flanders genre tag"\n'
        "    ],\n"
        '    "quote_sources": [\n'
        '      "Primary source title and author if a direct quote is used"\n'
        "    ],\n"
        '    "archives": [\n'
        '      "Stadsarchief Gent — original building records from the 12th century"\n'
        "    ]\n"
        "  }\n"
        "}\n\n"
        "For shooting_plan entries where venue is 'indoor', set indoor_alternative to a string "
        "describing the specific indoor venue and why it relates to the topic."
    )

    message = client.messages.create(
        model=MODEL,
        max_tokens=8192,
        system=system_msg,
        messages=[{"role": "user", "content": user_msg}],
    )

    if message.stop_reason == "max_tokens":
        raise ValueError(
            "generate_script: Claude response was cut off (max_tokens reached). "
            "The script may be too long. Try reducing the requested word count."
        )

    raw = message.content[0].text
    script = _parse_json_response(raw, context="generate_script")
    _validate_script(script)
    return script


def _build_client() -> anthropic.Anthropic:
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY environment variable is not set.")
    return anthropic.Anthropic(api_key=api_key)


def _parse_json_response(raw: str, context: str) -> dict:
    """
    Extract JSON from a Claude response, stripping markdown code fences if present.
    Raises ValueError with context and raw text on parse failure.
    """
    if not raw or not raw.strip():
        raise ValueError(
            f"JSON parse failure in {context}: Claude returned an empty response.\n"
            "Check that the API key is valid and the model is available."
        )

    # Try to extract from ```json ... ``` or ``` ... ``` fences first
    fenced = re.search(r"```(?:json)?\s*([\s\S]*?)```", raw)
    if fenced:
        candidate = fenced.group(1).strip()
        if not candidate:
            # Fences found but empty content — fall back to raw
            candidate = raw.strip()
    else:
        candidate = raw.strip()

    # If there's prose before the JSON, try to find the first '{' or '['
    if candidate and candidate[0] not in ("{", "["):
        brace_pos = candidate.find("{")
        bracket_pos = candidate.find("[")
        start = min(
            brace_pos if brace_pos != -1 else len(candidate),
            bracket_pos if bracket_pos != -1 else len(candidate),
        )
        if start < len(candidate):
            candidate = candidate[start:]

    try:
        return json.loads(candidate)
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"JSON parse failure in {context}.\n"
            f"Error: {exc}\n"
            f"Raw response:\n{raw}"
        ) from exc


def _validate_keys(data: dict, required: set[str], context: str) -> None:
    missing = required - set(data.keys())
    if missing:
        raise ValueError(f"Missing keys in {context}: {missing}")


def _validate_script(data: dict) -> None:
    _validate_keys(data, REQUIRED_SCRIPT_KEYS, context="script root")
    _validate_keys(data["script"], REQUIRED_INNER_SCRIPT_KEYS, context="script.script")
    for i, section in enumerate(data["script"].get("sections", [])):
        _validate_keys(section, REQUIRED_SECTION_KEYS, context=f"script.script.sections[{i}]")
