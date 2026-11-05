# Dashboard pest section: switch the dedicated card to integrated V8

**Audience:** VERDE app lead

**Verified on Pi:** 2026-11-05

**Scope:** frontend-only dashboard change. Do not change AI models, model
files, zones, `vision_worker_integrated.py`, backend code,
`verde-ai.service`, or the Raspberry Pi AI deployment.

## 1. Problem

The dedicated pest section still reads the old pest V6 output:

- `/simulated-pest/latest.json`
- `/simulated-pest/latest-annotated.jpg`

Those files are produced by the user service
`verde-simulated-pest.service`. Its `10-v6-demo.conf` drop-in runs the V6
NCNN detector; `model.ncnn.bin` has SHA-256 prefix `706f4972...`.

On the same Pi camera frame, V6 reported **3** printed insect props while
integrated pest V8 reported **5–6**. The V8 model is
`printed_prop_v8.pt` with SHA-256 prefix `8ef40e09...`; it is the pest model
reported in Table 6 of the thesis.

The main camera capture already receives the integrated V8 result through the
backend and is correct. It must not change visually or behaviorally.

## 2. Exact code locations

All line numbers below refer to the app branch at commit
`8f526bf587078c13b5772600356bcb13310e1c3e`.

### Edit only the dedicated pest section

File: `js/services/verde-api.js`

- **Lines 406–426 — `normalizeSimulatedPest(payload, now)`**
  currently parses the V6-only contract:
  - `status === "ok"`
  - `checked_at_utc`
  - `source_frame_mtime_utc`
  - `visible_prop_count`
  - `simulated_pest_detected`
  - `/simulated-pest/latest-annotated.jpg`
- **Line 681 in `getSnapshot()`** separately requests:

  ```js
  this.request(`/simulated-pest/latest.json?v=${Date.now()}`).catch(() => null)
  ```

Replace only the dedicated pest-card data path. The existing `/api/status`
request at line 677 already supplies `state.pest_detection` and camera
metadata.

The dedicated pest card rendering in `js/app.js` may be adjusted only as
needed to consume the new normalized V8 pest-section object. Keep that edit
confined to the dedicated pest panel.

### Do not touch the main camera capture

Do not alter the camera block in `normalizeBackendSnapshot()` around
**lines 437–497**, including:

```js
`/api/camera/annotated?v=${encodeURIComponent(camera.ai_capture_version ?? "latest")}`
`/api/camera/frame?v=${encodeURIComponent(camera.capture_version ?? "latest")}`
```

Do not change any of these backend files:

- `VERDE-Sensor-Integration/app/web/__init__.py`
- `VERDE-Sensor-Integration/app/service.py`
- `VERDE-Sensor-Integration/app/ml/vision/artifact.py`
- `VERDE-Sensor-Integration/app/config.py`

### Tests that reference the old addresses

Update the frontend expectations to match removal of the separate V6 request:

- `tests/verde-api.test.js:611`
- `tests/verde-api.test.js:671`

The Pi handoff also identified `tests/simulated-pest.test.js:17`. That file is
not present in app repository commit `8f526bf`. If it exists in the app lead's
Pi or working tree, savepoint it and update its old-address expectation. Do
not create it solely to satisfy this handoff.

## 3. Requested frontend-only behavior

Use `state.pest_detection` from the existing `/api/status` response for the
dedicated pest section.

Map the fields as follows:

| Dedicated section field | Existing backend value |
|---|---|
| Result | `state.pest_detection.value` |
| Detail/count text | `state.pest_detection.detail` |
| Confidence | `state.pest_detection.confidence` |
| Freshness/version | `state.camera.ai_capture_version`, falling back to `state.camera.last_capture_timestamp` |
| Image | `/api/camera/annotated?v=<camera.ai_capture_version>` |

Expected result values are `Pest Detected` and `No Pest Detected`. The detail
already contains the V8 printed-prop count; do not calculate or invent a
different count in the frontend.

