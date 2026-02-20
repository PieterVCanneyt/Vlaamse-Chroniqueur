"""
main.py — Vlaamse Chroniqueur weekly YouTube script generator.

Pipeline:
    1. Compute the upcoming Mon/Wed/Fri filming dates
    2. Ask Claude to select a Flemish history topic (step 1)
    3. Geocode the topic location to get lat/lon
    4. Fetch weather at the topic location for each filming date
    5. Ask Claude to generate the full script + production package (step 2)
    6. Find Wikimedia Commons images for the topic
    7. Create a formatted Google Doc
    8. Post a summary to Discord
"""

from __future__ import annotations

import sys
import time
import traceback
from datetime import date, timedelta

from dotenv import load_dotenv

from discord_notifier import post_to_discord
from generator import generate_script, select_topic
from google_drive import create_weekly_doc
from weather import geocode_location, get_weekly_weather
from wikimedia import find_image_url

# Courtesy delay between Wikimedia API calls (seconds)
WIKIMEDIA_DELAY = 0.5


def main() -> None:
    load_dotenv()

    today = date.today()
    filming_dates = get_upcoming_filming_dates(today)
    monday = filming_dates[0]

    print(f"Vlaamse Chroniqueur — generating script for week of {monday.isoformat()}")
    print(f"Filming dates: {[d.isoformat() for d in filming_dates]}")

    try:
        # Step 1: Select topic
        print("\n[1/6] Selecting topic...")
        topic = select_topic(monday)

        # Step 2: Geocode the filming location
        print(f"\n[2/6] Geocoding location: {topic['location']}")
        try:
            lat, lon = geocode_location(topic["location"])
            print(f"      Coordinates: {lat:.4f}, {lon:.4f}")
        except ValueError as exc:
            print(f"Warning: {exc}")
            print("      Falling back to Ghent coordinates (51.0543, 3.7174).")
            lat, lon = 51.0543, 3.7174

        # Step 3: Fetch weather at the filming location
        print(f"\n[3/6] Fetching weather forecast...")
        weather_data = get_weekly_weather(lat, lon, filming_dates)
        for w in weather_data:
            status = "outdoor OK" if w.get("outdoor_ok") else "INDOOR recommended"
            print(f"      {w['date']}: {w.get('condition', '?')} {w.get('temp_c', '?')}°C "
                  f"| rain {w.get('rain_mm', '?')} mm | {status}")

        # Step 4: Generate full script
        print("\n[4/6] Generating full script...")
        # Merge weather data back into the topic for the generator
        full_topic = {**topic}
        script = generate_script(full_topic, weather_data)
        # Propagate topic-level fields into the script dict for downstream use
        script["topic"] = topic.get("topic", "")
        script["location"] = topic.get("location", "")
        script["period"] = topic.get("period", "")
        script["wikipedia_url"] = topic.get("wikipedia_url", "")

        # Step 5: Find Wikimedia images
        print("\n[5/6] Searching for images...")
        image_queries = _build_image_queries(topic, script)
        image_urls: list[str | None] = []
        for query in image_queries:
            url = find_image_url(query)
            status = "found" if url else "not found"
            print(f"      '{query}' → {status}")
            image_urls.append(url)
            time.sleep(WIKIMEDIA_DELAY)
        script["image_urls"] = image_urls

        # Step 6: Create Google Doc
        print("\n[6/6] Creating Google Doc...")
        doc_url = create_weekly_doc(monday, script)
        print(f"      Doc URL: {doc_url}")

        # Step 7: Notify Discord (non-fatal)
        print("\n[7/7] Posting to Discord...")
        try:
            post_to_discord(monday, script, doc_url)
        except Exception as discord_exc:
            print(f"Warning: Discord notification failed: {discord_exc}")

        print(f"\nDone. Script ready for week of {monday.isoformat()}.")

    except Exception:
        print("\n--- Pipeline failed ---", file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
        sys.exit(1)


def get_upcoming_filming_dates(run_date: date) -> list[date]:
    """
    Return [Monday, Wednesday, Friday] of the upcoming week.
    Works correctly whether run on Sunday (scheduled) or any other day (manual).
    """
    days_until_monday = (7 - run_date.weekday()) % 7
    if days_until_monday == 0:
        # Today is Monday — target next Monday, not today
        days_until_monday = 7
    monday = run_date + timedelta(days=days_until_monday)
    return [monday, monday + timedelta(days=2), monday + timedelta(days=4)]


def _build_image_queries(topic: dict, script: dict) -> list[str]:
    """
    Build a list of Wikimedia Commons search queries: one for the topic
    overall and one per script section (up to 4 images total).
    """
    queries: list[str] = []

    # Primary query from topic
    primary = topic.get("wikimedia_search_query", "").strip()
    if primary:
        queries.append(primary)

    # One query per section, derived from the section title + topic
    topic_name = topic.get("topic", "")
    for section in script.get("script", {}).get("sections", [])[:3]:
        section_title = section.get("title", "").strip()
        if section_title and topic_name:
            queries.append(f"{topic_name} {section_title}")

    return queries[:5]  # cap at 5 images


if __name__ == "__main__":
    main()
