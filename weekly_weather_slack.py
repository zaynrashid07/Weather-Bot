"""
Weekly Weather Slack Channel Post

Fetches a 7-day forecast for a single fixed site (LOCATION, below) from
Open-Meteo (free, no API key) and posts a formatted forecast table, plus any
extreme-weather warnings and matching facility protocol checklists, to a
single Slack channel.

Requires SLACK_BOT_TOKEN in the environment. The bot must already be a
member of the target channel - this is mandatory for private channels (no
scope can bypass that) and required for public channels too unless the bot
also has the chat:write.public scope.

Run with:  python weekly_weather_slack.py
"""

import os
import sys
from datetime import datetime

import requests

SLACK_BOT_TOKEN = os.environ.get("SLACK_BOT_TOKEN")

# The site this report covers. Overridden by the SITE_LOCATION repository
# variable in GitHub Actions if you ever need to point this at a different
# location - same pattern as CHANNEL_ID below.
LOCATION = os.environ.get("SITE_LOCATION", "Mississauga, ON")

# Where reports get posted. Overridden by the SLACK_CHANNEL_ID repository
# variable in GitHub Actions (Settings -> Secrets and variables -> Actions ->
# Variables tab) - switching channels is then just editing that value in
# GitHub's UI, no code change or redeploy needed. The hardcoded fallback
# below is used only if that variable isn't set (e.g. running locally
# without it).
CHANNEL_ID = os.environ.get("SLACK_CHANNEL_ID", "C0A70L7HTFF")

GEOCODE_URL = "https://geocoding-api.open-meteo.com/v1/search"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
SLACK_API = "https://slack.com/api"

# Open-Meteo's geocoder matches on a bare place name only - it returns zero
# results if you pass it "City, Region" as a single string (e.g. "Mississauga,
# ON" finds nothing, but "Mississauga" alone finds it). LOCATION uses the
# "City, Region" format because it's the natural way to write a location, so
# we split it ourselves: query by city name, then use the region as a hint to
# pick the right match out of same-named cities elsewhere. Abbreviations are
# expanded to full names since that's what Open-Meteo returns in `admin1`.
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
        "wind_speed_10m_max",
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
    51: "☔", 53: "☔", 55: "☔",           # drizzle (steady, light)
    56: "🧊☔", 57: "🧊☔",                 # freezing drizzle
    61: "🌧️", 63: "🌧️", 65: "🌧️",        # rain (steady)
    66: "🧊🌧️", 67: "🧊🌧️",               # freezing rain
    71: "❄️", 73: "❄️", 75: "❄️", 77: "❄️",
    80: "🌦️", 81: "🌦️", 82: "🌦️",        # showers (intermittent, sun breaks)
    85: "🌨️", 86: "🌨️",
    95: "⛈️",                             # thunderstorm
    96: "⛈️🧊", 99: "⛈️🧊",                # thunderstorm with hail
}

# Thresholds for the extreme-weather warning banner. The six below (heat,
# cold, wind, rain, snow, freezing rain) are set to match the official
# activation triggers in Clutch's Severe Weather Checklist & Action Plan, so
# that a warning here corresponds to "activate this protocol" in that
# document. Fog/UV/thunderstorm aren't covered by that checklist, so their
# thresholds are just reasonable general defaults - tune freely.
EXTREME_HEAT_TEMP_C = 31       # temperature_2m_max at/above this triggers Extreme Heat
EXTREME_HEAT_HUMIDEX_C = 40    # apparent_temperature_max (humidex proxy) at/above this also triggers it
EXTREME_COLD_C = -30           # temperature_2m_min OR apparent_temperature_min (wind chill proxy) at/below this triggers Extreme Cold
HEAVY_RAIN_MM = 50             # rain_sum at/above this triggers Heavy Rain (checklist's 25mm/hour alt-trigger isn't available from daily data)
HEAVY_SNOW_CM = 15             # snowfall_sum at/above this triggers Heavy Snowfall (checklist's 10cm first-event exception isn't tracked)
SUSTAINED_WIND_KMH = 70        # wind_speed_10m_max at/above this triggers Extreme Wind
WIND_GUST_KMH = 90             # wind_gusts_10m_max at/above this also triggers Extreme Wind
HIGH_UV = 8                    # uv_index_max at/above this triggers a UV warning (not in the checklist)
EXTREME_UV = 11                # uv_index_max at/above this escalates to "extreme" wording
THUNDERSTORM_CODES = {95, 96, 99}
HAIL_CODES = {96, 99}
FREEZING_CODES = {56, 57, 66, 67}
FOG_CODES = {45, 48}

