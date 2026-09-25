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

Android live-backend installation is intentionally pending. The validated
backend currently binds to `127.0.0.1` and rejects non-local Host values, so it
is available only in a browser running on the Pi (or through a developer SSH
tunnel). Do not weaken those checks merely to expose the dashboard over Wi-Fi.
A future phone deployment needs an approved authenticated HTTPS/network design
before Android PWA installation is enabled.

## Raspberry Pi integration

`js/services/verde-api.js` contains both the live `VerdeApi` adapter and the
development-only `MockVerdeApi`. The live adapter uses `/api/status`,
`/api/history`, `/api/events`, `/api/session`, `/api/mode`, and camera-frame
URLs supplied by the backend. It preserves missing sensor/model values as
unavailable instead of fabricating results.

Do not connect the browser directly to GPIO or bypass backend safety decisions.

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
