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
A drinking-water sample designated 0.3 estimated NTU by the project is a
reference assumption, not a certified measurement. The current project response
uses `0.3 × (A0 reference voltage / live A0 voltage)^2.4`. This assumed nonlinear
sensitivity makes lower voltages respond more strongly than the previous inverse
ratio; it is not DFRobot's calibrated curve. The displayed result is an
unvalidated project estimate, so its four decimal places do not indicate physical
accuracy. DFRobot's stated clean-water sensor output (~4.1 ± 0.3 V) differs
from this project's saved reference (~2.66 V reconstructed before the divider).
The 2.4 exponent was chosen to place an observed 0.279 V milk sample above 20
on this project scale. The milk sample is not a 20 NTU standard. Since a
Critical classification can create an SMS incident, test liquids can produce
alerts. Archived sensor history and the real-data pilot were gathered on older
conversion versions and cannot be compared directly with new estimates.
Run `deploy/apply_pi_turbidity_response.py --check` before `--apply` to migrate
the Pi's existing A0 reference without recapturing it. The installer refuses
to proceed when a critical turbidity safety/SMS threshold is configured.
For systems already using that squared response, run
`deploy/apply_pi_turbidity_response_v2.py --check`, then `--apply`; the original
drinking-water A0 voltage stays unchanged.

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

The Plants page has six fixed positions, numbered left to right: P1–P3 in
the top NFT row and P4–P6 in the bottom row. The camera overlay, planting
record grid, and descriptive sensor-vision fusion use that same layout.
Select a position to enter a planting date. The Pi calculates days growing;
swap moves two saved dates, and erase clears a date for a replacement plant.
Camera detection boxes do not establish plant identity, and planting age does
not automatically change the experimental AI result.

The Plants page also shows a separate harvest-readiness card for each fixed
slot. It labels a slot Harvest-Ready only when its saved planting date is at
least 30 days old and its current vision classification is Healthy. Missing
dates, missing detections, vision faults, and stale data cannot qualify. This
display rule does not alter the vision model, GSM alerts, or dosing decisions.

The six-slot update creates `plant_slots_v4` on first use and copies saved
P1–P6 dates from `plant_slots_v3`. P7/P8 dates remain archived in v3.
Camera detections are assigned to fixed thirds of each image row; missing
detections do not shift adjacent slot numbers. On the Pi, pull this branch
and run `python3 deploy/apply_pi_six_plant_slots_v4.py --check` followed by
`python3 deploy/apply_pi_six_plant_slots_v4.py --apply`. The installer validates
the reviewed eight-slot modules, backs them up, and does not control GPIO.
Restart `verde.service` to load the two new modules, then verify six records
at `/api/plant-slots` and six entries in
`/api/status` under `fusion_by_slot`.

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
and adds a separate `water_quality_real_pilot` API field. The pilot is available
through the API for comparison; its Dashboard card was removed. The official water classifier, synthetic prototype
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

### Short water-temperature recovery

`deploy/apply_pi_water_recovery_last_good.py` adds timestamped last-valid
water-temperature metadata to the Pi's cached sensor snapshot. During a
transient `RECOVERING` read, the Dashboard displays that value with a clear
"not live" note. The prototype water RF may use it for at most 90 seconds and
labels its result `EXPERIMENTAL_RECOVERING`. After 90 seconds, on a persistent
`ERROR`, or without a prior valid reading, the prototype remains unavailable.
The current sensor value stays null throughout recovery. Fusion reliability
remains Low and the backend's safety override remains in force. Humidity,
GPIO, calibration, SMS, and dosing behavior are unchanged.

```bash
cd ~/VERDEapp
python3 deploy/apply_pi_water_recovery_last_good.py --check
python3 deploy/apply_pi_water_recovery_last_good.py --apply
sudo systemctl restart verde.service
```

The installer backs up each updated Pi file and does not restart the service.

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
# Pi alert and GSM update