# Facility action checklists, sourced from Clutch's Severe Weather Checklist &
# Action Plan (pages 1-6). Each triggered warning that maps to one of these
# keys gets the full pre/during/post list attached once beneath the headline.
WARNING_PROTOCOLS = {
    "extreme_heat": {
        "label": "Extreme Heat Protocol",
        "pre": [
            "Confirm cooling systems are fully operational at each site (review HVAC service records).",
            "Check condenser coil cleanliness on rooftop units.",
            "Confirm drum fans are clean, tested and available.",
            "Confirm with HSE that chilled bottled water is available.",
        ],
        "during": [
            "Monitor indoor temperatures in key areas (production/warehouse, offices) at regular intervals.",
            "Watch for HVAC alarms or unusual system behavior; dispatch vendor immediately if a unit fails.",
            "Check on staff working in non-air-conditioned areas (production, mechanical rooms).",
        ],
        "post": [
            "Inspect HVAC systems for signs of overwork or strain (unusual noise, tripped breakers, ice on coils).",
            "Log peak indoor temperatures reached and any comfort complaints received.",
            "Follow up on any vendor callouts and confirm repairs are complete.",
            "Debrief with team on any gaps (e.g., areas that ran hot) for next event.",
        ],
    },
    "extreme_wind": {
        "label": "Extreme Wind Protocol",
        "pre": [
            "Secure or remove loose outdoor items: signage, patio furniture, waste bins, pallets, tires, ladders.",
            "Inspect rooftop equipment, flashing, and loose roofing membrane for anything unsecured.",
            "Confirm tree limbs near buildings/parking areas have no obvious hazards.",
            "Advise vendor and delivery contacts of possible access disruptions.",
        ],
        "during": [
            "Monitor for downed branches, debris, or damage in parking lots and building perimeters.",
            "Restrict access to exterior areas with falling-object risk.",
            "Keep a log of any wind-related incidents reported by staff.",
        ],
        "post": [
            "Conduct a full exterior walk-around: roof, siding, windows, signage, fencing, parking lot lighting.",
            "Document any damage with photos for insurance and vendor follow-up.",
            "Clear debris from walkways, drains, and parking areas.",
            "Schedule repairs for any identified damage and confirm structural items (roof, awnings) are re-secured.",
        ],
    },
    "heavy_snowfall": {
        "label": "Heavy Snowfall Protocol",
        "pre": [
            "Confirm snow removal vendor is on standby with equipment and salt/sand supply confirmed.",
            "Verify snow removal contract activation thresholds and response-time commitments.",
            "Stage extra ice-melt, shovels, and mats at building entrances.",
            "Confirm exterior emergency lighting and signage are visible and functioning.",
        ],
        "during": [
            "Confirm vendor is actively plowing/salting per contracted schedule; escalate if service is late.",
            "Monitor entrances, walkways, and accessible parking spaces for snow accumulation and ice.",
            "Check rooftop snow accumulation on flat roofs if snowfall is prolonged or heavy.",
        ],
        "post": [
            "Walk the site to confirm all walkways, entrances, ramps, and accessible parking are cleared.",
            "Verify snow has been piled away from fire hydrants, exits, and drainage points.",
            "Inspect roof for excess snow load or drainage issues once conditions allow.",
            "Review vendor performance against the Master Services Agreement and log any service gaps.",
        ],
    },
    "heavy_rain": {
        "label": "Heavy Rain Protocol",
        "pre": [
            "Confirm roof drains, gutters, and downspouts are clear of debris.",
            "Inspect parking lot catch basins and site grading for known pooling areas.",
        ],
        "during": [
            "Monitor known problem areas for water intrusion.",
            "Check sump pump operation periodically during sustained heavy rain (shed).",
            "Watch for roof leaks, especially near known weak points or previous repair areas.",
            "Keep entrance mats and slip-hazard signage in place at all entrances.",
        ],
        "post": [
            "Inspect roof, ceilings, and walls for signs of leaks or water staining.",
            "Confirm all drains and catch basins are clear and functioning post-event.",
            "Document any water intrusion with photos, location, and estimated volume for vendor/insurance follow-up.",
            "Dry/dehumidify any affected areas promptly to prevent mould growth.",
        ],
    },
    "extreme_cold": {
        "label": "Extreme Cold Protocol",
        "pre": [
            "Confirm heating systems are fully operational and recently serviced at all sites.",
            "Check for exposed or poorly insulated pipes at risk of freezing; add insulation/heat trace if needed.",
            "Communicate any building access changes to staff for extreme cold days.",
        ],
        "during": [
            "Monitor indoor temperatures in key areas (especially near bay doors).",
            "Watch for signs of frozen or bursting pipes (drop in water pressure, damp spots, unusual sounds).",
            "Confirm exterior doors/dock doors are sealing properly and not left open unnecessarily.",
            "Check on any staff with outdoor duties (shuttle team) for cold-exposure risk and limit outdoor time.",
        ],
        "post": [
            "Inspect pipes, water lines, and heating equipment for any freeze-related damage.",
            "Log any heating system issues or vendor callouts for follow-up.",
            "Review any areas that ran cold and plan insulation/heat-trace improvements before next season.",
        ],
    },
    "freezing_rain": {
        "label": "Freezing Rain Protocol",
        "pre": [
            "Confirm ice-management vendor is on standby with salt/brine supply confirmed.",
            "Stage extra ice-melt and traction mats at all entrances and high-traffic walkways.",
            "Check exterior stair railings and ramps for pre-treatment ahead of the event.",
            "Communicate to staff/visitors about expected icy conditions and delayed arrivals.",
        ],
        "during": [
            "Monitor walkways, entrances, stairs, and parking lots continuously for ice buildup.",
            "Confirm vendor is applying salt/sand per contracted response times; escalate if delayed.",
            "Restrict access to any area that cannot be safely treated (rope off, signage) until treated.",
            "Watch for ice accumulation on power lines, tree limbs, or rooftop equipment.",
        ],
        "post": [
            "Walk the full site to confirm all walkways, stairs, and parking areas are treated and safe.",
            "Inspect for any slip-and-fall incidents and document per safety procedure.",
            "Check exterior structures (railings, awnings, signage) for ice-related damage.",
            "Review vendor response time and performance against contracted service levels.",
        ],
    },
}


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
    """Scan every day in the forecast and return a list of (headline,
    protocol_key) tuples, in chronological order. protocol_key is a key into
    WARNING_PROTOCOLS, or None for conditions with no facility checklist."""
    warnings = []

    for i, date_str in enumerate(daily["time"]):
        day_label = datetime.strptime(date_str, "%Y-%m-%d").strftime("%a")
        code = daily["weather_code"][i]
        temp_max = daily["temperature_2m_max"][i]
        temp_min = daily["temperature_2m_min"][i]
        apparent_max = daily["apparent_temperature_max"][i]
        apparent_min = daily["apparent_temperature_min"][i]
        rain = daily["rain_sum"][i]
        snow = daily["snowfall_sum"][i]
        sustained = daily["wind_speed_10m_max"][i]
        gusts = daily["wind_gusts_10m_max"][i]
        uv = daily["uv_index_max"][i]

        if code in THUNDERSTORM_CODES:
            if code in HAIL_CODES:
                warnings.append((f"⛈️ Thunderstorms with hail possible ({day_label})", None))
            else:
                warnings.append((f"⛈️ Thunderstorms possible ({day_label})", None))

        if code in FREEZING_CODES:
            warnings.append((f"🧊 Freezing rain possible — icy surfaces ({day_label})", "freezing_rain"))

        if code in FOG_CODES:
            warnings.append((f"🌫️ Reduced visibility from fog ({day_label})", None))

        if temp_max >= EXTREME_HEAT_TEMP_C or apparent_max >= EXTREME_HEAT_HUMIDEX_C:
            warnings.append((
                f"🌡️ Extreme heat — up to {round(temp_max)}°C, humidex {round(apparent_max)} ({day_label})",
                "extreme_heat",
            ))

        if temp_min <= EXTREME_COLD_C or apparent_min <= EXTREME_COLD_C:
            warnings.append((
                f"🥶 Extreme cold — down to {round(temp_min)}°C, wind chill {round(apparent_min)} ({day_label})",
                "extreme_cold",
            ))

        if rain >= HEAVY_RAIN_MM:
            warnings.append((f"🌧️ Heavy rain expected — {round(rain)}mm ({day_label})", "heavy_rain"))

        if snow >= HEAVY_SNOW_CM:
            warnings.append((f"❄️ Heavy snowfall expected — {round(snow)}cm ({day_label})", "heavy_snowfall"))

        if sustained >= SUSTAINED_WIND_KMH or gusts >= WIND_GUST_KMH:
            warnings.append((
                f"💨 Extreme wind — sustained {round(sustained)} km/h, gusts to {round(gusts)} km/h ({day_label})",
                "extreme_wind",
            ))

        if uv >= EXTREME_UV:
            warnings.append((f"☀️ Extreme UV — index {round(uv)} ({day_label})", None))
        elif uv >= HIGH_UV:
            warnings.append((f"☀️ Very high UV — index {round(uv)} ({day_label})", None))

    return warnings


