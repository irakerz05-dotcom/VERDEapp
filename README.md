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
EC/TDS cards show the live electrical voltage together with
`CONNECTED — CALIBRATION REQUIRED`. Raw volts are not relabeled as calibrated
pH, mS/cm, ppm or NTU values.

The installed DFRobot SEN0189 turbidity board's D output is wired to Raspberry
Pi GPIO5 (physical pin 29), separate from the ADS1115. The running Pi backend
still reads ADS1115 A0, so its voltage is unrelated to turbidity. D mode
provides a one-bit digital threshold output, not continuous NTU. The guarded
`deploy/apply_pi_turbidity_gpio5.py --check` checks a pending Pi source change
without applying it. `--apply --signal-3v3-verified` backs up the source
without restarting the service, and must be used only after the signal is
verified. **Before a service restart, verify the D output is safe for the Pi's
3.3 V GPIO input.** The board is powered at 5 V and its HIGH output voltage is
not yet verified. Once safely installed, the app displays only HIGH or LOW and
keeps numeric turbidity unavailable for automation and Random Forest. The
digital threshold polarity and potentiometer setting also remain unverified.
The legacy A0/A3 calibration utilities in `deploy/` do not apply to GPIO5.
A drinking-water sample designated 1.0 NTU by the project is a reference
assumption, not a certified measurement or a live sensor reading.

Do not connect the browser directly to GPIO or bypass backend safety decisions.

## Live sensor history

History records one row for each new integrated Pi sensor acquisition in a
separate SQLite table. It stores actual pH, EC, turbidity, water temperature,
and humidity values when valid; failed or stale readings remain empty. The
History page requests bounded views for Today, 24 Hours, and 7 Days.
Existing monitoring snapshots and automation behavior are unchanged.
Previously empty monitoring rows cannot be turned into sensor readings.

On the Pi, fetch `feature/live-sensor-history` in VERDE-Software and pull this
PWA branch. From `~/VERDEapp`, run
`python3 deploy/apply_pi_sensor_history.py --check`, then
`python3 deploy/apply_pi_sensor_history.py --apply`. The installer checks
reviewed code anchors, backs up changed backend files, and preserves the
existing database. Restart `verde.service` at a safe time; its restart may
briefly put actuators SAFE/OFF and reopen SMS incidents. New History points
should appear after the next sensor acquisition (normally about 30 seconds).

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

## Experimental water-quality Random Forest

The water-quality card shows a clearly labeled **Prototype** result when all
four Pi readings (pH, EC, water temperature, turbidity) are fresh and valid.
The model was trained on synthetic examples labeled by the paper's threshold
rules; it has no validation against labeled physical water samples. The Pi's
turbidity NTU reference is project-assigned. Missing or conflicting evidence
produces no model class. The prototype feeds the descriptive sensor-vision
fusion card only; automation, GPIO, and SMS decisions use the existing backend
inputs.

On the Pi, fetch `feature/prototype-water-rf` in VERDE-Software and pull this
PWA branch. From `~/VERDEapp`, run
`python3 deploy/apply_pi_prototype_water_rf.py --check`, then
`python3 deploy/apply_pi_prototype_water_rf.py --apply`. The installer backs up
the backend files it changes and does not restart the service. Restart
`verde.service` at a safe time, then inspect `/api/status` for
`water_quality_experimental` and `fusion`. A missing or faulty water probe
must leave the experimental result unavailable and the fusion result Low.

### Collect real readings for later validation

The Pi already stores individual acquisitions in `sensor_samples`. To export
complete four-sensor rows without interrupting the running service, pull this
PWA branch on the Pi and run:

```bash
cd ~/VERDEapp
python3 deploy/export_pi_water_quality_samples.py \
  --output ~/verde-water-quality-unlabeled-20261026.csv
```

The CSV is created outside Git, includes at most one row per 30 minutes, and
leaves its independent-reference label fields empty. Rows with missing or
invalid pH, EC, water temperature, or turbidity are excluded. Record the
physical water-sample batch and an independently measured or assessed label
before using the rows to evaluate a real model. The prototype's prediction
must not be copied into the reference-label column. The current turbidity
number uses a project-assigned drinking-water reference, so record that
limitation with any dataset. Re-running the command requires a new output
filename; existing exports are never overwritten.

To record a specific physical solution as its own batch, let the probe settle
in that solution, then run on the Pi:

```bash
cd ~/VERDEapp
python3 deploy/capture_pi_water_batch.py --batch-id solution-one
```

The command waits for a new complete cached acquisition after it starts and
appends one row to `~/verde-water-quality-batches.csv`. It does not trigger a
hardware read. Use the **same** batch ID for repeat readings of one physical
solution; use a new ID only when the physical water sample changes. The
reference label, method and label time stay blank until independently
established. Do not infer a class from the prototype, liquid color, or a new
batch ID. A failed water sensor makes capture fail without writing a row.

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
- Do not add credentials, Wi-Fi passwords, GSM details, `.env` files, physical training datasets, logs, or databases to Git. The synthetic prototype artifact in VERDE-Software is documented and reproducible.
