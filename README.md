# Resideo — Home Assistant integration

[![HACS Custom](https://img.shields.io/badge/HACS-Custom-41BDF5)](https://hacs.xyz/docs/faq/custom_repositories/)
[![GitHub release](https://img.shields.io/github/v/release/sfcodes/ha-resideo)](https://github.com/sfcodes/ha-resideo/releases)
[![CI](https://github.com/sfcodes/ha-resideo/actions/workflows/ci.yml/badge.svg)](https://github.com/sfcodes/ha-resideo/actions/workflows/ci.yml)
[![License](https://img.shields.io/github/license/sfcodes/ha-resideo)](LICENSE)

Control your **Resideo** thermostats from Home Assistant. Sign in with the **same email and
password** you use in the Resideo app — that's the whole setup. From then on everything stays in
sync in real time: change something on the thermostat or in the app, and Home Assistant sees it
a second later.

> [!NOTE]
> Home Assistant already ships with a [Lyric](https://www.home-assistant.io/integrations/lyric/)
> integration for these thermostats, but it requires a _developer account_ with OAuth API keys
> — a bit of a headache to set up — and it updates by _polling_. This one uses your regular
> credentials and **streams changes in real time**.

> [!IMPORTANT]
> Resideo runs **_two_ parallel systems**. This integration supports the _newer_ one only — ElitePRO
> S1200, X8S, T9/T10. It does **not** support the older Lyric one, which is where the **T5, T6
> and Lyric Round** live. [Supported devices](#supported-devices) has the breakdown and what to
> use instead.

## What you get

Each thermostat becomes a Home Assistant device, and every wireless room sensor gets one too.
Entities only appear when your hardware actually supports them — no dead tiles.

### Thermostat

| Entity | Type | Notes |
| --- | --- | --- |
| Thermostat | `climate` | Current temperature & humidity; heat / cool / off (+ auto where supported); target temperature or range; fan **Auto / Circulate / On**; presets **None / Temporary hold / Permanent hold** |
| Indoor / Outdoor temperature | `sensor` | Shown in your Home Assistant unit system (°F/°C) |
| Indoor / Outdoor humidity | `sensor` | |
| Carbon dioxide, VOC | `sensor` | Air-quality models only |
| Connectivity | `binary_sensor` | Reports **Disconnected** when the thermostat drops offline |
| Fan, Circulation fan | `binary_sensor` | Whether air is moving, and why |
| Adaptive recovery active | `binary_sensor` | Pre-heating/cooling ahead of a schedule period |
| Air filter, Fault | `binary_sensor` | Complains when something's wrong |
| Feels Like | `switch` | Target the perceived (feels-like) temperature instead of the measured one |
| Adaptive recovery | `switch` | a.k.a. Smart Response |
| Schedule | `switch` | Follow or ignore the programmed schedule |
| Emergency heat | `switch` | Shown only when the thermostat reports emergency-heat support |
| Heat/Cool setpoint min & max | `number` | Guardrails for the setpoint range |
| Freeze protection floor | `number` | A 35–45 °F "pipes shall not freeze" floor |

<details>
<summary>The nerd drawer: ~45 diagnostic entities, if you're into that</summary>

Heat/Cool setpoint, Hold status, Equipment status, Demand, Current stage, Air / CO2 / VOC /
Humidity quality, Schedule period / day / type, Backlight, Room priority, Air filter remaining,
Firmware (+ status, last updated), Faults, Signal strength, Heat/cool mode, Fan reason, Demand
response, Adaptive recovery mode, Ventilation & ventilation-boost timers, Language, Registered,
Heating/Cooling system & stages, Temperature units, Matter status, Priority status — plus
Vacation hold, Freeze protection, Away mode, and Commercial mode binary sensors.

</details>

### Wireless room sensors

| Entity | Type | Notes |
| --- | --- | --- |
| Temperature, Humidity | `sensor` | Per-room readings the thermostat averages |
| Carbon dioxide, VOC | `sensor` | Air-quality sensor models only |
| Motion, Occupancy | `binary_sensor` | |
| Exclude motion / Exclude temperature | `switch` | Drop this room from occupancy/averaging |
| Occupancy sensitivity | `select` | Takes effect at the sensor's next check-in (battery life comes first) |
| Battery, Signal strength, Status | `sensor` | Diagnostic |

<img align="right" width="300" src="https://raw.githubusercontent.com/sfcodes/ha-resideo/main/docs/images/device-page.png" alt="Resideo thermostat device page in Home Assistant">

## Installation

The one-click way:

[![Open your Home Assistant instance and open this repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=sfcodes&repository=ha-resideo&category=integration)

The clicking-around way:

1. HACS → Integrations → ⋮ → **Custom repositories** → add
   `https://github.com/sfcodes/ha-resideo`, category **Integration**.
2. Install **Resideo**, then restart Home Assistant.

<details>
<summary>No HACS? The copy-paste classic</summary>

Copy `custom_components/resideo/` from the latest release into your Home Assistant
`config/custom_components/` directory and restart. The integration is fully self-contained —
the async API client (`aioresideo`) is vendored inside it, and the only runtime dependency is
`aiohttp`, which Home Assistant already provides.

</details>

## Configuration

[![Open your Home Assistant instance and start setting up a new integration.](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start/?domain=resideo)

Or: Settings → Devices & Services → **Add Integration** → **Resideo**. Sign in however you
like:

- **Email and password** — your everyday Resideo credentials (sent only to Resideo's own
  sign-in endpoint; only the resulting refresh token gets stored). Try this first.
- **Sign in with your browser** — opens Resideo's own sign-in page so you log in there
  instead, then you paste the redirect back. Slower, but it's the one that works when
  Resideo's bot detection blocks the direct login (see Troubleshooting).
- **Refresh token** — already have an Auth0 refresh token and prefer pasting to typing? Go
  for it.

Picking one isn't a commitment: any failed attempt puts you back on this list, with an
explanation of what went wrong, so you can switch paths without restarting setup.

One entry per account — adding the same account twice gets politely rejected. And if the token
ever dies (password change, revocation), you get a re-authentication prompt instead of a
silently broken integration.

## Data updates

This integration is `cloud_push`: after one REST bootstrap against Resideo's
native API at `api.ha.resideo.com` (the same backend the app uses), it parks on a persistent
Azure SignalR stream — so thermostat, app, and schedule changes land in Home Assistant in
**~1–3 seconds**, including the ones someone makes on the wall. Your own commands show up
instantly (optimistically), get confirmed by the stream, then double-checked by a quiet
reconcile — no flicker, no stale values.

If the stream can't be established, setup fails and retries — there's no polling fallback;
this integration simply doesn't poll.

## Supported devices

This works with thermostats on Resideo's **current** system, signed in with the same
email/password you use in the Resideo (or First Alert) mobile app. Resideo runs two parallel
systems, and every thermostat sits on exactly one of them:

| Thermostat | System | Supported here |
| --- | --- | --- |
| **ElitePRO S1200 Smart**, **X8S Smart** — with wireless room sensors | Resideo, current | ✅ Built and tested against these |
| **T9 / T10 Smart** and newer models | Resideo, current | ☑️ Expected to work — let me know if you try one out |
| **T5**, **T5+**, **T6 Pro**, **Lyric Round** | Lyric (LCC), older | ❌ [Not supported](#why-the-t5-and-t6-dont-work) |

Smoke detectors and other Resideo products aren't supported yet — if you own one and want to
help wire it up, contributions are warmly welcome.

### Why the T5 and T6 don't work

They're on the **older Lyric system** — _LCC_, Lyric Connected Comfort, internally — which is
why Honeywell's own API lumps that whole family into a single `T5-T6` model and hands out device
IDs prefixed `LCC-`. Resideo's newer hardware launched on the current system, and the two don't
cross over: **a T5 never appears in the Resideo account graph at all.**

Sign-in still succeeds, because your Resideo account spans both systems — so setup gets all the
way to "no supported thermostats" before it fails. That's the account working as intended; it
simply holds nothing this integration can drive.

## Troubleshooting

**Something acting up? Grab a debug log.** Settings → Devices & Services → **Resideo** →
**Enable debug logging**. (Flip it off again and Home Assistant hands you the captured log.)
YAML fans:

```yaml
logger:
  logs:
    custom_components.resideo: debug
```

**Download diagnostics.** On the integration (or any device) page: ⋮ → **Download
diagnostics**. It's the raw device state with tokens, serial numbers, and MAC addresses
already scrubbed — perfect for bug reports.

**Filing an issue?** Bring receipts: the Home Assistant and integration versions, the
diagnostics file, and a debug log covering the moment things went sideways.

**Sign-in fails with a CAPTCHA.** Resideo's sign-in sometimes decides a login looks like a bot
and demands a CAPTCHA, which Home Assistant has no way to solve — it will say so. It's not your
password; ordinary bad credentials get their own distinct message, so the two are never
confused.

The CAPTCHA message comes with the other sign-in methods listed right underneath it, **Sign in
with your browser** first. It hands you Resideo's real sign-in page, you log in
there like any other website, and you paste the resulting redirect back into Home Assistant. In
practice the CAPTCHA doesn't even appear — Resideo's bot detection is reacting to the headless
login, not to you. The step includes click-by-click instructions; the one thing that trips
people up is that your browser's Network panel has to be open **before** you sign in.

**Setup fails with "No supported thermostats in this Resideo account."** Your sign-in worked —
the account just holds nothing this integration can drive. The message lists what it *did* find,
which is usually the giveaway; if that list is empty, or your thermostat is a T5/T6, see
[Supported devices](#supported-devices). This one doesn't retry on its own, because it isn't a
temporary failure: sort out the account side, then reload the entry.

(Versions up to 0.2.0 reported this as `No SignalR-capable thermostat locations found`. Same
cause — and that's *SignalR*, Microsoft's push-messaging service, not anything to do with
infrared.)

**"Cannot connect" during setup** usually means a firewall or proxy is eating outbound
WebSockets to `*.service.signalr.net`. The stream isn't optional, so un-block it and try
again.

**"Resideo's cloud is refusing requests", and everything went unavailable.** Every call is
coming back as HTTP 503, and Home Assistant raises a repair notice quoting whatever Resideo's
servers said. That response looks identical whether Resideo is having an outage or has simply
stopped serving the address this integration uses — so open the First Alert app on your phone,
which settles it in seconds. If the app is broken too, it's an outage: wait, and everything
comes back on its own. If the app works normally, the endpoint has most likely been retired
and you need a newer version of this integration. Resideo did precisely that in September
2026, moving the consumer API to a new host and leaving the old one answering "The API is
temporarily down for planned maintenance" indefinitely — which is why the notice never tells
you that waiting will help.

Resideo posts confirmed outages at [status.resideo.com](https://status.resideo.com). Treat a
green status page as weak evidence, though: it reported every service operational — "First
Alert App" included — right through the September 2026 move, while the retired host had
already been refusing every request for well over a day. The phone app is the reliable test.

## Known limitations

> [!WARNING]
> **Unofficial & reverse-engineered.** This integration mimics the mobile app against an
> undocumented API; Resideo may change or cut off access at any time. Use at your own risk.

- **The Resideo cloud speaks Fahrenheit**, whatever your thermostat or app displays. Home
  Assistant converts everything to your configured unit system, so Celsius households see
  °C throughout — but the handful of °F-native controls (like the freeze-protection floor)
  step in whole °F.
- **Temporary hold** only exists while a schedule is enabled and followed; with the schedule
  off, setpoint changes are permanent holds — exactly like the app.
- **Vacation hold** and **Hold until** show up when the device reports them, but can't be
  started from Home Assistant yet.

## Removing the integration

Leaving? No hard feelings. Settings → Devices & Services → **Resideo** → ⋮ → **Delete**. If
you also delete the files, restart afterwards. Devices that vanished from your Resideo account
can be removed one-by-one from their device pages.

## Development

PRs and bug reports welcome — the setup is the usual:

```bash
python -m venv .venv && source .venv/bin/activate
pip install ruff -r requirements.txt -r requirements.test.txt
ruff check .
pytest   # tests/aioresideo (client) + tests/resideo (HA integration layer)
```

The vendored client has its own docs in [`docs/CLIENT.md`](docs/CLIENT.md). The repo doubles
as a local Home Assistant dev instance under `config/` (gitignored), with
`config/custom_components` symlinked to `custom_components/` so your edits load live.

**Releasing:** versioning is driven from `manifest.json` via `bump2version`
(`.bumpversion.cfg`). Run the **Release** GitHub Action (choose patch/minor/major) — it runs
the tests, bumps the version, pushes a `vX.Y.Z` tag, and drafts a GitHub Release. HACS installs
from releases.

## License

[MIT](LICENSE). Go build something cozy.
