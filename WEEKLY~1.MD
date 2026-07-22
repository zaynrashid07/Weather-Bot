# Weekly Weather Bot — Setup Guide (Expanded)

This sets up a real Slack bot — its own identity, separate from your personal account — that posts a 7-day weather forecast for a single site (Mississauga, ON, by default) to a Slack channel every day at 6:30am. Two independent pieces make this work: a Slack app with a bot token, and a free scheduled service (GitHub Actions) that runs the job and calls Slack's API.

**What you'll need before starting:**

- Permission to install apps into your Slack workspace. Some workspaces restrict this to admins — if "Install to Workspace" is greyed out or asks for approval later, you'll need to route the request to whoever manages your Slack.
- A GitHub account (free — sign up at github.com if you don't have one).
- The bot already invited into the target Slack channel (or an admin who can invite it) — see Part 3.
- About 15–20 minutes.

**Files referenced throughout this guide** (provided alongside it):

| File | Purpose |
|---|---|
| `weekly_weather_slack.py` | The script that fetches the forecast and posts it to the channel |
| `test_extreme_weather.py` | Optional: sends a fabricated extreme-weather week for on-demand testing |
| `requirements.txt` | The one Python dependency (`requests`) |
| `weekly-weather.yml` | The GitHub Actions schedule definition |
| `test-extreme-weather.yml` | Optional: manual-trigger workflow for the test script |

---

## Part 1 — Create the Slack app and bot token

### Option A: Manual setup (click through each setting)

1. Go to **https://api.slack.com/apps** in your browser and sign in with your Slack account if prompted.
2. Click **Create New App** (top right).
3. Choose **From scratch**.
4. Enter an **App Name** — something like "Weather Bot" is fine, this is just the display name that will post in the channel.
5. Under **Pick a workspace to develop your app in**, select your workspace, then click **Create App**.
6. You'll land on the app's **Basic Information** page. In the left sidebar, click **OAuth & Permissions**.
7. Scroll down to the **Scopes** section, then **Bot Token Scopes**. Click **Add an OAuth Scope** and add:
   - `chat:write` — lets the bot post messages into channels it's a member of.
8. Scroll back up to the top of the **OAuth & Permissions** page and click **Install to Workspace**.
9. Slack will show a permissions review screen listing exactly what the bot can do (post messages). Click **Allow**.
   - If you see a message that approval is required, someone with Slack admin rights will need to approve the app before you can continue — this is a workspace setting, not something you can bypass.
10. After installing, you'll land back on **OAuth & Permissions**, now showing a **Bot User OAuth Token** starting with `xoxb-`. Click to copy it.
11. Treat this token like a password: anyone holding it can post messages as the bot. Don't paste it into chat messages, commit it to a public repo, or share it over email. It only needs to go into one place — the GitHub secret in Part 2.

### Option B: Faster setup using an app manifest

Slack lets you skip steps 6–7 by creating the app from a manifest that pre-fills the scope. When creating the app, choose **From an app manifest** instead of **From scratch**, select your workspace, and paste this (YAML format):

```yaml
display_information:
  name: Weather Bot
features:
  bot_user:
    display_name: Weather Bot
    always_online: true
oauth_config:
  scopes:
    bot:
      - chat:write
settings:
  org_deploy_enabled: false
  socket_mode_enabled: false
  token_rotation_enabled: false
```

Review the summary Slack shows you, click **Create**, then continue from step 8 above (Install to Workspace → copy the bot token).

---

## Part 2 — Set up the GitHub repository

1. Sign in to GitHub and click **New** (or the **+** in the top right → **New repository**).
2. Give it a name (e.g. `weekly-weather-bot`). Private is a reasonable default, though nothing in this repo is sensitive on its own now that it no longer lists people's names or emails.
3. Click **Create repository**.
4. Add the files from this guide to the repo. The simplest way if you're not using git locally: on the repo's main page, click **Add file → Upload files**, then drag in `weekly_weather_slack.py`, `requirements.txt`, and (optionally) `test_extreme_weather.py`. Commit those.
5. `weekly-weather.yml` needs to live at the exact path `.github/workflows/weekly-weather.yml` — GitHub Actions only discovers workflow files in that specific folder. To create that path via the web UI: click **Add file → Create new file**, then in the filename box type `.github/workflows/weekly-weather.yml` (typing the slashes creates the folders automatically), paste in the contents of the provided `weekly-weather.yml`, and commit. Do the same for `test-extreme-weather.yml` if you want the optional test workflow.
6. Now add the secret: go to the repo's **Settings** tab → in the left sidebar, **Secrets and variables → Actions** → **New repository secret**.
   - **Name:** `SLACK_BOT_TOKEN` (must match exactly — this is what the workflow file references).
   - **Value:** paste the `xoxb-...` token from Part 1.
   - Click **Add secret**.
7. Double-check: GitHub secrets are write-only after creation — you (and no one else) can view the value again once saved, only overwrite it. That's expected and is the point of storing it as a secret rather than in a file.

At this point the automation infrastructure is fully wired up; it just needs a channel and a first test run.

---

## Part 3 — Point it at the right channel and location

**Channel:** the script posts to a fixed channel ID, read from the `SLACK_CHANNEL_ID` repository variable (falling back to a hardcoded test channel if that variable isn't set). To set or change it:

1. In Slack, invite the bot into the target channel: open the channel → click the channel name → **Integrations** (or **Members**) → **Add apps** → select your bot. The bot must be a member of the channel before it can post there — there's no scope that bypasses this for private channels, and public channels need it too unless you separately add `chat:write.public`.
2. Get the channel ID: open the channel in Slack, click the channel name at the top, and the ID (starts with `C`) is shown near the bottom of the "About" tab. You can also right-click the channel → **Copy link** — the ID is the last segment of the URL.
3. In GitHub: repo **Settings → Secrets and variables → Actions → Variables tab → New repository variable**.
   - **Name:** `SLACK_CHANNEL_ID`
   - **Value:** the channel ID from step 2 (e.g. `C0BH4FEHZDW`)
4. To switch channels later (e.g. from a test channel to the real one), just edit this variable's value — no code change, no redeploy.

**Location:** the site the forecast covers defaults to `Mississauga, ON`, set as a constant in `weekly_weather_slack.py` (`LOCATION = os.environ.get("SITE_LOCATION", "Mississauga, ON")`). To point it at a different site, either:
- Add a `SITE_LOCATION` repository variable the same way as `SLACK_CHANNEL_ID` above (and add `SITE_LOCATION: ${{ vars.SITE_LOCATION }}` to the workflow's `env:` block), or
- Just edit the default string directly in the script and commit.

Location can be any city, town, or place name recognizable by a geocoder — it works globally. Being specific (e.g. "Austin, TX" rather than just "Austin") avoids ambiguity with same-named places elsewhere.

---

## Part 4 — Test it before trusting the schedule

1. In the repo, click the **Actions** tab.
2. In the left sidebar, click **Daily Weather Channel Post** (the workflow name).
3. Click **Run workflow** (a button/dropdown on the right) → confirm **Run workflow** again. This manually triggers a run right now, without waiting for Monday.
4. Refresh after a few seconds — a new run will appear. Click into it, then click the **send-weather** job to see live logs.
5. Read the output carefully:
   - `Posted <location> forecast to channel <id>` — success.
   - Anything prefixed `ERROR:` — the run failed; see the troubleshooting table below.
6. Go check the Slack channel — the messages should appear from the **bot's** name/icon, not your personal account.

### Troubleshooting common errors

| Error in logs | What it means | Fix |
|---|---|---|
| `could not geocode '<location>'` | The city name (before the comma) didn't match any place at all | Check for typos in the city name |
| `send failed: invalid_auth` | The bot token is wrong, expired, or wasn't saved correctly as the secret | Re-copy the token from Slack, update the GitHub secret |
| `send failed: not_in_channel` | The bot isn't a member of the target channel | Invite the bot into the channel (Part 3, step 1) |
| `send failed: channel_not_found` | The `SLACK_CHANNEL_ID` value is wrong or the bot can't see that channel | Re-copy the channel ID (Part 3, step 2); confirm it's not mistyped |
| `send failed: missing_scope` | The `chat:write` scope wasn't added/installed | Go back to OAuth & Permissions, add the scope, click **Install to Workspace** again to reinstall with the new scope |
| Workflow doesn't appear under Actions at all | The yml file isn't at `.github/workflows/weekly-weather.yml` exactly | Check the path — a typo or wrong folder is the usual cause |

---

## Part 5 — Understanding the schedule

The workflow trigger is:

```yaml
schedule:
  - cron: "30 10 * * *"
```

Cron fields are `minute hour day-of-month month day-of-week`, always in UTC — GitHub Actions has no timezone setting. `30 10 * * *` means "at minute 30 of hour 10 UTC, every day" (the last `*` is day-of-week — a wildcard, so it's not restricted to any particular day). 10:30 UTC is 6:30 AM Eastern **during Eastern Daylight Time** (UTC−4, roughly mid-March to early November).

The catch: cron doesn't know about daylight saving. During Eastern Standard Time (UTC−5, roughly early November to mid-March), that same `30 10 * * *` fires at **5:30 AM** local instead of 6:30. If exact timing matters to you year-round, swap the cron line twice a year:

- EDT (spring/summer): `30 10 * * *`
- EST (fall/winter): `30 11 * * *`

If being off by an hour twice a year doesn't matter, you can leave it as-is indefinitely.

One more real-world note: GitHub's scheduler can run a few minutes late during periods of high platform load — this is documented, expected behavior for free scheduled workflows, not a sign anything is broken. Also worth knowing: GitHub automatically disables scheduled workflows after 60 days of zero repository activity — if the daily post ever silently stops, check the **Actions** tab for a "workflow disabled" banner before assuming something else is wrong.

---

## Part 6 — Message format & extreme weather warnings

Each daily run posts up to two messages to the channel:

1. **A warnings message** (only sent if something qualifies) — plain text, e.g.:
   ```
   ⚠️ *This week:*
   • 🌡️ Extreme heat — feels like 39°C (Tue)
   • ⛈️ Thunderstorms with hail possible (Thu)
   ```
2. **The forecast table** — a native Slack **table block** (not a markdown table), with each day as a column across four rows: day label, icon, bold high / plain low temperature, and a 💧mm + % precipitation indicator (shown as "–" on dry days).

The table block is a real structured Slack UI element (added to the platform in 2025), so it renders identically across desktop, mobile, and web — no image generation, file upload, or extra Slack scope required, just the existing `chat:write` scope sending a `blocks` payload instead of plain text. You can preview the exact JSON structure being sent by pasting the output of `build_forecast_blocks()` into [Slack's Block Kit Builder](https://app.slack.com/block-kit-builder/).

Any day crossing a threshold below adds a line to the warnings message (the message is skipped entirely if no day qualifies). All thresholds are named constants near the top of `weekly_weather_slack.py` — safe to tune without touching any logic.

Six of these warnings also carry a full **facility action checklist** (pre-event / during-event / post-event), sourced from Clutch's Severe Weather Checklist & Action Plan. Their thresholds are set to match that document's official activation triggers exactly, so a warning firing here corresponds to "activate this protocol" in the checklist. If a warning fires on multiple days in the same week, the checklist text is only printed once beneath the list of headlines — not repeated per day.

| Warning | Trigger | Threshold | Facility protocol attached? |
|---|---|---|---|
| Extreme heat | `temperature_2m_max` or `apparent_temperature_max` (humidex) | ≥ 31°C or humidex ≥ 40 | Yes |
| Extreme cold | `temperature_2m_min` or `apparent_temperature_min` (wind chill) | ≤ −30°C | Yes |
| Extreme wind | `wind_speed_10m_max` (sustained) or `wind_gusts_10m_max` | sustained ≥ 70 km/h or gusts ≥ 90 km/h | Yes |
| Heavy rain | `rain_sum` | ≥ 50mm | Yes |
| Heavy snowfall | `snowfall_sum` | ≥ 15cm | Yes |
| Freezing rain | WMO `weather_code` | 56, 57, 66, 67 | Yes |
| Thunderstorms (± hail) | WMO `weather_code` | 95 / 96, 99 | No — not in the checklist |
| Fog | WMO `weather_code` | 45, 48 | No — not in the checklist |
| Very high / extreme UV | `uv_index_max` | ≥ 8 / ≥ 11 | No — not in the checklist |

Two known gaps versus the source document, both due to what's available from a daily forecast aggregate rather than hourly/observed data: the checklist's alternate heavy-rain trigger of "25mm in a single hour" isn't captured (only the 50mm/24h trigger is), and the "10cm for a first/early-season snowfall" exception isn't tracked (there's no season-state to check against). Both would need hourly precipitation data and/or historical tracking to implement — flag if you want either added.

Icon legend (WMO `weather_code` → emoji, since Slack messages here can only use emoji, not custom images):

| Code(s) | Condition | Icon |
|---|---|---|
| 0 | Clear | ☀️ |
| 1 | Mainly clear | 🌤️ |
| 2 | Partly cloudy | ⛅ |
| 3 | Overcast | ☁️ |
| 45, 48 | Fog | 🌫️ |
| 51, 53, 55 | Drizzle (steady, light) | ☔ |
| 56, 57 | Freezing drizzle | 🧊☔ |
| 61, 63, 65 | Rain (steady) | 🌧️ |
| 66, 67 | Freezing rain | 🧊🌧️ |
| 80, 81, 82 | Showers (intermittent) | 🌦️ |
| 71, 73, 75, 77 | Snow | ❄️ |
| 85, 86 | Snow showers | 🌨️ |
| 95 | Thunderstorm | ⛈️ |
| 96, 99 | Thunderstorm with hail | ⛈️🧊 |

Note: light/moderate/heavy variants of the same condition (e.g. codes 61, 63, 65 are all "rain," just different intensities) intentionally share one icon — intensity is conveyed by the mm/% precipitation row instead, which is standard practice for weather icon sets generally.

---

## Part 6b — Testing extreme weather without waiting for it

`test_extreme_weather.py` sends a **fabricated** week of extreme conditions (heat, cold, wind, rain, snow, freezing rain, thunderstorm with hail, plus UV) through the exact same `build_warning_message`/`build_forecast_blocks` code the real job uses — no real forecast is fetched, and no thresholds are touched. It's imported straight from `weekly_weather_slack.py`, so what you see is guaranteed to match production formatting.

To use it: add the file to your repo alongside the others, and add `test-extreme-weather.yml` at `.github/workflows/test-extreme-weather.yml` (same rule as the main workflow — GitHub only reads that exact folder). It has no schedule, only a manual trigger — go to **Actions → Test Extreme Weather Message → Run workflow**. It posts to the same channel as the real job, prefixed with "[TEST - fabricated data, not a real forecast]" so it's never mistaken for a real alert.

This is the safer alternative to temporarily lowering real thresholds to force a trigger — that approach works too, but it's easy to forget to change a threshold back afterward, and until you do, the live job could send a false alarm off real (non-extreme) weather.

---

## Part 7 — Ongoing maintenance

- **Changing the site or channel:** see Part 3 — both are set via repository variables (or the constants in the script) with no code redeploy needed for the variable-based approach.
- **Changing wording, layout, warning thresholds, or icons:** edit `weekly_weather_slack.py` — `build_forecast_blocks` controls the table block, `build_warning_message`/`get_warnings` and the threshold constants control the warnings message, and `WEATHER_ICONS` controls the emoji per WMO code.
- **Rotating the bot token:** in the Slack app's OAuth & Permissions page, reinstalling the app regenerates the token. Update the `SLACK_BOT_TOKEN` secret in GitHub afterward — the old token stops working immediately once reinstalled.
- **Cost:** this is free end to end — GitHub Actions includes free minutes for scheduled workflows (a job this small uses well under a minute per run), and Open-Meteo's API requires no key, account, or paid plan.
- **This system runs on a schedule, not continuously:** each run recalculates warnings fresh from whatever Open-Meteo returns at that moment. It's not a standing monitor — even at a daily cadence, if conditions shift significantly between runs (e.g. a storm develops mid-afternoon), it won't be caught until the next scheduled run (or a manual trigger). Keep that in mind for anything safety-critical.

---

## Quick end-to-end checklist

1. Slack app created, `chat:write` scope added, app installed, token copied.
2. Bot invited into the target Slack channel; channel ID copied.
3. Private (or public) GitHub repo created with the script, requirements, and workflow file(s) at their exact paths.
4. `SLACK_BOT_TOKEN` secret added, `SLACK_CHANNEL_ID` (and optionally `SITE_LOCATION`) variables added under repo Settings → Secrets and variables → Actions.
5. Manual **Run workflow** test completed, log shows `Posted ... forecast to channel ...`, message confirmed in the channel from the bot's identity.
6. Schedule left as-is (or adjusted for DST per Part 5) — the job now runs automatically every day.
