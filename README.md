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

The DFRobot SEN0189 turbidity board is now set to analog output and connected
to ADS1115 A0 through a voltage divider: 1 kOhm from the sensor output to A0,
and 2 kOhm from A0 to ground. A0 should receive two-thirds of the sensor
output. DFRobot specifies an analog output range of 0 to 4.5 V, so this
divider puts the specified maximum at 3.0 V, below the ADS1115's 3.3 V
supply. The live Pi backend reads A0; its previous A3 calibration record must
be replaced with a fresh A0 reference from the drinking-water sample. Run
`deploy/calibrate_pi_turbidity_a0.py --channel A0 --check`, then `--apply`
while the probe remains in the reference water. The installer backs up the
prior calibration record and the Pi service must be restarted separately.
Capture waits up to ten minutes for five consecutive stable A0 samples and
leaves the old record in place if the signal keeps drifting or spiking.
The older GPIO5 digital-threshold installer remains in `deploy/` but does not
apply to the current analog connection; do not run it.
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

The Plants page has 10 fixed positions: top NFT row Plant 1–5 from right to
left, bottom NFT row Plant 6–10 from right to left. Select a position on the
camera image or in the slot grid to enter a planting date. The Pi stores dates
in its existing SQLite database and calculates the days growing. The 10-slot
layout starts with blank dates in a new table; earlier 12-slot records remain
in the original table. Swap moves
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

For the 10-slot layout on an already updated Pi, run
`python3 deploy/apply_pi_ten_plant_slots.py --check` and then `--apply`.
Run `python3 deploy/apply_pi_ten_fusion.py --check` and then `--apply` to
expose one descriptive Table 3 confidence result per fixed position using
the Water Quality prototype and fresh YOLO detections. Both installers make
backups and leave the service running until a safe restart. The new date
table is blank; the original 12-slot date table is retained in SQLite.

## Experimental water-quality Random Forest

The water-quality card shows a clearly labeled **Prototype** result when all
four Pi readings (pH, EC, water temperature, turbidity) are fresh and valid.
The model was trained on synthetic examples labeled by the paper's threshold
rules; it has no validation against labeled physical water samples. The Pi's
turbidity NTU reference is project-assigned. Missing or conflicting evidence
produces no model class. The prototype feeds the descriptive sensor-vision
fusion card only; automation, GPIO, and SMS decisions use the existing backend
inputs.

During temperature or mixing changes, a raw ADC spike can accompany a fresh
median-filtered pH, EC, or turbidity reading. The experimental RF may use that
filtered reading but explicitly marks its result provisional and identifies
the fluctuating input. Faulty, stale, retained, and missing readings still
produce no class. Fusion continues to treat spike-flagged inputs as unreliable;
the real-data batch capture excludes them from training rows.

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
hardware read. It skips readings flagged as ADC spikes. Use the **same** batch ID for repeat readings of one physical
solution; use a new ID only when the physical water sample changes. The
reference label, method and label time stay blank until independently
established. Do not infer a class from the prototype, liquid color, or a new
batch ID. A failed water sensor makes capture fail without writing a row.

### Fit an offline pilot from captured readings

`deploy/train_pi_water_pilot.py` can fit a **threshold-labeled exploratory RF**
from the unlabeled batch CSV. It uses the four real Pi measurements as features,
but assigns classes with the paper's same threshold rules; this tests a fitting
workflow, not independent water-quality accuracy. A physical batch with rows
on different sides of a class boundary is rejected until a specific unsuitable
reading is explicitly excluded. The audit lists every exclusion.

```bash
cd ~/VERDEapp
python3 deploy/train_pi_water_pilot.py ~/verde-water-quality-batches.csv \
  --exclude-sample 'session.csv#boundary-reading'
```

To fit, supply a **new** output path outside Git and use a Python environment
with scikit-learn, NumPy, and SciPy installed:

```bash
~/verde-rf-pilot-env/bin/python deploy/train_pi_water_pilot.py \
  ~/verde-water-quality-batches.csv \
  --exclude-sample 'session.csv#boundary-reading' \
  --pilot-output ~/verde-water-rf-pilot.json.gz
```

The script requires at least one distinct batch per class. It reports **no
accuracy score** because those batches are all used for fitting. Its artifact
is deliberately incompatible with the live prototype loader; it does not
change the service, fusion, automation, SMS, or GPIO. The independently labeled
candidate trainer in VERDE-Software retains its five-batches-per-class and
held-out evaluation requirements.

When a newly prepared solution is captured, refit to a **new artifact path**
with `--holdout-batch new-solution-id`. The model records the training and
held-out batch IDs and does not use the held-out reading during fitting. Then
compare it offline:

```bash
~/verde-rf-pilot-env/bin/python deploy/train_pi_water_pilot.py \
  ~/verde-water-quality-batches.csv \
  --exclude-sample 'session.csv#boundary-reading' \
  --holdout-batch new-solution-id \
  --pilot-output ~/verde-water-rf-pilot-holdout.json.gz
python3 deploy/compare_pi_water_pilot.py \
  ~/verde-water-quality-batches.csv ~/verde-water-rf-pilot-holdout.json.gz \
  --exclude-sample 'session.csv#boundary-reading' \
  --batch-id new-solution-id
```

The comparison reports the pilot class beside the threshold-derived class,
without an accuracy claim. The test solution must really be a separate water
preparation; a new batch name for the same water is not an independent test.

### Show the real-reading pilot live, separately

The three-training-batch RF can be shown as an **experimental live comparison**.
`deploy/apply_pi_real_rf_live.py` checks the existing offline model at
`~/verde-water-rf-pilot-holdout-optimal02.json.gz`, backs up the Pi service,
and adds a separate `water_quality_real_pilot` API field. The dashboard shows
an additional **REAL-DATA RF PILOT** card, including any disagreement with the
paper's threshold class. The official water classifier, synthetic prototype
used for descriptive fusion, automation, SMS, GPIO, and calibration are not
changed. The model remains unvalidated and does not control hardware.

```bash
cd ~/VERDEapp
python3 deploy/apply_pi_real_rf_live.py --check
python3 deploy/apply_pi_real_rf_live.py --apply
python3 -m py_compile ~/VERDE-Sensor-Integration/app/service.py \
  ~/VERDE-Sensor-Integration/app/ml/water_quality/real_rf_pilot.py
sudo systemctl restart verde.service
```

The restart can briefly put actuators in SAFE/OFF. After startup, inspect
`/api/status` for `water_quality_real_pilot`. Keep the backup path reported by
the installer for rollback. The installer is guarded and does not restart the
service itself.

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
