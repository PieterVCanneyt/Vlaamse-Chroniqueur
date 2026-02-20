# CLAUDE.md

This file provides guidance to Claude Code when working in this repository.

## Project Overview

A weekly script generator for a Flemish History YouTube channel called "Vlaamse Chroniqueur".
Each week the script:
1. Has Claude (`claude-sonnet-4-6`) automatically select a Flemish history topic (city, building, monument, battlefield, etc.)
2. Geocodes the filming location and fetches weather for the next Mon/Wed/Fri from Open-Meteo
3. Generates a complete 10-15 minute YouTube script — commentary, shooting plan, editing guide, and resource tips
4. Finds relevant Wikimedia Commons images
5. Creates a formatted Google Doc in Google Drive
6. Posts a summary to Discord via webhook

Runs automatically every Sunday at 08:00 UTC via GitHub Actions, planning the upcoming week.

The host films on **Monday, Wednesday, and Friday**. Rain > 2 mm at the filming location → recommend indoor alternative (museum, archive, library, church).

## Tech Stack

- Language: Python 3.11+
- AI: Anthropic API (`claude-sonnet-4-6`)
- Weather: Open-Meteo API (free, no API key — geocoding + forecast)
- Storage: Google Docs + Google Drive API (OAuth 2.0 with stored refresh token)
- Images: Wikimedia Commons API (JPEG/PNG only, < 25 MB)
- Notifications: Discord webhook (plain-text message with topic + filming schedule + doc link)
- CI/CD: GitHub Actions (weekly cron, Sunday 08:00 UTC)

## File Structure

```
.
├── main.py                      # Entry point — orchestrates the full pipeline
├── generator.py                 # Two-step Anthropic API calls: topic selection + script generation
├── weather.py                   # Open-Meteo geocoding + weather forecast
├── wikimedia.py                 # Wikimedia Commons image search
├── google_drive.py              # Google Docs creation (four-phase build) and Drive upload
├── discord_notifier.py          # Discord webhook posting
├── auth_setup.py                # One-time OAuth token setup (run locally)
├── requirements.txt
├── .env.example                 # Template for local secrets
├── .gitignore
└── .github/
    └── workflows/
        └── weekly.yml           # GitHub Actions cron (Sunday 08:00 UTC)
```

## Pipeline (main.py)

1. `get_upcoming_filming_dates(today)` → [Monday, Wednesday, Friday] of the upcoming week
2. `select_topic(monday)` → topic dict from Claude (step 1)
3. `geocode_location(topic["location"])` → (latitude, longitude) via Open-Meteo geocoding
4. `get_weekly_weather(lat, lon, dates)` → weather at the filming location for each day
5. `generate_script(topic, weather)` → full production package dict from Claude (step 2)
6. `find_image_url(query)` × up to 5 → Wikimedia image URLs attached to script
7. `create_weekly_doc(monday, script)` → formatted Google Doc, returns shareable URL
8. `post_to_discord(monday, script, doc_url)` → Discord message (non-fatal if it fails)

## Script Dict Shape

```python
{
    # From topic selection (step 1)
    "topic": "Gravensteen Castle",
    "location": "Sint-Veerleplein 11, 9000 Ghent",
    "period": "Medieval, c. 1180-1350",
    "wikipedia_url": "https://en.wikipedia.org/wiki/...",
    "wikimedia_search_query": "Gravensteen castle Ghent Belgium",

    # From script generation (step 2)
    "shooting_plan": [
        {
            "day": "Monday",
            "date": "2026-02-23",
            "weather": {"condition": "partly cloudy", "temp_c": 8, "rain_mm": 0.5},
            "recommended": True,
            "venue": "outdoor",
            "shots": ["Wide establishing shot", "Close-up of stonework"],
            "indoor_alternative": None
        }
    ],
    "script": {
        "intro": "~200 words spoken intro",
        "sections": [
            {
                "title": "Section title",
                "commentary": "~300 words spoken commentary",
                "location_notes": "Stand at X, frame Y over left shoulder"
            }
        ],
        "outro": "~150 words spoken outro"
    },
    "editing_guide": {
        "structure": "...",
        "transitions": "...",
        "b_roll_suggestions": [...],
        "music_timing": "..."
    },
    "resources": {
        "footage_tips": [...],
        "music_suggestions": [...],
        "quote_sources": [...],
        "archives": [...]
    },

    # Added by main.py
    "image_urls": ["https://upload.wikimedia.org/...", ...]
}
```

## Google Docs Build Strategy

`google_drive.py` populates a doc in four phases:
1. Build the full text string, recording `StyleEvent` and `ImageSlot` positions (char offsets)
2. Insert all text in one `batchUpdate` at index 1
3. Apply all formatting in chunked `batchUpdate` calls (50 requests per batch)
4. Insert images one at a time, going **backwards** (highest index first) so earlier
   indices stay valid after each insertion

## Google Docs Design

**Typography hierarchy**
- Title (`TITLE` style): centred, 10 pt gap below
- Section header (`HEADING_1`): deep navy `#1A3569`, 20 pt above / 6 pt below
- Subsection header (`HEADING_2`): dark burgundy `#611E1E`, 16 pt above / 4 pt below
- Filming day header (`HEADING_2`): forest green `#2D6A2D`, 16 pt above / 4 pt below
- Body (`NORMAL_TEXT`): justified, 8 pt between paragraphs
- Location notes: grey `#555555`, italic
- Links (Wikipedia): italic, steel blue `#1F5C99`, 18 pt below

**Images**
- JPEG/PNG from Wikimedia Commons (≤ 25 MB)
- Each image lives in its own isolated paragraph (centred, 10 pt above, 14 pt below)
- Images are inserted last, working backwards (430 × 260 pt display size)

**Auth**
- Uses OAuth 2.0 with a long-lived refresh token (not a service account)
- Run `python auth_setup.py` once locally to obtain the three Google secrets

## Secrets (GitHub Actions secrets + local `.env`)

- `ANTHROPIC_API_KEY`
- `GOOGLE_CLIENT_ID` — from the OAuth 2.0 client credential
- `GOOGLE_CLIENT_SECRET` — from the OAuth 2.0 client credential
- `GOOGLE_REFRESH_TOKEN` — obtained by running `auth_setup.py` once
- `GOOGLE_DRIVE_FOLDER_ID` — ID from the target folder's URL (optional)
- `DISCORD_WEBHOOK_URL`

## Development Commands

```bash
# Install dependencies
pip install -r requirements.txt

# One-time: set up Google OAuth (run locally, needs client_secrets.json)
python auth_setup.py

# Run locally (reads from .env)
python main.py
```

## Writing Style Guide

Dan Jones style means:
- Concrete names, dates, and numbers — not "many soldiers" but "around 4,000 men"
- Human scale — what did it feel like to be there?
- Short declarative sentences alongside longer ones
- No breathless superlatives ("the greatest", "forever changed")
- Context given without turning into a lecture

## Do's and Don'ts

- Always use model `claude-sonnet-4-6`
- Always build one fresh doc per week — never append to an existing one
- Never hallucinate Wikipedia URLs — only link to known, substantial articles
- Never commit `.env` or any `*.json` file (covered by `.gitignore`)
- Never catch bare `except:` — always name the exception type