The alert update names the critical or faulty sensor, identifies a camera or
plant-slot vision failure, and sends a separate Harvest-Ready SMS notice naming
the fixed plant slot. Harvest-Ready remains a notification in the app and does
not require acknowledgement. Pest detection remains a separate SMS event.
Routine water-temperature and humidity range deviations stay dashboard
warnings; a *faulty* sensor remains an SMS event. The GSM sender retries failed
dispatches while an incident remains active, no more often than once per minute.
The update does not alter GPIO, thresholds, recipient settings, or automation.

On the Pi, after pulling this branch, run:

```bash
cd ~/VERDEapp
python3 deploy/apply_pi_alerts.py --check
python3 deploy/apply_pi_alerts.py --apply
python3 -m py_compile ~/VERDE-Sensor-Integration/app/service.py \
  ~/VERDE-Sensor-Integration/app/notifications/alert_policy.py \
  ~/VERDE-Sensor-Integration/app/notifications/sms_text.py
sudo systemctl restart verde.service
```

The installer backs up the touched backend files and never sends a test SMS.
After restarting, inspect `journalctl -u verde.service` and the app's Alerts
page during a real qualifying event. Do not deliberately induce a water or
camera fault just to test alerts.

For an existing alert v1 installation, also run
`python3 deploy/apply_pi_alerts_v3.py --check` and then
`python3 deploy/apply_pi_alerts_v3.py --apply` before restarting. This replaces
the earlier v2 alert grouping: temporarily unclassified plant slots remain
visible in per-slot fusion and do not trigger a Faulty Vision SMS. Actual
camera capture or plant-analysis failures still qualify for SMS.

If the modem echoes an SMS but replies later, install the SIM800 confirmation
reader with `python3 deploy/apply_pi_sms_confirmation.py --check` followed by
`python3 deploy/apply_pi_sms_confirmation.py --apply` and restart the service.
The sender waits for a final `+CMGS` and `OK` response. If confirmation never
arrives, it records `UNCONFIRMED` rather than claiming delivery or retrying an
SMS that might already have been accepted.

To space all GSM alerts and notices, install the shared 30-second SMS gap:

```bash
cd ~/VERDEapp
python3 deploy/apply_pi_sms_spacing.py --check
python3 deploy/apply_pi_sms_spacing.py --apply
python3 -m py_compile ~/VERDE-Sensor-Integration/app/service.py \
  ~/VERDE-Sensor-Integration/app/notifications/__init__.py
sudo systemctl restart verde.service
```

This applies to different alert types as well as retries after a modem error.
An SMS waiting for its turn stays pending while its issue remains active; it is
not sent if the issue clears first. The gap is measured within the running
service and resets when the service restarts. The installer sends no test SMS.

# Pi pH 6.86 buffer adjustment

With the pH probe resting in a labeled 6.86 buffer, run:

```bash
cd ~/VERDEapp
python3 deploy/calibrate_pi_ph_686.py --check
python3 deploy/calibrate_pi_ph_686.py --apply
python3 -m py_compile ~/VERDE-Sensor-Integration/verde_sensor_service.py
sudo systemctl restart verde.service
```

The script reads five consecutive, fresh, non-spiking ADS1115 A1 samples. It
waits for a stable voltage window, backs up the Pi's untracked sensor service,
and adjusts only the pH intercept. The existing slope is retained. This is a
single-point offset adjustment; checking the slope requires a second buffer.
The script never reads hardware directly or sends a test SMS. After restart,
check the live pH reading while the probe remains in the 6.86 buffer.

For the later provisional **two-point commercial-meter fit**, the recorded
references are 2.803375 V = 6.81 pH and 2.377750 V = 9.45 pH. The alkaline
filtered voltage was repeated, but its raw voltage fluctuated; the meter also
varied roughly 9.3–9.6 pH. The 4.41 acidic reference is excluded because its
A1 voltage reached the ADC supply. Values below 6.81 pH therefore remain
extrapolations, not validated by this fit.