When `state.pest_detection.status !== "READY"`, preserve an unavailable
fallback. Do not present a non-READY, missing, malformed, or stale result as
`No Pest Detected`.

Use the existing V8 image URL:

```text
/api/camera/annotated?v=<camera.ai_capture_version>
```

This image is intentionally the same integrated annotated frame already used
by the main camera view. Do not change how the main view obtains or displays
that frame.

After the dedicated section is verified using `/api/status`, remove the
separate `/simulated-pest/latest.json` request from `getSnapshot()` and update
the associated normalization call and tests.

## 4. Safety, acceptance, and rollback

### Savepoint every edited file before editing

Set `files` to the exact frontend files the app lead will edit. If an
additional file becomes necessary, stop and add it to the savepoint before
editing it.

```bash
stamp="$(date +%Y%m%d-%H%M%S)"
save="$HOME/VERDEapp/deploy/savepoints/$stamp-pest-section-v8"

files=(
  js/services/verde-api.js
  js/app.js
  tests/verde-api.test.js
)

# Add this only if it exists and will be edited:
# files+=(tests/simulated-pest.test.js)

mkdir -p "$save"

for file in "${files[@]}"; do
  test -f "$HOME/VERDEapp/$file"
  mkdir -p "$save/$(dirname "$file")"
  cp -p -- "$HOME/VERDEapp/$file" "$save/$file"
  cmp -- "$HOME/VERDEapp/$file" "$save/$file"
done

(
  cd "$save"
  find . -type f ! -name SHA256SUMS.txt -print0 | sort -z |
    xargs -0 sha256sum > SHA256SUMS.txt
  sha256sum -c SHA256SUMS.txt
)

echo "SAVEPOINT READY: $save"
```

### Implementation restrictions

- Frontend change only; do not edit the backend.
- Do not modify or restart `verde-ai.service`.
- Leave `verde-simulated-pest.service` running. Stopping it is Emman's
  separate decision.
- Do not change any AI model, model file, zone configuration, or worker.
- Do not modify the main camera capture block.

### Tests

Run the existing frontend tests after updating their old V6 request
expectations:

```bash
cd "$HOME/VERDEapp"
node --test
```

Add or update focused frontend coverage for:

- V8 `Pest Detected` with confidence and detail.
- V8 `No Pest Detected`.
- Non-READY `pest_detection` producing the unavailable fallback.
- Missing/malformed pest data producing the unavailable fallback.
- The removed `/simulated-pest/latest.json` request.
- The unchanged main-camera image URL and behavior.

### Acceptance checks

1. At the same observation time, the pest section text, detail/count, and
   confidence match `/api/status` → `pest_detection`.
2. The dedicated section uses
   `/api/camera/annotated?v=<camera.ai_capture_version>`.
3. The main camera capture shows the same image, labels, URL selection, and
   behavior before and after the change.
4. Non-READY pest results display the unavailable fallback.
5. The frontend no longer requests `/simulated-pest/latest.json`.
6. All frontend tests pass.

### Rollback

Restore the exact timestamped savepoint made before editing:

```bash
save="$HOME/VERDEapp/deploy/savepoints/YYYYMMDD-HHMMSS-pest-section-v8"

files=(
  js/services/verde-api.js
  js/app.js
  tests/verde-api.test.js
)

# Include this only if it was in the original savepoint:
# files+=(tests/simulated-pest.test.js)

(
  cd "$save"
  sha256sum -c SHA256SUMS.txt
)

for file in "${files[@]}"; do
  cp -p -- "$save/$file" "$HOME/VERDEapp/$file"
  cmp -- "$save/$file" "$HOME/VERDEapp/$file"
done
```

Reload the dashboard with a cache-busting refresh after implementation or
rollback. No service restart is required for this static frontend change.

## Defense context

The pest model in thesis Table 6 is V8 (`8ef40e09...`). After this frontend
change, both the main camera view and dedicated pest section will display the
same integrated V8 result.
