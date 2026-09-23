# VERDE project context

## Purpose

VERDE (Vegetation Environment Recognition and Detection Engine) is a thesis prototype for hydroponic Butterhead and Looseleaf lettuce. It combines IoT water-quality sensing, YOLOv8 plant/pest detection, Random Forest classification, sensor-vision fusion, dashboard alerts, and dual-mode nutrient management.

## Current repository state

This is a new static PWA implementation. The original backend, Raspberry Pi integration, database, model code, and previous dashboard files have not been recovered, so no backend behavior has been replaced. All displayed readings are explicitly mock development data.

## Frontend

- Dependency-free static HTML/CSS/JavaScript PWA.
- Entry point: `index.html`.
- UI code: `js/app.js`.
- Mock data/API boundary: `js/services/verde-api.js`.
- Offline installation: `manifest.webmanifest` and `service-worker.js`.
- The UI is mobile-first and works in Android Chrome.

## Intended future backend contract

The PWA must call a local-network backend on the Raspberry Pi, never GPIO directly. Expected API capabilities: system status, current sensor snapshot, plant/detection output, fusion output, alert history, historical readings, mode-change request, and confirmation/decline of a recommended dosing action. Confirm exact routes and payloads against the recovered backend before implementation.

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

1. Recover or build the Raspberry Pi backend and database.
2. Define and implement the actual API contract.
3. Replace mock adapter with a real API client, including offline/timeout/error handling.
4. Add backend-enforced authentication/authorization appropriate to local deployment.
5. Test UI against live sensor, YOLOv8, Random Forest, fusion, alert, and actuator data.
6. Validate installation and local-network access on Android.
