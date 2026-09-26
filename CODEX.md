# VERDE project context

## Purpose

VERDE (Vegetation Environment Recognition and Detection Engine) is a thesis prototype for hydroponic Butterhead and Looseleaf lettuce. It combines IoT water-quality sensing, YOLOv8 plant/pest detection, Random Forest classification, sensor-vision fusion, dashboard alerts, and dual-mode nutrient management.

## Current repository state

This static PWA is integrated with the recovered `VERDE-Software` Raspberry Pi
backend. Live mode is the default and uses same-origin `/api/*` routes. An
explicit `?api=mock` mode remains available for frontend-only development.
Live failures never silently fall back to mock readings.

## Frontend

- Dependency-free static HTML/CSS/JavaScript PWA.
- Entry point: `index.html`.
- UI code: `js/app.js`.
- Live and mock API boundary plus backend-payload normalization: `js/services/verde-api.js`.
- Shared safe-rendering and chart helpers: `js/verde-ui.js`.
- Offline installation: `manifest.webmanifest` and `service-worker.js`.
- The UI is mobile-first and works in Android Chrome.
- Dependency-free automated tests: `tests/`, run with `node --test`.

## Backend contract

The PWA calls the local backend on the Raspberry Pi, never GPIO directly. It
uses status, snapshot history, event history, camera frames, session-token, and
mode-change routes already implemented by `VERDE-Software`. The backend can
serve this repository with `python run.py --web-root ../VERDEapp`, keeping all
requests same-origin. Physical confirmation/actuation remains blocked.

## VERDE domain rules to preserve

- Water classifier inputs: pH, EC, water temperature, turbidity. Humidity is independent.
- Plant classes: Healthy, Yellowing, Wilting, Harvest-Ready. Pest detection is presence-only.
- Water-quality status: Optimal, Suboptimal, Critical.
- Fusion confidence is informational only: High, Medium, Low. It must not directly control actuators.
- Full Automation may perform permitted pH/EC/circulation actions.
- Semi-Automation requires farmer confirmation for pH/EC dosing.
- Critical, Faulty Sensor, or Faulty Vision must be enforced by the backend as a safety override to Semi-Automation; the frontend cannot bypass this.

## Important files

- `README.md`: setup and cross-computer workflow.
- `index.html`, `styles.css`: interface shell and styling.
- `js/app.js`: UI rendering and safe mock interactions.
- `js/services/verde-api.js`: replacement point for a real backend client.

## Current TODOs

1. Validate the integrated PWA on the Pi with the already tested DHT11 and camera.
2. Integrate and calibrate the remaining water sensors without inventing values.
3. Integrate validated YOLOv8, Random Forest, and fusion models.
4. Validate the implemented private Tailscale Serve deployment on the Pi and Android; never substitute public port-forwarding or Funnel.
5. Keep physical actuation disabled until the relay, pump, interlock, watchdog,
   timing, and rearming policies are approved and hardware-validated.
