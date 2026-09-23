# VERDE

Vegetation Environment Recognition and Detection Engine - an IoT-based hydroponics system with sensor-vision fusion for plant health monitoring and nutrient management.

## Current state

This repository contains a standalone, mobile-first Progressive Web App (PWA) prototype. It uses clearly labelled mock data because the Raspberry Pi/backend source has not yet been recovered. It does **not** control hardware and makes no network calls by default.

## Run locally

This project has no package installation step. Use any static file server from the repository root. For example, if Python is installed:

```powershell
python -m http.server 4173
```

Then open `http://localhost:4173` in Chrome. Opening `index.html` directly will show the interface, but service-worker installation needs an HTTP server.

## Android installation

1. Serve the app from a device reachable on the same Wi-Fi network.
2. Open its address in Chrome on Android.
3. In Chrome, select **Install app** or **Add to Home screen**.

When VERDE runs on a Raspberry Pi, the PWA should be served by that device or another local machine, and the Android phone should connect to the same local network.

## Future Raspberry Pi integration

The UI reads data through `js/services/verde-api.js`. It currently uses `MockVerdeApi`. When backend code is available, replace it with an API adapter that calls the Pi backend. Keep GPIO, pumps, relays, dosing validation, safety overrides, GSM, and machine-learning logic server-side.

Expected future API responsibilities are documented in [CODEX.md](CODEX.md). Do not connect the browser directly to GPIO or bypass backend safety decisions.

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
- Do not add credentials, Wi-Fi passwords, GSM details, `.env` files, model weights, datasets, logs, or databases to Git.