```bash
cd ~/VERDEapp
python3 deploy/apply_pi_ph_two_point.py --check
python3 deploy/apply_pi_ph_two_point.py --apply
python3 -m py_compile ~/VERDE-Sensor-Integration/verde_sensor_service.py
sudo systemctl restart verde.service
```

The installer backs up the sensor service, writes a calibration provenance
record in the Pi home directory, and changes only its pH slope and intercept.
It does not send an SMS. After restarting, compare VERDE with the commercial
meter in the same solution before using pH values for data gathering.

# Pi EC two-point tap-water adjustment

The saved post-hardware-fix A2 reference is 0.553125 V at 1.413 mS/cm
(25 °C). A separate EC meter measured the current tap-water sample at
0.138 mS/cm. While the VERDE EC probe remains in that tap-water sample, run:

```bash
cd ~/VERDEapp
python3 deploy/calibrate_pi_ec_tap_two_point.py --check
python3 deploy/calibrate_pi_ec_tap_two_point.py --apply
python3 -m py_compile ~/VERDE-Sensor-Integration/verde_sensor_service.py
sudo systemctl restart verde.service
```

The installer captures five fresh, stable A2 acquisitions, fits a straight
line through the two references, preserves the V2 record, backs up the live
sensor service, and stores a separate V3 record in the Pi home directory.
Below the lower point the linear estimate is clamped to zero; above the
higher point it is extrapolated. The tap-water meter temperature was not
recorded, and no temperature compensation was derived. Older EC History and
the real-data RF pilot used a different conversion, so their values are not
directly comparable. A Critical EC condition may send SMS after the restart.

# Pi live automation mode source

The pre-pump savepoint is Git tag `pre-pump-automation-20261029` and the Pi
archive is `/home/verde/verde-pre-pump-automation-20261029-014001.tar.gz`.
The initial mode evaluator reads legacy disabled adapters on the Pi, so it may
report a safety override while the integrated pH, EC, temperature, and
turbidity cache is healthy. To change only the mode decision source:

```bash
cd ~/VERDEapp
python3 deploy/apply_pi_live_automation_mode.py --check
python3 deploy/apply_pi_live_automation_mode.py --apply
python3 -m py_compile ~/VERDE-Sensor-Integration/app/service.py \
  ~/VERDE-Sensor-Integration/app/automation/live_mode.py
sudo systemctl restart verde.service
```

The installer backs up `app/service.py`, validates exact source anchors,
and never writes GPIO. Physical outputs remain disabled. A Critical water
condition, persistent required-sensor fault, stale acquisition, camera fault,
or plant-model fault moves a requested Full mode to Semi and stops circulation.
When the condition clears, the previously requested Full mode becomes active
again. Humidity is excluded from this
override. Temporary recovery or no plant detection holds dosing eligibility
without treating either as a confirmed hardware fault.

The separate `pi_pump_decision.py` module is a proposed, pure decision policy;
it is not installed by this mode patch. It uses a 60-second mixing wait and
requires an explicit dose duration and physically verified GPIO24 flow level.
`pi_pump_flow_observations.json` records Pump 1 at 0.82 mL/s, Pumps 2 and 3
as shared-model estimates, and the corrected 18 L operating reservoir. Those values
do not activate pumps or establish a chemical dose.

The corrected 18 L operating reservoir allows each pump to request at most
3.69 mL over 4.5 seconds at the assumed 0.82 mL/s rate. There is no rolling
24-hour volume limit; the next decision must still wait 60 seconds after the
previous dose and use a fresh reading, and it stops when the target range is
reached.
The pH course amounts are arithmetic estimates from the sequential 2 L test,
not verified doses for the 18 L reservoir. A Critical reading, including
pH 8.5 or EC 0.3 mS/cm, overrides to Semi, stops circulation, and blocks
automatic dosing. The gateway enforces one-pump-at-a-time, the 4.5-second
pulse cap, and the 60-second mixing wait; it does not impose a rolling
24-hour volume block. Physical control remains disabled until the
existing manual pump controller can be invoked securely and GPIO24's actual
flow and stop behavior has been checked with the NC load.

