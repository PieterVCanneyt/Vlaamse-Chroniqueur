"""
Weather module for Vlaamse Chroniqueur.

Provides two public functions:
  - geocode_location(location_name) → (latitude, longitude)
  - get_weekly_weather(lat, lon, filming_dates) → list of weather dicts

Uses Open-Meteo (free, no API key required) for both geocoding and forecasting.
"""

from __future__ import annotations

from datetime import date

import requests

GEOCODING_URL = "https://geocoding-api.open-meteo.com/v1/search"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
RAIN_THRESHOLD_MM = 2.0
REQUEST_TIMEOUT = 10

# WMO Weather Interpretation Codes (WW codes)
WMO_CODE_MAP: dict[int, str] = {
    0: "clear sky",
    1: "mainly clear",
    2: "partly cloudy",
    3: "overcast",
    45: "fog",
    48: "rime fog",
    51: "light drizzle",
    53: "moderate drizzle",
    55: "dense drizzle",
    56: "light freezing drizzle",
    57: "dense freezing drizzle",
    61: "slight rain",
    63: "moderate rain",
    65: "heavy rain",
    66: "light freezing rain",
    67: "heavy freezing rain",
    71: "slight snow",
    73: "moderate snow",
    75: "heavy snow",
    77: "snow grains",
    80: "slight rain showers",
    81: "moderate rain showers",
    82: "violent rain showers",
    85: "slight snow showers",
    86: "heavy snow showers",
    95: "thunderstorm",
    96: "thunderstorm with slight hail",
    99: "thunderstorm with heavy hail",
}

_FALLBACK_WEATHER = {
    "condition": "unknown",
    "temp_c": None,
    "rain_mm": None,
    "outdoor_ok": False,
}


def geocode_location(location_name: str) -> tuple[float, float]:
    """
    Resolve a location name to (latitude, longitude) using Open-Meteo geocoding.

    Raises ValueError if the location cannot be found.
    Raises requests.Timeout or requests.HTTPError on network issues.
    """
    resp = requests.get(
        GEOCODING_URL,
        params={"name": location_name, "count": 1, "language": "en"},
        timeout=REQUEST_TIMEOUT,
    )
    resp.raise_for_status()
    data = resp.json()
    results = data.get("results")
    if not results:
        raise ValueError(
            f"Geocoding failed: no results for '{location_name}'. "
            "Check that the location name is recognisable (e.g. 'Ghent, Belgium')."
        )
    result = results[0]
    return float(result["latitude"]), float(result["longitude"])


def get_weekly_weather(
    lat: float,
    lon: float,
    filming_dates: list[date],
) -> list[dict]:
    """
    Fetch the Open-Meteo 7-day forecast for (lat, lon) and return one weather
    dict per filming date.

    Each dict has:
        date       : "YYYY-MM-DD"
        condition  : human-readable WMO description
        temp_c     : max temperature in Celsius (float or None)
        rain_mm    : total daily precipitation in mm (float)
        outdoor_ok : True if rain_mm <= RAIN_THRESHOLD_MM

    If a filming date falls outside the 7-day forecast window, a fallback dict
    with outdoor_ok=False is returned for that day.
    """
    daily = _fetch_forecast(lat, lon)
    date_index: dict[str, int] = {d: i for i, d in enumerate(daily["time"])}

    results = []
    for filming_date in filming_dates:
        date_str = filming_date.strftime("%Y-%m-%d")
        idx = date_index.get(date_str)
        if idx is None:
            print(
                f"Warning: {date_str} is outside the forecast window. "
                "Using fallback weather data."
            )
            results.append({"date": date_str, **_FALLBACK_WEATHER})
        else:
            results.append(_parse_day(date_str, daily, idx))
    return results


def _fetch_forecast(lat: float, lon: float) -> dict:
    """Return the raw daily arrays from the Open-Meteo forecast response."""
    resp = requests.get(
        FORECAST_URL,
        params={
            "latitude": lat,
            "longitude": lon,
            "daily": "precipitation_sum,weathercode,temperature_2m_max",
            "timezone": "auto",
            "forecast_days": 7,
        },
        timeout=REQUEST_TIMEOUT,
    )
    resp.raise_for_status()
    return resp.json()["daily"]


def _parse_day(date_str: str, daily: dict, idx: int) -> dict:
    """Extract and interpret weather data for a single forecast day."""
    code = int(daily["weathercode"][idx] or 0)
    temp = daily["temperature_2m_max"][idx]
    rain = daily["precipitation_sum"][idx] or 0.0

    return {
        "date": date_str,
        "condition": _decode_wmo(code),
        "temp_c": round(float(temp), 1) if temp is not None else None,
        "rain_mm": round(float(rain), 1),
        "outdoor_ok": float(rain) <= RAIN_THRESHOLD_MM,
    }


def _decode_wmo(code: int) -> str:
    return WMO_CODE_MAP.get(code, f"unknown (WMO {code})")
