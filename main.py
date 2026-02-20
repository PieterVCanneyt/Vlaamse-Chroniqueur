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

import os
import sys
import time
import traceback
from datetime import date, timedelta

from dotenv import load_dotenv

from discord_notifier import post_to_discord
from generator import generate_script, select_topic
from google_drive import create_weekly_doc, get_past_topics
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
        # Step 1: Load past topics for chronological continuity
        folder_id = os.environ.get("GOOGLE_DRIVE_FOLDER_ID", "").strip()
        past_topics: list[str] = []
        if folder_id:
            print("\n[0/6] Loading past topics from Google Drive...")
            past_topics = get_past_topics(folder_id)
            if past_topics:
                print(f"      {len(past_topics)} past topic(s) found; last: {past_topics[-1]}")
            else:
                print("      No past topics found — starting from the beginning.")

        # Step 1: Select topic
        print("\n[1/6] Selecting topic...")
        topic = select_topic(monday, past_topics)

        # Step 2: Geocode the filming location
        print(f"\n[2/6] Geocoding location: {topic['location']}")
        try:
            lat, lon = geocode_location(topic["location"])
            print(f"      Coordinates: {lat:.4f}, {lon:.4f}")
        except ValueError as exc:
            print(f"Warning: {exc}")
            print("      Falling back to Ghent coordinates (51.0543, 3.7174).")
            lat, lon = 51.0543, 3.7174

        # Step 3: Fetch weather and pick the best single filming day
        print("\n[3/6] Fetching weather forecast...")
        weather_data = get_weekly_weather(lat, lon, filming_dates)
        for w in weather_data:
            status = "outdoor OK" if w.get("outdoor_ok") else "indoor recommended"
            print(f"      {w['date']}: {w.get('condition', '?')} {w.get('temp_c', '?')}°C "
                  f"| rain {w.get('rain_mm', '?')} mm | {status}")

        best_day = _select_best_filming_day(weather_data)
        print(f"      → Best day: {best_day['date']} ({best_day.get('condition', '?')}, "
              f"{'outdoor' if best_day.get('outdoor_ok') else 'indoor'})")

        # Step 4: Generate full script for the chosen day
        print("\n[4/6] Generating full script...")
        script = generate_script(topic, best_day)
        # Propagate topic-level fields into the script dict for downstream use
        script["topic"] = topic.get("topic", "")
        script["location"] = topic.get("location", "")
        script["period"] = topic.get("period", "")
        script["wikipedia_url"] = topic.get("wikipedia_url", "")

        # Step 5: Find Wikimedia images
        print("\n[5/6] Searching for images...")
        image_queries = _build_image_queries(topic)
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


def _select_best_filming_day(weather_data: list[dict]) -> dict:
    """
    Pick the single best filming day from Mon/Wed/Fri weather options.
    Prefers outdoor-ok days; among ties, lowest rain then highest temperature.
    Falls back to the least-rainy day if all are indoor.
    """
    outdoor = [w for w in weather_data if w.get("outdoor_ok")]
    pool = outdoor if outdoor else weather_data
    return min(pool, key=lambda w: (w.get("rain_mm") or 999, -(w.get("temp_c") or 0)))


def _build_image_queries(topic: dict) -> list[str]:
    """
    Build a list of short Wikimedia Commons search queries (2-4 keywords each).
    Wikimedia search matches against file names and descriptions, so brevity wins.
    """
    seen: set[str] = set()
    queries: list[str] = []

    def add(q: str) -> None:
        q = q.strip()
        if q and q not in seen:
            seen.add(q)
            queries.append(q)

    # Primary query from the topic (Claude is asked to keep this to 3-5 keywords)
    add(topic.get("wikimedia_search_query", ""))

    # Topic name alone — often matches image file names directly
    topic_name = topic.get("topic", "").strip()
    add(topic_name)

    # Location name alone (first two words)
    location = topic.get("location", "").strip()
    location_short = " ".join(location.split(",")[0].split()[:3])
    add(location_short)

    # Historical period keyword(s) + topic name
    period = topic.get("period", "").strip()
    period_keyword = period.split(",")[0].split()[0] if period else ""
    if period_keyword and topic_name:
        add(f"{topic_name} {period_keyword}")

    return queries[:5]  # cap at 5 images


if __name__ == "__main__":
    main()