The circulation pump was observed flowing with GPIO24 in `no pd` mode. That
does not establish its driven HIGH/LOW behavior. The existing manual
`circulation on/pause` commands assume LOW=flow and must not be used for this
verification. With a person watching actual water flow, run
`sudo python3 deploy/verify_pi_circulation_gpio24.py --run` from `~/VERDEapp`.
It checks that physical output is disabled, drives HIGH for at most five
seconds, restores `no pd`, then drives LOW for at most five seconds and restores
`no pd` again. Record whether water flowed in each state. A relay LED alone
does not answer this question. The test does not enable automation or dose.

Two supervised repetitions subsequently observed GPIO24 HIGH=water flowing,
LOW=water stopped, and baseline `no pd`=flowing. The circulation pump was
unplugged again while configuring the integration. The protected gateway
installer, `deploy/install_pi_auto_pump_gateway.py`, copies the existing
manual controller to a root-owned directory and adds a scoped service command
path. It starts disarmed and changes no GPIO. Its root-owned ledger enforces
one dosing command at a time, at most 4.5 seconds per automatic command,
and at least one minute between completed doses. An
interrupted dose remains blocked pending manual inspection. Arming requires
the circulation pump reconnected and actual flow observed; the web service
uses the installed pump runtime while the gateway remains disarmed.

`deploy/apply_pi_pump_runtime.py` installs that separate service integration
after the protected gateway is installed. It backs up the Pi service, copies
the guarded decision and runtime modules, and does not restart the service.
On restart, the service requests dosing pins OFF and circulation STOP, then
reports a Semi-Automation safety override while the gateway is disarmed.
Armed operation uses the integrated live sensor snapshot, respects the
60-second mixing wait and root-owned dose history, and runs
circulation at GPIO24 HIGH in normal operation. A Critical reading, Faulty
Sensor, Faulty Vision, stale acquisition, or system fault requires GPIO24
LOW/STOP and selects Semi-Automation. Temporary unclassified vision holds
dosing without stopping circulation. When the condition clears, the requested
Full mode can resume.

`deploy/apply_pi_circulation_policy.py` updates those three policy modules in
one guarded transaction. It accepts only the reviewed installed module hashes
and backs up each file before editing. The gateway remains disarmed.

`deploy/apply_pi_pump_confirmation.py` adds a guarded `/api/confirm` action
for one farmer-confirmed dose in Semi-Automation. It rechecks a fresh integrated
sensor snapshot, correction eligibility, circulation state, the one-minute
mixing wait, and the root-owned dose history immediately before requesting
the existing pump controller. The dashboard shows one confirmation button
for each eligible recommendation so the farmer can select pH Up, pH Down, or
nutrients individually. The protected gateway
still rejects every dose while disarmed. The installer backs up each changed
Pi file and never arms the gateway or switches a pump.

The user subsequently corrected the operating reservoir to 18 L. The
provisional per-dose limit uses 18/20 of the original 20 L
proposal: one pulse is at most 3.69 mL over 4.5 seconds. This is an upper
bound, not a predicted correction. The earlier 12.5 L installer is retired.
To update the protected Pi gateway, put the service in Semi-Automation, use its
interactive `disarm` command, run `deploy/install_pi_auto_pump_gateway.py`,
then apply `deploy/apply_pi_reservoir_18.py` and restart `verde.service`.
The protected installer backs up the old gateway and refuses an armed update;
the backend installer verifies the reviewed gateway, disarmed state, and
source hashes before writing. Circulation remains stopped until a person
physically confirms flow with the revised gateway's interactive `arm` command.

