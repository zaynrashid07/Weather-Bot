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


DAILY_FIELDS = ",".join(
    [
        "weather_code",
        "temperature_2m_max",
        "temperature_2m_min",
        "apparent_temperature_max",
        "apparent_temperature_min",
        "precipitation_sum",
        "precipitation_probability_max",
        "rain_sum",
        "snowfall_sum",
        "wind_gusts_10m_max",
        "uv_index_max",
    ]
)

# WMO weather codes (see https://open-meteo.com/en/docs, "Weather variable
# documentation") mapped to a stand-in emoji icon, since Slack messages here
# can only use Unicode emoji, not custom images.
WEATHER_ICONS = {
    0: "☀️",
    1: "🌤️",
    2: "⛅",
    3: "☁️",
    45: "🌫️", 48: "🌫️",
    51: "🌦️", 53: "🌦️", 55: "🌦️", 56: "🌦️", 57: "🌦️",
    61: "🌧️", 63: "🌧️", 65: "🌧️", 66: "🌧️", 67: "🌧️",
    71: "❄️", 73: "❄️", 75: "❄️", 77: "❄️",
    80: "🌦️", 81: "🌦️", 82: "🌦️",
    85: "🌨️", 86: "🌨️",
    95: "⛈️", 96: "⛈️", 99: "⛈️",
}

# Thresholds for the extreme-weather warning banner. Tune freely - these are
# reasonable general-purpose defaults, not official alert criteria.
EXTREME_HEAT_C = 35        # apparent_temperature_max at/above this triggers a heat warning
EXTREME_COLD_C = -25       # apparent_temperature_min at/below this triggers a cold warning
HEAVY_RAIN_MM = 25         # rain_sum at/above this triggers a heavy rain warning
VERY_HEAVY_RAIN_MM = 50    # rain_sum at/above this escalates to "heavy" wording
SIGNIFICANT_SNOW_CM = 5    # snowfall_sum at/above this triggers a snowfall warning
HEAVY_SNOW_CM = 15         # snowfall_sum at/above this escalates to "heavy" wording
HIGH_WIND_KMH = 60         # wind_gusts_10m_max at/above this triggers a wind warning
SEVERE_WIND_KMH = 80       # wind_gusts_10m_max at/above this escalates to "severe" wording
HIGH_UV = 8                # uv_index_max at/above this triggers a UV warning
EXTREME_UV = 11            # uv_index_max at/above this escalates to "extreme" wording
THUNDERSTORM_CODES = {95, 96, 99}
HAIL_CODES = {96, 99}
FREEZING_CODES = {56, 57, 66, 67}
FOG_CODES = {45, 48}


def get_forecast(lat: float, lon: float):
    params = {
        "latitude": lat,
        "longitude": lon,
        "daily": DAILY_FIELDS,
        "timezone": "auto",
        "temperature_unit": "celsius",
        "forecast_days": 7,
    }
    resp = requests.get(FORECAST_URL, params=params, timeout=15)
    resp.raise_for_status()
    return resp.json()["daily"]


def get_warnings(daily: dict) -> list:
    """Scan every day in the forecast and return a list of human-readable
    warning strings for extreme conditions, in chronological order."""
    warnings = []

    for i, date_str in enumerate(daily["time"]):
        day_label = datetime.strptime(date_str, "%Y-%m-%d").strftime("%a")
        code = daily["weather_code"][i]
        apparent_max = daily["apparent_temperature_max"][i]
        apparent_min = daily["apparent_temperature_min"][i]
        rain = daily["rain_sum"][i]
        snow = daily["snowfall_sum"][i]
        gusts = daily["wind_gusts_10m_max"][i]
        uv = daily["uv_index_max"][i]

        if code in THUNDERSTORM_CODES:
            if code in HAIL_CODES:
                warnings.append(f"⛈️ Thunderstorms with hail possible ({day_label})")
            else:
                warnings.append(f"⛈️ Thunderstorms possible ({day_label})")

        if code in FREEZING_CODES:
            warnings.append(f"🧊 Freezing rain possible — icy surfaces ({day_label})")

        if code in FOG_CODES:
            warnings.append(f"🌫️ Reduced visibility from fog ({day_label})")

        if apparent_max >= EXTREME_HEAT_C:
            warnings.append(f"🌡️ Extreme heat — feels like {round(apparent_max)}°C ({day_label})")

        if apparent_min <= EXTREME_COLD_C:
            warnings.append(f"🥶 Extreme cold — feels like {round(apparent_min)}°C ({day_label})")

        if rain >= VERY_HEAVY_RAIN_MM:
            warnings.append(f"🌧️ Heavy rain expected — {round(rain)}mm ({day_label})")
        elif rain >= HEAVY_RAIN_MM:
            warnings.append(f"🌧️ Significant rain expected — {round(rain)}mm ({day_label})")

        if snow >= HEAVY_SNOW_CM:
            warnings.append(f"❄️ Heavy snowfall expected — {round(snow)}cm ({day_label})")
        elif snow >= SIGNIFICANT_SNOW_CM:
            warnings.append(f"❄️ Significant snowfall expected — {round(snow)}cm ({day_label})")

        if gusts >= SEVERE_WIND_KMH:
            warnings.append(f"💨 Severe winds — gusts to {round(gusts)} km/h ({day_label})")
        elif gusts >= HIGH_WIND_KMH:
            warnings.append(f"💨 High winds — gusts to {round(gusts)} km/h ({day_label})")

        if uv >= EXTREME_UV:
            warnings.append(f"☀️ Extreme UV — index {round(uv)} ({day_label})")
        elif uv >= HIGH_UV:
            warnings.append(f"☀️ Very high UV — index {round(uv)} ({day_label})")

    return warnings