def build_warning_message(daily: dict) -> str:
    """Return the '⚠️ This week' text message, or None if nothing qualifies.
    Sent as its own message, separate from the forecast table. Any warning
    that maps to a facility checklist gets the full pre/during/post action
    list attached once beneath the headlines (not repeated per day)."""
    warnings = get_warnings(daily)
    if not warnings:
        return None

    lines = ["⚠️ *This week:*"]
    lines.extend(f"• {headline}" for headline, _ in warnings)

    protocol_order = []
    for _, protocol_key in warnings:
        if protocol_key and protocol_key not in protocol_order:
            protocol_order.append(protocol_key)

    for key in protocol_order:
        proto = WARNING_PROTOCOLS[key]
        lines.append("")
        lines.append(f"*{proto['label']}*")
        lines.append("_Pre-event:_")
        lines.extend(f"• {item}" for item in proto["pre"])
        lines.append("_During event:_")
        lines.extend(f"• {item}" for item in proto["during"])
        lines.append("_Post-event:_")
        lines.extend(f"• {item}" for item in proto["post"])

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
                "text": f"*Weather for the week of {first_day} — {location}:*",
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

    try:
        lat, lon = geocode(LOCATION)
        daily = get_forecast(lat, lon)

        warning_text = build_warning_message(daily)
        if warning_text:
            slack_send_message(CHANNEL_ID, warning_text)

        blocks, fallback_text = build_forecast_blocks(LOCATION, daily)
        slack_send_message(CHANNEL_ID, fallback_text, blocks=blocks)

        print(f"Posted {LOCATION} forecast to channel {CHANNEL_ID}")
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
