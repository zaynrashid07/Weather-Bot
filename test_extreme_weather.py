"""
Test script - sends a FABRICATED extreme-weather week to the first person in
recipients.json, using the exact same message-building code as the real job
(imported straight from weekly_weather_slack.py), so you can see precisely
how the warnings, facility protocol checklists, and forecast table render in
Slack. No real forecast is fetched, and no thresholds are touched - this is
just fake `daily` data run through the real formatting logic.

Run with:  python test_extreme_weather.py
(Needs the same SLACK_BOT_TOKEN environment variable as the real job.)
"""

import json

from weekly_weather_slack import (
    RECIPIENTS_FILE,
    build_forecast_blocks,
    build_warning_message,
    slack_lookup_user_by_email,
    slack_open_dm,
    slack_send_message,
)

# Engineered to trip every facility-protocol warning at once (heat, cold,
# wind, rain, snow, freezing rain, thunderstorm with hail), plus one
# non-protocol warning (extreme UV) for comparison. Dates are arbitrary -
# only the data values matter for this test.
MOCK_DAILY = {
    "time": [
        "2026-08-03", "2026-08-04", "2026-08-05", "2026-08-06",
        "2026-08-07", "2026-08-08", "2026-08-09",
    ],
    "weather_code":                  [1,   1,    1,   1,  75,  66,  96],  # Fri=heavy snow, Sat=freezing rain, Sun=thunderstorm+hail
    "temperature_2m_max":            [33, -28,   15,  18,  -3,   2,  22],  # Mon=extreme heat
    "temperature_2m_min":            [24, -32,    8,  12, -10,  -1,  14],  # Tue=extreme cold
    "apparent_temperature_max":      [41, -30,   16,  19,  -5,   3,  23],
    "apparent_temperature_min":      [26, -34,    9,  13, -12,  -2,  15],
    "precipitation_sum":             [0,   0,    0,  55,   0,   3,  20],
    "precipitation_probability_max": [0,   0,    0,  90,   0,  60,  70],
    "rain_sum":                      [0,   0,    0,  55,   0,   3,  20],   # Thu=heavy rain
    "snowfall_sum":                  [0,   0,    0,   0,  18,   0,   0],   # Fri=heavy snowfall
    "wind_speed_10m_max":            [15, 15,   75,  15,  15,  15,  25],   # Wed=extreme wind
    "wind_gusts_10m_max":            [20, 20,   95,  20,  20,  20,  35],
    "uv_index_max":                  [12,  1,    3,   3,   1,   1,   4],   # Mon=extreme UV (not protocol-linked)
}


def main() -> None:
    with open(RECIPIENTS_FILE, encoding="utf-8") as f:
        recipients = json.load(f)
    if not recipients:
        raise SystemExit("recipients.json is empty - add someone to test with first.")

    person = recipients[0]
    print(f"Sending test message to {person['name']} ({person['email']})")

    user_id = slack_lookup_user_by_email(person["email"])
    channel_id = slack_open_dm(user_id)

    warning_text = build_warning_message(MOCK_DAILY)
    if warning_text:
        slack_send_message(channel_id, f"🧪 *[TEST - fabricated data, not a real forecast]*\n\n{warning_text}")

    blocks, fallback_text = build_forecast_blocks(f"{person['location']} (TEST DATA)", MOCK_DAILY)
    slack_send_message(channel_id, fallback_text, blocks=blocks)

    print("Done - check Slack.")


if __name__ == "__main__":
    main()
