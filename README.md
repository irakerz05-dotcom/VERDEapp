# VERDE

Vegetation Environment Recognition and Detection Engine - an IoT-based hydroponics system with sensor-vision fusion for plant health monitoring and nutrient management.

## Current state

This repository contains the mobile-first Progressive Web App (PWA) for the
validated VERDE Raspberry Pi backend. Its default data source is the same-origin
backend API. The UI does **not** control GPIO or hardware directly; sensor access,
mode validation, safety overrides, and future actuation remain server-side.

An explicit mock adapter is retained for frontend-only development. Live API
failures never silently fall back to mock measurements.

## Run locally

This project has no package installation step. Use any static file server from the repository root. For example, if Python is installed:

```powershell
python -m http.server 4173
```

Then open `http://localhost:4173/?api=mock` in Chrome. Opening `index.html`
directly can show the interface, but service-worker installation needs an HTTP
server. Without `?api=mock`, the PWA expects `/api/*` on the same origin and
will correctly report that the backend is unavailable.

## Run with the VERDE backend

Keep this repository and `VERDE-Software` in sibling directories. From the
backend directory, run:

```powershell
python run.py --web-root ..\VERDEapp
```

On Raspberry Pi OS, the equivalent command is:

```bash
.venv/bin/python run.py --web-root ../VERDEapp
```

Open `http://127.0.0.1:8000`. The backend serves the PWA and its API from one
origin, preserving its Host, Origin, and session-token checks. The previous
backend dashboard remains available at `/legacy` while `--web-root` is active.

### Run the frontend with a separate backend port

Keep the PWA on port `8000` for Tailscale while the Raspberry Pi backend runs
on port `8001`. The included systemd service serves the PWA and proxies
`/api/*` and camera requests to the backend. Install it once:

```bash
sudo cp deploy/verde-frontend.service /etc/systemd/system/verde-frontend.service
sudo systemctl daemon-reload
sudo systemctl enable --now verde-frontend.service
```

Start the backend on port `8001`:

```bash
cd ~/VERDE-Software
.venv/bin/python run.py --port 8001
```

The frontend service starts automatically after boot and keeps port `8000` for
the existing Tailscale Serve configuration. If the backend is stopped, the
website remains accessible and shows `Faulty Sensors` and `Faulty Camera`.

## Test locally

The automated tests use Node's built-in test runner and require no downloaded dependencies:

```powershell
node --test
```

The explicit mock adapter also supports development-only states through query
parameters such as `?api=mock&mockOffline=1`, `?api=mock&mockError=1`, or
`?api=mock&mockDelay=5000`. These affect only local mock behavior and never
connect to hardware.

## Android installation

The supported remote design is private Tailscale Serve, not a public port or
Tailscale Funnel. The backend stays bound to `127.0.0.1`; Tailscale terminates
HTTPS, applies tailnet access controls, and forwards an authenticated identity
to the loopback service. Start the backend with its exact private origin:

```bash
python3 run.py --web-root ../VERDEapp \
  --trusted-origin https://YOUR-PI.YOUR-TAILNET.ts.net
tailscale serve --bg 8000
tailscale serve status
```

The Raspberry Pi and Android phone must be signed into the approved tailnet.
Open the HTTPS URL in Android Chrome, then use the VERDE Settings page's
**Install app** button or Chrome's **Install app / Add to Home screen** menu.
Never use `tailscale funnel`, router port-forwarding, or a public HTTP URL for
this prototype.

Installation does not imply calibration or model readiness. The installed app
continues to show live DHT11, DS18B20, camera, and ADS1115 electrical evidence;
uncalibrated chemistry remains explicitly marked **CALIBRATION REQUIRED**, AI
components remain unavailable until trusted models are integrated, and
physical outputs remain disabled.

The service worker caches only the application shell. `/api/*` responses and
camera readings are always network-only, so reopening the app without a Pi
connection cannot present old readings as live. Frontend releases show an
update-ready message and take effect after the installed app is closed and
reopened.

The Alerts page distinguishes active, acknowledged and resolved incidents.
Acknowledging an incident records that the farmer has seen it; it does not
resolve the underlying condition, enable automation or operate any hardware.
History includes the detected, acknowledged and recovered transitions as an
audit timeline. Stale samples and failed refreshes remain visibly marked and
provide a manual retry action.

## Raspberry Pi integration

`js/services/verde-api.js` contains both the live `VerdeApi` adapter and the
development-only `MockVerdeApi`. The live adapter uses `/api/status`,
`/api/history`, `/api/events`, `/api/session`, `/api/mode`, and camera-frame
URLs supplied by the backend. It preserves missing sensor/model values as
unavailable instead of fabricating results.

When the backend supplies ADS1115 `raw_value` and `raw_unit` metadata, the pH,
EC/TDS and turbidity cards show the live electrical voltage together with
`CONNECTED — CALIBRATION REQUIRED`. Raw volts are not relabeled as calibrated
pH, mS/cm, ppm or NTU values.

When the turbidity backend rejects an incompatible calibration but still provides
an A0 voltage, the turbidity card shows that live voltage as an uncalibrated
signal in V. It does not report NTU or claim that the probe is connected.

Do not connect the browser directly to GPIO or bypass backend safety decisions.

## NFT planting records

The Plants page has 12 fixed positions: top NFT row Plant 1–6 from right to
left, bottom NFT row Plant 7–12 from right to left. Select a position on the
camera image or in the slot grid to enter a planting date. The Pi stores dates
in its existing SQLite database and calculates the days growing. Swap moves
two saved dates when plants are physically moved; erase clears a date for a
replacement plant. Camera detection boxes do not establish plant identity,
and planting age does not automatically change the experimental AI result.

On the Pi, fetch `feature/planting-slots` in VERDE-Software and pull this PWA
branch. Then run `python3 deploy/apply_pi_plant_slots.py --check` followed by
`python3 deploy/apply_pi_plant_slots.py --apply` from `~/VERDEapp`.
The installer backs up the existing backend web module. Restart
`verde.service` at a safe time because its restart can briefly set actuators
SAFE/OFF and may reopen SMS incidents. Afterward, check
`http://127.0.0.1:8000/api/plant-slots` on the Pi.

## Development workflow across computers

GitHub is the source of truth. Before switching computers, commit and push your finished work:

```powershell
git status
git add .
git commit -m "Describe the change"
git push
```

On the other computer, clone once, then pull before continuing:

```powershell
git clone https://github.com/irakerz05-dotcom/VERDEapp.git
cd VERDEapp
git pull
```

Signing in to ChatGPT/Codex with the same account does not replace GitHub as the project backup. Keep the repository pushed so the source and project context are available everywhere. See OpenAI's [Remote connections documentation](https://learn.chatgpt.com/docs/remote-connections) for remote access to a supported desktop session.

## Safety

- The PWA is interface-only; it must never directly address Raspberry Pi GPIO.
- Mode changes and dosing confirmations must be validated by the backend.
- Critical, Faulty Sensor, and Faulty Vision states must remain backend-enforced safety overrides to Semi-Automation Mode.
- API GET responses are network-only in the service worker; stale live readings are never installed as offline cache entries.
- Do not add credentials, Wi-Fi passwords, GSM details, `.env` files, model weights, datasets, logs, or databases to Git.
