"""
google_drive.py — Google Docs creation for Vlaamse Chroniqueur.

Public function:
    create_weekly_doc(week_start_date, script) → shareable URL string

Builds the document in four phases:
    1. Build the full text string, recording StyleEvent and ImageSlot positions
    2. Insert all text in one batchUpdate at index 1
    3. Apply all formatting in chunked batchUpdate calls (50 requests per batch)
    4. Insert images one at a time, backwards (highest index first)
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import date

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

SCOPES = [
    "https://www.googleapis.com/auth/documents",
    "https://www.googleapis.com/auth/drive",
]

BATCH_SIZE = 50
IMAGE_WIDTH_PT = 430
IMAGE_HEIGHT_PT = 260

# Colours (RGB 0-255)
COLOR_NAVY = (0x1A, 0x35, 0x69)       # HEADING_1 — section headers
COLOR_BURGUNDY = (0x61, 0x1E, 0x1E)   # HEADING_2 — subsection headers
COLOR_GREEN = (0x2D, 0x6A, 0x2D)      # Filming day headers
COLOR_STEEL = (0x1F, 0x5C, 0x99)      # Links
COLOR_GREY = (0x55, 0x55, 0x55)       # Location notes


@dataclass
class StyleEvent:
    start: int
    end: int
    named_style: str | None = None      # "TITLE", "HEADING_1", "HEADING_2", "NORMAL_TEXT"
    color_rgb: tuple | None = None       # (r, g, b) integers 0-255
    bold: bool = False
    italic: bool = False
    space_above_pt: int = 0
    space_below_pt: int = 0
    alignment: str | None = None        # "CENTER", "JUSTIFIED", "START"
    link_url: str | None = None


@dataclass
class ImageSlot:
    offset: int
    url: str


def create_weekly_doc(week_start_date: date, script: dict) -> str:
    """
    Create a new Google Doc with the weekly production package and return
    the shareable URL.
    """
    creds = _get_credentials()
    docs = build("docs", "v1", credentials=creds)
    drive = build("drive", "v3", credentials=creds)

    # Create empty document
    topic = script.get("topic", "Unknown Topic")
    date_str = week_start_date.strftime("%d %B %Y").lstrip("0") if hasattr(week_start_date, "strftime") else str(week_start_date)
    title = f"Vlaamse Chroniqueur \u2014 Week of {date_str}: {topic}"

    doc = docs.documents().create(body={"title": title}).execute()
    doc_id = doc["documentId"]
    print(f"Created Google Doc: {doc_id}")

    # Phase 1: Build text and collect style events / image slots
    full_text, style_events, image_slots = _build_document_text(week_start_date, script)

    # Phase 2: Insert all text at index 1
    _insert_text(docs, doc_id, full_text)

    # Phase 3: Apply formatting
    _apply_formatting(docs, doc_id, style_events)

    # Phase 4: Insert images (backwards)
    _insert_images(docs, doc_id, image_slots)

    # Move to folder and share
    folder_id = os.environ.get("GOOGLE_DRIVE_FOLDER_ID", "").strip()
    if folder_id:
        _move_to_folder(drive, doc_id, folder_id)

    return _make_shareable(drive, doc_id)


# ---------------------------------------------------------------------------
# Phase 1: Text assembly
# ---------------------------------------------------------------------------

def _build_document_text(
    week_start_date: date,
    script: dict,
) -> tuple[str, list[StyleEvent], list[ImageSlot]]:
    """
    Assemble the full document text and record all formatting events and
    image slot positions.
    """
    buf: list[str] = []
    events: list[StyleEvent] = []
    slots: list[ImageSlot] = []

    def pos() -> int:
        return sum(len(s) for s in buf)

    def add(text: str) -> None:
        buf.append(text)

    def heading1(text: str, color: tuple = COLOR_NAVY) -> None:
        start = pos()
        add(text + "\n")
        events.append(StyleEvent(
            start=start, end=pos(),
            named_style="HEADING_1", color_rgb=color,
            space_above_pt=20, space_below_pt=6, alignment="START",
        ))

    def heading2(text: str, color: tuple = COLOR_BURGUNDY) -> None:
        start = pos()
        add(text + "\n")
        events.append(StyleEvent(
            start=start, end=pos(),
            named_style="HEADING_2", color_rgb=color,
            space_above_pt=16, space_below_pt=4, alignment="START",
        ))

    def body(text: str, italic: bool = False, color: tuple | None = None) -> None:
        start = pos()
        add(text + "\n")
        events.append(StyleEvent(
            start=start, end=pos(),
            named_style="NORMAL_TEXT",
            italic=italic,
            color_rgb=color,
            space_below_pt=8,
            alignment="JUSTIFIED",
        ))

    def image_placeholder(url: str) -> None:
        start = pos()
        add("\n")
        events.append(StyleEvent(
            start=start, end=pos(),
            named_style="NORMAL_TEXT",
            alignment="CENTER",
            space_above_pt=10,
            space_below_pt=14,
        ))
        slots.append(ImageSlot(offset=start, url=url))

    def link_line(label: str, url: str) -> None:
        start = pos()
        add(f"{label}\n")
        events.append(StyleEvent(
            start=start, end=pos(),
            named_style="NORMAL_TEXT",
            italic=True,
            color_rgb=COLOR_STEEL,
            link_url=url,
            space_below_pt=18,
        ))

    # --- Title ---
    date_label = week_start_date.strftime("%d %B %Y").lstrip("0") if hasattr(week_start_date, "strftime") else str(week_start_date)
    topic_name = script.get("topic", "")
    title_start = pos()
    add(f"Vlaamse Chroniqueur \u2014 Week of {date_label}: {topic_name}\n")
    events.append(StyleEvent(
        start=title_start, end=pos(),
        named_style="TITLE",
        alignment="CENTER",
        space_below_pt=10,
    ))

    # --- Filming Schedule ---
    heading1("Filming Schedule")

    shooting_plan = script.get("shooting_plan", [])
    for i, day_plan in enumerate(shooting_plan):
        day_label = day_plan.get("day", "")
        day_date = day_plan.get("date", "")
        weather = day_plan.get("weather", {})
        condition = weather.get("condition", "unknown")
        temp = weather.get("temp_c")
        rain = weather.get("rain_mm", 0)
        recommended = day_plan.get("recommended", False)
        venue = day_plan.get("venue", "outdoor")

        temp_str = f"{temp}\u00b0C" if temp is not None else "?"
        heading2(
            f"{day_label} {day_date} \u2014 {condition} \u2014 {temp_str}",
            color=COLOR_GREEN,
        )

        body(f"Venue: {venue}")
        body(f"Rain: {rain} mm  |  Recommended: {'Yes' if recommended else 'No'}")

        indoor_alt = day_plan.get("indoor_alternative")
        if indoor_alt:
            body(f"Indoor alternative: {indoor_alt}", italic=True, color=COLOR_GREY)

        shots = day_plan.get("shots", [])
        if shots:
            body("Suggested shots:")
            for shot in shots:
                body(f"\u2022  {shot}")

        # Insert an image placeholder after the first filming day entry
        if i == 0 and script.get("image_urls"):
            first_url = script["image_urls"][0]
            if first_url:
                image_placeholder(first_url)

    image_urls = script.get("image_urls", [])
    image_idx = 1  # index 0 used in filming schedule

    def render_script_section(heading_label: str, script_content: dict) -> None:
        nonlocal image_idx

        heading1(heading_label)

        # Intro
        heading2("Intro")
        body(script_content.get("intro", ""))

        if image_idx < len(image_urls) and image_urls[image_idx]:
            image_placeholder(image_urls[image_idx])
            image_idx += 1

        # Sections
        for section in script_content.get("sections", []):
            heading2(section.get("title", ""))
            loc_notes = section.get("location_notes", "")
            if loc_notes:
                body(f"Locatie / Location: {loc_notes}", italic=True, color=COLOR_GREY)
            body(section.get("commentary", ""))

            if image_idx < len(image_urls) and image_urls[image_idx]:
                image_placeholder(image_urls[image_idx])
                image_idx += 1

        # Outro
        heading2("Outro")
        body(script_content.get("outro", ""))

    # --- Flemish Dutch script ---
    render_script_section("Script \u2014 Nederlands", script.get("script_nl", {}))

    # --- English script ---
    render_script_section("Script \u2014 English", script.get("script_en", {}))

    # --- Editing Guide ---
    heading1("Editing Guide")
    editing = script.get("editing_guide", {})

    heading2("Structure")
    body(editing.get("structure", ""))

    heading2("Transitions")
    body(editing.get("transitions", ""))

    b_roll = editing.get("b_roll_suggestions", [])
    if b_roll:
        heading2("B-Roll Suggestions")
        for item in b_roll:
            body(f"\u2022  {item}")

    heading2("Music Timing")
    body(editing.get("music_timing", ""))

    # --- Resources ---
    heading1("Resources")
    resources = script.get("resources", {})

    def resource_section(title: str, items: list[str]) -> None:
        if items:
            heading2(title)
            for item in items:
                body(f"\u2022  {item}")

    resource_section("Where to Find Footage", resources.get("footage_tips", []))
    resource_section("Music Suggestions", resources.get("music_suggestions", []))
    resource_section("Quotes and Sources", resources.get("quote_sources", []))
    resource_section("Archives", resources.get("archives", []))

    # Wikipedia link
    wiki_url = script.get("wikipedia_url", "")
    if wiki_url:
        link_line(f"Wikipedia: {topic_name}", wiki_url)

    full_text = "".join(buf)
    return full_text, events, slots


# ---------------------------------------------------------------------------
# Phase 2: Insert text
# ---------------------------------------------------------------------------

def _insert_text(docs, doc_id: str, text: str) -> None:
    docs.documents().batchUpdate(
        documentId=doc_id,
        body={
            "requests": [
                {
                    "insertText": {
                        "location": {"index": 1},
                        "text": text,
                    }
                }
            ]
        },
    ).execute()


# ---------------------------------------------------------------------------
# Phase 3: Apply formatting
# ---------------------------------------------------------------------------

def _apply_formatting(docs, doc_id: str, events: list[StyleEvent]) -> None:
    requests = []
    for ev in events:
        # Google Docs indices are 1-based after our text insert at index 1
        start = ev.start + 1
        end = ev.end + 1

        if ev.named_style:
            para_req: dict = {
                "paragraphStyle": {},
                "fields": "",
            }
            style_fields = []

            if ev.named_style:
                para_req["paragraphStyle"]["namedStyleType"] = ev.named_style
                style_fields.append("namedStyleType")

            if ev.alignment:
                para_req["paragraphStyle"]["alignment"] = ev.alignment
                style_fields.append("alignment")

            if ev.space_above_pt:
                para_req["paragraphStyle"]["spaceAbove"] = {
                    "magnitude": ev.space_above_pt, "unit": "PT"
                }
                style_fields.append("spaceAbove")

            if ev.space_below_pt:
                para_req["paragraphStyle"]["spaceBelow"] = {
                    "magnitude": ev.space_below_pt, "unit": "PT"
                }
                style_fields.append("spaceBelow")

            para_req["fields"] = ",".join(style_fields)
            requests.append({
                "updateParagraphStyle": {
                    "range": {"startIndex": start, "endIndex": end},
                    **para_req,
                }
            })

        # Text style (colour, bold, italic, link)
        text_style: dict = {}
        text_fields = []

        if ev.color_rgb:
            r, g, b = ev.color_rgb
            text_style["foregroundColor"] = {
                "color": {
                    "rgbColor": {
                        "red": r / 255,
                        "green": g / 255,
                        "blue": b / 255,
                    }
                }
            }
            text_fields.append("foregroundColor")

        if ev.bold:
            text_style["bold"] = True
            text_fields.append("bold")

        if ev.italic:
            text_style["italic"] = True
            text_fields.append("italic")

        if ev.link_url:
            text_style["link"] = {"url": ev.link_url}
            text_fields.append("link")

        if text_style:
            requests.append({
                "updateTextStyle": {
                    "range": {"startIndex": start, "endIndex": end},
                    "textStyle": text_style,
                    "fields": ",".join(text_fields),
                }
            })

    # Apply in chunks of BATCH_SIZE
    for i in range(0, len(requests), BATCH_SIZE):
        chunk = requests[i : i + BATCH_SIZE]
        docs.documents().batchUpdate(
            documentId=doc_id, body={"requests": chunk}
        ).execute()


# ---------------------------------------------------------------------------
# Phase 4: Insert images (backwards)
# ---------------------------------------------------------------------------

def _insert_images(docs, doc_id: str, slots: list[ImageSlot]) -> None:
    for slot in sorted(slots, key=lambda s: s.offset, reverse=True):
        try:
            docs.documents().batchUpdate(
                documentId=doc_id,
                body={
                    "requests": [
                        {
                            "insertInlineImage": {
                                "location": {"index": slot.offset + 1},
                                "uri": slot.url,
                                "objectSize": {
                                    "height": {"magnitude": IMAGE_HEIGHT_PT, "unit": "PT"},
                                    "width": {"magnitude": IMAGE_WIDTH_PT, "unit": "PT"},
                                },
                            }
                        }
                    ]
                },
            ).execute()
        except Exception as exc:
            print(f"Warning: Could not insert image {slot.url}: {exc}")


# ---------------------------------------------------------------------------
# Drive helpers
# ---------------------------------------------------------------------------

def _move_to_folder(drive, doc_id: str, folder_id: str) -> None:
    file_metadata = drive.files().get(
        fileId=doc_id, fields="parents"
    ).execute()
    current_parents = ",".join(file_metadata.get("parents", []))
    drive.files().update(
        fileId=doc_id,
        addParents=folder_id,
        removeParents=current_parents,
        fields="id, parents",
    ).execute()


def _make_shareable(drive, doc_id: str) -> str:
    drive.permissions().create(
        fileId=doc_id,
        body={"type": "anyone", "role": "reader"},
    ).execute()
    file_data = drive.files().get(
        fileId=doc_id, fields="webViewLink"
    ).execute()
    return file_data["webViewLink"]


def get_past_topics(folder_id: str) -> list[str]:
    """
    Return a list of past topic names, in creation order (oldest first), by
    reading the titles of Google Docs in the given Drive folder.

    Document titles follow the pattern:
        "Vlaamse Chroniqueur — Week of {date}: {topic}"

    Returns an empty list if the folder is empty, the env var is unset, or any
    error occurs during the Drive API call.
    """
    try:
        creds = _get_credentials()
        drive = build("drive", "v3", credentials=creds)
        results = drive.files().list(
            q=(
                f"'{folder_id}' in parents "
                "and mimeType='application/vnd.google-apps.document' "
                "and trashed=false"
            ),
            fields="files(name, createdTime)",
            orderBy="createdTime asc",
            pageSize=100,
        ).execute()
    except Exception as exc:
        print(f"Warning: Could not fetch past topics from Drive: {exc}")
        return []

    topics: list[str] = []
    for f in results.get("files", []):
        name = f.get("name", "")
        # Parse "Vlaamse Chroniqueur — Week of ...: {topic}"
        if ":" in name:
            topic = name.split(":", 1)[1].strip()
            if topic:
                topics.append(topic)
    return topics


def _get_credentials() -> Credentials:
    creds = Credentials(
        token=None,
        refresh_token=os.environ["GOOGLE_REFRESH_TOKEN"],
        token_uri="https://oauth2.googleapis.com/token",
        client_id=os.environ["GOOGLE_CLIENT_ID"],
        client_secret=os.environ["GOOGLE_CLIENT_SECRET"],
        scopes=SCOPES,
    )
    creds.refresh(Request())
    return creds