For the paper's pH dosing objectives, `deploy/apply_pi_ph_objective_logging.py`
adds pH 5.5–6.5 and EC 1.2–1.8 recommendation fallbacks when local limits are
null, matching the existing automatic decision thresholds. After a successful
Full-Automation dose, it records a structured `actuator` event in the system
database with pump, action, requested duration, estimated volume, and sensor
sample timestamp. A failed event write makes Semi-Automation active and requests
all pumps OFF; the requested Full mode is retained for recovery after database
logging succeeds again. The guarded installer backs up changed files and requires the
gateway to be disarmed. Critical readings still override to Semi-Automation;
Objective 6's automatic pH-Up test therefore uses 4.5 ≤ pH < 5.5, and
Objective 7's automatic pH-Down test uses 6.5 < pH ≤ 8.0, with other required
inputs noncritical and fresh. The actual motor duration and delivered volume
must be observed separately from the software's requested duration and
estimated volume.

`deploy/apply_pi_pump_dose_settings.py` adds per-pump requested volumes to the
dashboard Settings page. Pump 1 is nutrients, Pump 2 is pH Up, and Pump 3 is
pH Down. In Semi-Automation, the farmer may save a separate target above zero
and at most 3.69 mL for each pump. The values persist in
`/home/verde/VERDE-Sensor-Integration/pump_dose_settings.json`; saving never
activates a pump. The service converts each target using the provisional
0.82 mL/s rate and still applies the protected gateway's 4.5-second pulse,
one-pump-at-a-time rule and 60-second mixing wait.
The installer checks the reviewed 18 L runtime, backs up every changed backend
file, and requires the gateway to be disarmed before applying. After restarting
the service, physically verify circulation and arm the gateway again.

The pump policy update in `deploy/apply_pi_pump_policy_v2.py` retains the farmer's
requested Full mode during a Critical, Faulty Sensor, Faulty Vision, stale
sample, or controller override. The active mode becomes Semi and circulation
stops. Once the next fresh evaluation clears the fault, Full mode and
circulation resume automatically if Full was requested. A farmer-selected Semi
mode stays Semi. A farmer-confirmed dose requires an explicit selection of one
currently recommended pump. Automatic dosing stays blocked in Critical and faulty conditions. Pump
1/2/3 doses are available in History through `/api/pump/history`, including
older events beyond the general event feed's last 30 rows. Dose volumes shown
there are estimates from the assumed flow rate, not measured delivery.

For the installed Pi at commit `abe6b12`, update the disarmed gateway and
backend while someone watches circulation:

```bash
cd ~/VERDEapp
git pull --ff-only origin feature/android-pwa-install
python3 deploy/install_pi_auto_pump_gateway.py --check
python3 deploy/apply_pi_pump_policy_v2.py --check
sudo /usr/local/libexec/verde_auto_pumps.py disarm
sudo python3 deploy/install_pi_auto_pump_gateway.py --apply
python3 deploy/apply_pi_pump_policy_v2.py --apply
python3 -m py_compile ~/VERDE-Sensor-Integration/app/service.py \
  ~/VERDE-Sensor-Integration/app/web/__init__.py \
  ~/VERDE-Sensor-Integration/app/database/__init__.py \
  ~/VERDE-Sensor-Integration/app/automation/{live_mode,pump_runtime,pump_decision}.py
sudo systemctl restart verde.service
systemctl is-active verde.service
sudo -n /usr/local/libexec/verde_auto_pumps.py status
```

The installers make timestamped backups. This sequence does not dose. The
gateway stays disarmed and circulation stopped until a supervised `arm` with
physical flow confirmation. On service restart the requested mode starts in
Semi, so Full must be selected again on the dashboard after checking live
readings and circulation flow.

