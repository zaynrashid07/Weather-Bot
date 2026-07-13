"""
Weekly Weather Slack DM

Reads recipients.json (name, email, location), fetches a 7-day forecast for
each location from Open-Meteo (free, no API key), looks up the matching
Slack user by email, and DMs them a formatted forecast using the bot token
in the SLACK_BOT_TOKEN environment variable.

Run with:  python weekly_weather_slack.py
"""

import json
import os
import sys
from datetime import datetime

import requests

SLACK_BOT_TOKEN = os.environ.get("SLACK_BOT_TOKEN")
RECIPIENTS_FILE = os.path.join(os.path.dirname(__file__), "recipients.json")

GEOCODE_URL = "https://geocoding-api.open-meteo.com/v1/search"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
SLACK_API = "https://slack.com/api"

# Open-Meteo's geocoder matches on a bare place name only - it returns zero
# results if you pass it "City, Region" as a single string (e.g. "Mississauga,
# ON" finds nothing, but "Mississauga" alone finds it). recipients.json uses
# the "City, Region" format because it's the natural way to write a location,
# so we split it ourselves: query by city name, then use the region as a hint
# to pick the right match out of same-named cities elsewhere. Abbreviations
# are expanded to full names since that's what Open-Meteo returns in `admin1`.
REGION_ABBR = {
    # US states + DC
    "AL": "Alabama", "AK": "Alaska", "AZ": "Arizona", "AR": "Arkansas",
    "CA": "California", "CO": "Colorado", "CT": "Connecticut", "DE": "Delaware",
    "DC": "District of Columbia", "FL": "Florida", "GA": "Georgia", "HI": "Hawaii",
    "ID": "Idaho", "IL": "Illinois", "IN": "Indiana", "IA": "Iowa",
    "KS": "Kansas", "KY": "Kentucky", "LA": "Louisiana", "ME": "Maine",
    "MD": "Maryland", "MA": "Massachusetts", "MI": "Michigan", "MN": "Minnesota",
    "MS": "Mississippi", "MO": "Missouri", "MT": "Montana", "NE": "Nebraska",
    "NV": "Nevada", "NH": "New Hampshire", "NJ": "New Jersey", "NM": "New Mexico",
    "NY": "New York", "NC": "North Carolina", "ND": "North Dakota", "OH": "Ohio",
    "OK": "Oklahoma", "OR": "Oregon", "PA": "Pennsylvania", "RI": "Rhode Island",
    "SC": "South Carolina", "SD": "South Dakota", "TN": "Tennessee", "TX": "Texas",
    "UT": "Utah", "VT": "Vermont", "VA": "Virginia", "WA": "Washington",
    "WV": "West Virginia", "WI": "Wisconsin", "WY": "Wyoming",
    # Canadian provinces + territories
    "ON": "Ontario", "QC": "Quebec", "BC": "British Columbia", "AB": "Alberta",
    "MB": "Manitoba", "SK": "Saskatchewan", "NS": "Nova Scotia", "NB": "New Brunswick",
    "NL": "Newfoundland and Labrador", "PE": "Prince Edward Island",
    "NT": "Northwest Territories", "YT": "Yukon", "NU": "Nunavut",
}


def geocode(location: str):
    city, _, region_hint = location.partition(",")
    city = city.strip()
    region_hint = region_hint.strip()
    region_hint_full = REGION_ABBR.get(region_hint.upper(), region_hint) if region_hint else None

    resp = requests.get(GEOCODE_URL, params={"name": city, "count": 10}, timeout=15)
    resp.raise_for_status()
    results = resp.json().get("results")
    if not results:
        raise ValueError(f"could not geocode '{location}'")

    if region_hint_full:
        for r in results:
            haystack = f"{r.get('admin1', '')} {r.get('country', '')}".lower()
            if region_hint_full.lower() in haystack:
                return r["latitude"], r["longitude"]
        # No result matched the region hint (e.g. an unrecognized abbreviation
        # or a typo) - fall back to the top match rather than failing outright,
        # since Open-Meteo ranks results by population and is usually right.

    top = results[0]
    return top["latitude"], top["longitude"]


def get_forecast(lat: float, lon: float):
    params = {
        "latitude": lat,
        "longitude": lon,
        "daily": "temperature_2m_max,temperature_2m_min,precipitation_probability_max",
        "timezone": "auto",
        "temperature_unit": "celsius",
        "forecast_days": 7,
    }
    resp = requests.get(FORECAST_URL, params=params, timeout=15)
    resp.raise_for_status()
    return resp.json()["daily"]


def format_message(location: str, daily: dict) -> str:
    first_day = datetime.strptime(daily["time"][0], "%Y-%m-%d").strftime("%B %-d")
    lines = [f"*Your weather for the week of {first_day} — {location}:*", ""]

    for i, date_str in enumerate(daily["time"]):
        day_label = datetime.strptime(date_str, "%Y-%m-%d").strftime("%a %b %-d")
        high = round(daily["temperature_2m_max"][i])
        low = round(daily["temperature_2m_min"][i])
        precip = daily["precipitation_probability_max"][i]

        line = f"*{day_label}:* High {high}°C / Low {low}°C"
        if precip and precip > 0:
            line += f" — {precip}% chance of precipitation"
        lines.append(line)

    return "\n".join(lines)


def slack_lookup_user_by_email(email: str) -> str:
    resp = requests.get(
        f"{SLACK_API}/users.lookupByEmail",
        headers={"Authorization": f"Bearer {SLACK_BOT_TOKEN}"},
        params={"email": email},
        timeout=15,
    )
    data = resp.json()
    if not data.get("ok"):
        raise ValueError(f"Slack user lookup failed for {email}: {data.get('error')}")
    return data["user"]["id"]


def slack_open_dm(user_id: str) -> str:
    resp = requests.post(
        f"{SLACK_API}/conversations.open",
        headers={"Authorization": f"Bearer {SLACK_BOT_TOKEN}"},
        json={"users": user_id},
        timeout=15,
    )
    data = resp.json()
    if not data.get("ok"):
        raise ValueError(f"could not open DM with {user_id}: {data.get('error')}")
    return data["channel"]["id"]


def slack_send_message(channel_id: str, text: str) -> None:
    resp = requests.post(
        f"{SLACK_API}/chat.postMessage",
        headers={"Authorization": f"Bearer {SLACK_BOT_TOKEN}"},
        json={"channel": channel_id, "text": text},
        timeout=15,
    )
    data = resp.json()
    if not data.get("ok"):
        raise ValueError(f"send failed: {data.get('error')}")


def main() -> None:
    if not SLACK_BOT_TOKEN:
        print("ERROR: SLACK_BOT_TOKEN environment variable is not set.", file=sys.stderr)
        sys.exit(1)

    with open(RECIPIENTS_FILE, encoding="utf-8") as f:
        recipients = json.load(f)

    exit_code = 0
    for person in recipients:
        name = person.get("name", "unknown")
        email = person.get("email")
        location = person.get("location")
        try:
            lat, lon = geocode(location)
            daily = get_forecast(lat, lon)
            message = format_message(location, daily)
            user_id = slack_lookup_user_by_email(email)
            channel_id = slack_open_dm(user_id)
            slack_send_message(channel_id, message)
            print(f"Sent to {name} ({email})")
        except Exception as exc:  # noqa: BLE001 - keep going for other recipients
            print(f"Skipped {name} ({email}): {exc}")
            exit_code = 1

    sys.exit(exit_code)


if __name__ == "__main__":
    main()