def build_warning_message(daily: dict) -> str:
    """Return the '⚠️ This week' text message, or None if nothing qualifies.
    Sent as its own message, separate from the forecast table."""
    warnings = get_warnings(daily)
    if not warnings:
        return None
    lines = ["⚠️ *This week:*"] + [f"• {w}" for w in warnings]
    return "\n".join(lines)


def build_forecast_blocks(location: str, daily: dict):
    """Build the Block Kit payload for the forecast table: a header section
    plus a native `table` block (rows = metrics, columns = days). Slack
    renders table blocks itself, consistently across every client - no image
    generation or file upload needed. Returns (blocks, fallback_text)."""
    first_day = datetime.strptime(daily["time"][0], "%Y-%m-%d").strftime("%B %-d")
    num_days = len(daily["time"])

    day_row = []
    icon_row = []
    temp_row = []
    precip_row = []

    for i, date_str in enumerate(daily["time"]):
        date_obj = datetime.strptime(date_str, "%Y-%m-%d")
        day_row.append({"type": "raw_text", "text": date_obj.strftime("%a %-m/%-d")})

        icon = WEATHER_ICONS.get(daily["weather_code"][i], "")
        icon_row.append({"type": "raw_text", "text": icon})

        high = round(daily["temperature_2m_max"][i])
        low = round(daily["temperature_2m_min"][i])
        temp_row.append(
            {
                "type": "rich_text",
                "elements": [
                    {
                        "type": "rich_text_section",
                        "elements": [
                            {"type": "text", "text": f"{high}°", "style": {"bold": True}},
                            {"type": "text", "text": f"/{low}°"},
                        ],
                    }
                ],
            }
        )

        precip_mm = daily["precipitation_sum"][i]
        precip_pct = daily["precipitation_probability_max"][i]
        precip_text = ""
        if precip_mm and precip_mm > 0:
            precip_text += f"💧{round(precip_mm)}mm"
        if precip_pct and precip_pct > 0:
            precip_text += f" {round(precip_pct)}%" if precip_text else f"{round(precip_pct)}%"
        precip_row.append({"type": "raw_text", "text": precip_text or "–"})

    blocks = [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*Your weather for the week of {first_day} — {location}:*",
            },
        },
        {
            "type": "table",
            "column_settings": [{"align": "center"}] * num_days,
            "rows": [day_row, icon_row, temp_row, precip_row],
        },
    ]

    fallback_text = f"Weekly forecast for {location}"
    return blocks, fallback_text


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


def slack_send_message(channel_id: str, text: str, blocks: list = None) -> None:
    payload = {"channel": channel_id, "text": text}
    if blocks:
        payload["blocks"] = blocks
    resp = requests.post(
        f"{SLACK_API}/chat.postMessage",
        headers={"Authorization": f"Bearer {SLACK_BOT_TOKEN}"},
        json=payload,
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
            user_id = slack_lookup_user_by_email(email)
            channel_id = slack_open_dm(user_id)

            warning_text = build_warning_message(daily)
            if warning_text:
                slack_send_message(channel_id, warning_text)

            blocks, fallback_text = build_forecast_blocks(location, daily)
            slack_send_message(channel_id, fallback_text, blocks=blocks)

            print(f"Sent to {name} ({email})")
        except Exception as exc:  # noqa: BLE001 - keep going for other recipients
            print(f"Skipped {name} ({email}): {exc}")
            exit_code = 1

    sys.exit(exit_code)


if __name__ == "__main__":
    main()