The dashboard displays live pH/EC correction recommendations even while a
Critical condition stops circulation and automatic dosing. With the later
`deploy/apply_pi_critical_manual_dosing.py` update, a person can explicitly arm
manual dosing on the Pi while circulation stays stopped, select one recommended
pump in Semi-Automation, and confirm a bounded pulse. The service rechecks the
matching pH or EC sensor immediately before the command. A faulty or stale
matching sensor cannot authorize its pump. The operator must watch delivery,
mix the reservoir manually, and verify with a separate meter before another
dose. A Critical manual correction uses a fixed 4.5-second pulse, estimated at
3.69 mL using the provisional 0.82 mL/s flow rate; the delivered volume must
be measured separately. If a new post-dose reading still calls for correction,
the farmer must confirm another dose. A pre-dose reading cannot authorize a
repeat. The gateway retains the 4.5-second maximum pulse, one pump at a time,
and a 60-second minimum gap. Manual arming never permits automatic dosing while
the water remains Critical or faulty. With the later automatic flow-resume
update, a manual session started from a supervised flow arm retains that proof.
If Full was requested, fresh Optimal or Suboptimal readings and a post-dose
mixing wait return the gateway to flow mode and the active mode to Full.
A manual session started without prior flow confirmation remains Semi until
an operator physically verifies flow with the normal `arm` command.
When pH and EC are both Suboptimal in Full mode, the first eligible pulse
corrects pH. If EC is still below 1.2 mS/cm after that pulse, Pump 1 gets the
next eligible turn after the 60-second gateway wait and a newer sensor sample.
Only one pump runs at a time. A fresh Critical reading temporarily makes Semi
active; fresh valid Optimal or Suboptimal water readings select Full again.
For Critical water readings, a supervised flow arm remains valid when the
controller stops circulation. The Dashboard offers only the specific pH/EC
correction supported by a fresh matching sensor. A farmer must select and
confirm one pump; the protected gateway requires circulation STOP, limits the
pulse to 4.5 seconds, and keeps the 60-second repeat wait. A pure vision fault
does not offer a correction pump. Check a separate meter before and after any
Critical correction. `deploy/apply_pi_critical_flow_manual.py` installs this
guarded runtime update after the protected gateway is updated.
The History page
shows recorded Pump 1–3 doses from the last seven days above its sensor chart,
regardless of the chart's Today/24 Hours/7 Days filter. Direct manual-controller
hardware tests are not recorded as app doses.

To install the Critical manual-dose policy, run the gateway installer `--check`
and `deploy/apply_pi_critical_manual_dosing.py --check` first. Disarm the gateway,
install the reviewed gateway with `sudo python3 deploy/install_pi_auto_pump_gateway.py --apply`,
apply the guarded backend update with
`python3 deploy/apply_pi_critical_manual_dosing.py --apply`, then compile and
restart `verde.service`. The installers back up changed files and issue no dose.
The separate `sudo /usr/local/libexec/verde_auto_pumps.py arm-manual` command
asks for a physical supervision acknowledgment and leaves circulation STOP.
Use `disarm` to end the manual session.

For water dosing, an unclassified plant is not a water-sensor fault. The guarded
`deploy/apply_pi_water_only_pump_hold.py` update removes that plant-result hold
while retaining Critical sensor and Faulty Vision overrides. With Full mode
requested and the gateway flow-armed, a fresh Suboptimal low EC reading can
request Pump 1, low pH Pump 2, or high pH Pump 3. A fresh Optimal water reading
requests no dose. Critical or faulty readings switch the active mode to Semi
and stop circulation. Once fresh readings clear, the service selects Full
automatically, including after a manual Semi correction.
The gateway still enforces one bounded pulse at a time and its mixing wait.

`deploy/apply_pi_auto_flow_resume.py` installs the guarded runtime change after
the updated root-owned gateway is installed. The gateway marks manual sessions
that started from a supervised flow arm; only those sessions can resume flow
automatically. A Critical or faulty reading still stops circulation and keeps
the active mode Semi. The first fresh normal evaluation after the 60-second
post-dose wait and a newer sensor sample can resume flow when Full is selected.
`deploy/apply_pi_auto_mode_recovery.py` installs the service rule that selects
Full when a fresh water sample is Optimal or Suboptimal with no sensor, vision,
or database hold. Run `--check`, then `--apply`, compile
`~/VERDE-Sensor-Integration/app/service.py`, and restart `verde.service`.
The installer does not disarm or switch GPIO. A normal service restart briefly
stops outputs, then the already armed gateway can restore circulation. A
manual-only arm without prior verified flow still requires the normal flow arm;
the dashboard does not claim physical Full operation while circulation is STOP.
