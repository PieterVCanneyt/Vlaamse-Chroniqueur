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
REQUIRED_SCRIPT_KEYS = {"shooting_plan", "script_nl", "script_en", "editing_guide", "resources"}
REQUIRED_INNER_SCRIPT_KEYS = {"intro", "sections", "outro"}
REQUIRED_SECTION_KEYS = {"title", "commentary", "location_notes"}


def select_topic(week_start_date: date, past_topics: list[str] | None = None) -> dict:
    """
    Ask Claude to pick one Flemish history topic for the week.

    If past_topics is provided, Claude will suggest the next topic in
    chronological order so viewers build context episode by episode.

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
        "CHRONOLOGICAL ORDER: The channel covers Flemish history in chronological order. "
        "The list of already-published topics will be provided. You must pick the next "
        "logical topic that follows chronologically, so viewers build context step by step. "
        "If no past topics exist, start from the earliest Flemish history.\n\n"
        "Respond with ONLY a valid JSON object. No prose before or after."
    )

    past_section = ""
    if past_topics:
        listed = "\n".join(f"  {i + 1}. {t}" for i, t in enumerate(past_topics))
        past_section = (
            f"\nTopics already published (in order):\n{listed}\n\n"
            "Pick the next topic that follows chronologically from the last one above. "
            "Make sure viewers of the previous episode will have useful context for this one.\n"
        )

    user_msg = (
        f"Week starting: {week_start_date.strftime('%A %d %B %Y')}\n"
        f"{past_section}\n"
        "Return JSON only:\n"
        "{\n"
        '  "topic": "Name of the topic (e.g., \'Gravensteen Castle\')",\n'
        '  "location": "Specific filming location (e.g., \'Sint-Veerleplein 11, 9000 Ghent\')",\n'
        '  "period": "Historical era and dates (e.g., \'Medieval, c. 1180-1350\')",\n'
        '  "wikipedia_url": "https://en.wikipedia.org/wiki/EXACT_ARTICLE_TITLE",\n'
        '  "wikimedia_search_query": "3-5 search keywords for Wikimedia Commons images",\n'
        '  "rationale": "One sentence explaining why this follows chronologically"\n'
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


def generate_script(topic: dict, filming_day: dict) -> dict:
    """
    Generate the full weekly production package in two API calls:
      1. Dutch package: script_nl + shooting_plan + editing_guide + resources
      2. English script: script_en (separate call to stay within token limits)

    Returns a merged dict with all five keys.
    """
    print("      Generating Dutch script + production package...")
    package = _generate_dutch_package(topic, filming_day)

    print("      Generating English script...")
    script_en = _generate_english_script(topic, package["script_nl"])
    package["script_en"] = script_en

    _validate_script(package)
    return package


def _generate_dutch_package(topic: dict, filming_day: dict) -> dict:
    """
    Call 1: Flemish Dutch script + shooting plan + editing guide + resources.
    Returns dict with keys: shooting_plan, script_nl, editing_guide, resources.
    """
    client = _build_client()
    venue = "outdoor" if filming_day.get("outdoor_ok", True) else "indoor"

    system_msg = (
        "You are the scriptwriter for 'Vlaamse Chroniqueur', een Vlaamse geschiedeniskanal op YouTube.\n\n"
        "Schrijf in de stijl van Dan Jones (maar dan in het Nederlands):\n"
        "- Concrete namen, data en cijfers — niet 'veel soldaten' maar 'ongeveer 4.000 man'\n"
        "- Menselijke schaal — hoe voelde het om er zelf bij te zijn?\n"
        "- Korte declaratieve zinnen afgewisseld met langere\n"
        "- Geen superlatieven ('de grootste', 'veranderde alles voorgoed')\n"
        "- Historische context zonder te vervallen in een lezing\n\n"
        "De presentator filmt op ÉÉN dag deze week. Dag en weer zijn opgegeven.\n\n"
        f"Filmlocatie deze week: {venue}. "
        + (
            "Regen > 2 mm — stel een relevante binnenlocatie voor (nabijgelegen museum, archief, "
            "bibliotheek of kerk die verband houdt met het onderwerp)."
            if venue == "indoor"
            else "Het weer is geschikt voor buiten filmen op de locatie."
        )
        + "\n\n"
        "Doellengte: ~1.600 woorden gesproken commentaar (130 wpm × 12 min).\n"
        "Verdeling: intro ~200 woorden, 4-5 secties ~300 woorden elk, outro ~150 woorden.\n"
        "Schrijf in warm, natuurlijk Vlaams Nederlands — niet formeel Hollands.\n\n"
        "Antwoord met ALLEEN een geldig JSON-object. Geen tekst ervoor of erna."
    )

    user_msg = (
        f"Onderwerp:\n{json.dumps(topic, indent=2, ensure_ascii=False)}\n\n"
        f"Filmdag en weersomstandigheden:\n{json.dumps(filming_day, indent=2)}\n\n"
        "Genereer het volledige weekelijkse productiepakket als één JSON-object.\n"
        "Gebruik precies deze structuur:\n\n"
        "{\n"
        '  "shooting_plan": [\n'
        "    {\n"
        '      "day": "Maandag / Woensdag / Vrijdag",\n'
        '      "date": "YYYY-MM-DD",\n'
        '      "weather": {"condition": "...", "temp_c": N, "rain_mm": N},\n'
        '      "venue": "outdoor of indoor",\n'
        '      "shots": [\n'
        '        "Brede establishingshot van de hoofdgevel",\n'
        '        "Close-up van de toegangspoort",\n'
        '        "Wandelend shot langs de noordmuur"\n'
        "      ],\n"
        '      "indoor_alternative": null\n'
        "    }\n"
        "  ],\n"
        '  "script_nl": {\n'
        '    "intro": "Volledige gesproken intro (~200 woorden) in Vlaams Nederlands.",\n'
        '    "sections": [\n'
        "      {\n"
        '        "title": "Sectietitel",\n'
        '        "commentary": "Volledige gesproken commentaar (~300 woorden) in Vlaams Nederlands.",\n'
        '        "location_notes": "Sta op [specifieke plek]. Kadreer [kenmerk] over je linkerschouder."\n'
        "      }\n"
        "    ],\n"
        '    "outro": "Volledige gesproken outro (~150 woorden) in Vlaams Nederlands."\n'
        "  },\n"
        '  "editing_guide": {\n'
        '    "structure": "Beschrijf de algehele montageflow.",\n'
        '    "transitions": "Aanbevelingen voor overgangsstijl.",\n'
        '    "b_roll_suggestions": [\n'
        '      "Drone-opname boven het dak bij gouden uur"\n'
        "    ],\n"
        '    "music_timing": "Wanneer muziek aanzwelt, wegvalt of stilte beter werkt."\n'
        "  },\n"
        '  "resources": {\n'
        '    "footage_tips": [\n'
        '      "Beeldbank Erfgoed Gent: https://beeldbank.gent.be — historische foto\'s"\n'
        "    ],\n"
        '    "music_suggestions": [\n'
        '      "Free Music Archive — Medieval Flanders genre tag"\n'
        "    ],\n"
        '    "quote_sources": [\n'
        '      "Primaire bron en auteur als een citaat wordt gebruikt"\n'
        "    ],\n"
        '    "archives": [\n'
        '      "Stadsarchief Gent — originele bouwrecords uit de 12de eeuw"\n'
        "    ]\n"
        "  }\n"
        "}\n\n"
        "Regels:\n"
        "- shooting_plan heeft precies ÉÉN item voor de filmdag hierboven.\n"
        "- Als venue 'indoor' is, zet indoor_alternative op een string die de specifieke "
        "binnenlocatie beschrijft en waarom die relevant is voor het onderwerp."
    )

    message = client.messages.create(
        model=MODEL,
        max_tokens=8192,
        system=system_msg,
        messages=[{"role": "user", "content": user_msg}],
    )
    if message.stop_reason == "max_tokens":
        raise ValueError(
            "_generate_dutch_package: response was cut off (max_tokens reached)."
        )
    raw = message.content[0].text
    data = _parse_json_response(raw, context="_generate_dutch_package")

    required = {"shooting_plan", "script_nl", "editing_guide", "resources"}
    _validate_keys(data, required, context="dutch_package")
    _validate_keys(data["script_nl"], REQUIRED_INNER_SCRIPT_KEYS, context="script_nl")
    return data


def _generate_english_script(topic: dict, script_nl: dict) -> dict:
    """
    Call 2: English-language script only, using the Dutch script's section
    structure for consistency. Returns a script dict with intro/sections/outro.
    """
    client = _build_client()

    # Pass section titles and location notes from the Dutch script so the
    # English version uses the same structure and shot descriptions.
    section_structure = [
        {"title": s.get("title", ""), "location_notes": s.get("location_notes", "")}
        for s in script_nl.get("sections", [])
    ]

    system_msg = (
        "You are the scriptwriter for 'Vlaamse Chroniqueur', a Flemish history YouTube channel.\n\n"
        "Write in the style of Dan Jones:\n"
        "- Concrete names, dates, and numbers — not 'many soldiers' but 'around 4,000 men'\n"
        "- Human scale — what did it feel like to be there?\n"
        "- Short declarative sentences alongside longer ones\n"
        "- No breathless superlatives ('the greatest', 'forever changed history')\n"
        "- Historical context without turning it into a lecture\n\n"
        "Target length: ~1,600 words total (130 wpm × 12 min).\n"
        "Word distribution: intro ~200 words, sections ~300 words each, outro ~150 words.\n\n"
        "Respond with ONLY a valid JSON object. No prose before or after."
    )

    user_msg = (
        f"Topic:\n{json.dumps(topic, indent=2, ensure_ascii=False)}\n\n"
        "Write the English script for this video. Use exactly the same sections as the "
        "Dutch script (same titles translated to English, same location notes translated "
        "to English). Cover the same historical content.\n\n"
        f"Section structure from Dutch script:\n{json.dumps(section_structure, indent=2, ensure_ascii=False)}\n\n"
        "Return JSON only:\n"
        "{\n"
        '  "intro": "Full spoken intro (~200 words).",\n'
        '  "sections": [\n'
        "    {\n"
        '      "title": "Section title in English",\n'
        '      "commentary": "Full spoken commentary (~300 words).",\n'
        '      "location_notes": "Stand at [specific spot]. Frame [feature] over your left shoulder."\n'
        "    }\n"
        "  ],\n"
        '  "outro": "Full spoken outro (~150 words)."\n'
        "}"
    )

    message = client.messages.create(
        model=MODEL,
        max_tokens=8192,
        system=system_msg,
        messages=[{"role": "user", "content": user_msg}],
    )
    if message.stop_reason == "max_tokens":
        raise ValueError(
            "_generate_english_script: response was cut off (max_tokens reached)."
        )
    raw = message.content[0].text
    data = _parse_json_response(raw, context="_generate_english_script")
    _validate_keys(data, REQUIRED_INNER_SCRIPT_KEYS, context="script_en")
    return data


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
    for lang_key in ("script_nl", "script_en"):
        _validate_keys(data[lang_key], REQUIRED_INNER_SCRIPT_KEYS, context=f"{lang_key}")
        for i, section in enumerate(data[lang_key].get("sections", [])):
            _validate_keys(section, REQUIRED_SECTION_KEYS, context=f"{lang_key}.sections[{i}]")
