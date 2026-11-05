# Dashboard pest section handoff: use integrated V8 output

**Audience:** VERDE app lead  
**Verified on Pi:** 2026-11-05 17:10 (Asia/Manila)  
**Scope:** frontend/backend dashboard integration only

Do not change AI weights, fixed zones, `vision_worker_integrated.py`, or
`verde-ai.service` as part of this work. Do not stop
`verde-simulated-pest.service`; that is a separate decision for Emman.

## 1. Verified problem

The Pi currently has two pest-result pipelines.

### Main integrated camera and AI artifact

The main application worker is `verde-ai.service`, which runs:

`/home/verde/VERDE-Sensor-Integration/tools/vision_worker_integrated.py`

Its verified inputs are:

| Purpose | File | SHA-256 prefix |
|---|---|---|
| Plant condition | `condition_yellowing_epoch8_best.pt` | `83f2f0e9...` |
| Harvest readiness | `harvest_cls_v3.pt` | `3990ea79...` |
| Printed insect props | `printed_prop_v8.pt` | `8ef40e09...` |
| Fixed cup zones | `zones_final.json` | `75e032c2...` |

The worker writes:

- `/home/verde/VERDE-Sensor-Integration/data/vision/latest.json`
- `/home/verde/VERDE-Sensor-Integration/data/vision/annotated-latest.jpg`

`latest.json` includes `printed_props` (list), `pest_detection` (object),
`generated_at`, `image_size`, and the other integrated vision fields. The main
camera view is correct and must remain visually and functionally unchanged.

### Dedicated dashboard pest section

The dedicated **SIMULATED PEST TEST** section currently reads:

- `/home/verde/VERDEapp/simulated-pest/latest.json`
- `/home/verde/VERDEapp/simulated-pest/latest-annotated.jpg`

Those files are written by the old user service
`verde-simulated-pest.service`, including its `10-v6-demo.conf` drop-in. That
service runs pest V6 NCNN; `model.ncnn.bin` has SHA-256 prefix
`706f4972...`.

On the same Pi camera frame, V6 reported **3** printed props while integrated
V8 reported **5**. V6 also adds approximately **35 seconds of CPU work per
frame**. Therefore the dedicated dashboard section can disagree with the main
integrated artifact even though both appear to describe the same scene.

The current frontend confirms this split:

- `js/services/verde-api.js` requests `/simulated-pest/latest.json` separately.
- `normalizeBackendSnapshot` also receives `state.pest_detection` from the
  backend, which is derived from the integrated vision artifact.
- `js/app.js` renders the dedicated simulated-pest card from the former rather
  than from integrated V8.

## 2. Requested frontend/backend change

Change only the dedicated dashboard pest section so its source of truth is the
integrated V8 artifact at:

`/home/verde/VERDE-Sensor-Integration/data/vision/latest.json`

The browser should receive the required fields through a same-origin backend
route or the existing normalized backend response. Do not expose an arbitrary
filesystem-reading endpoint.

### Count and status

- Displayed count: `printed_props.length`.
- Displayed status and message: the `pest_detection` object without replacing
  its state with a count-derived guess.
- Preserve the worker's two-consecutive-frame confirmation. A first positive
  frame is `VERIFYING`; only the next consecutive positive frame becomes
  `READY` / `Pest Detected`.
- Display `generated_at` so the operator can see whether the inference is
  current. Treat missing, invalid, future-dated, or stale timestamps as
  unavailable rather than as “No Pest Detected.”

### Exact V8 JSON contract

The following line references are from the deployed file:

`/home/verde/VERDE-Sensor-Integration/tools/vision_worker_integrated.py`

#### `printed_props`

Prop items are created at **lines 206–213**, retained after NMS at
**lines 214–220**, and placed in the result as `printed_props` at
**lines 292–299**.

```json
{
  "class_name": "Pest Detected",
  "confidence": 0.0,
  "box_xyxy": [0.0, 0.0, 0.0, 0.0]
}
```

- `class_name`: currently the literal string `Pest Detected`.
- `confidence`: floating-point score in `[0, 1]`.
- `box_xyxy`: four full-resolution image coordinates
  `[x1, y1, x2, y2]`, not width/height and not normalized values.
- `image_size` in the parent artifact is `[width, height]` and must be used to
  scale overlays to the displayed image.

#### `pest_detection`

The confirmation and summary logic is at **lines 124–149**. Its shapes are:

First positive frame:

```json
{
  "status": "VERIFYING",
  "value": null,
  "confidence": 0.0,
  "detail": "Possible printed prop in one frame; awaiting confirmation."
}
```

Second consecutive positive frame and later:

```json
{
  "status": "READY",
  "value": "Pest Detected",
  "confidence": 0.0,
  "detail": "5 possible printed insect prop(s) detected; farmer inspection recommended."
}
```

No qualifying props:

```json
{
  "status": "READY",
  "value": "No Pest Detected",
  "confidence": null,
  "detail": "No qualifying printed-prop detection in the latest frame."
}
```

The artifact gains `schema_version`, `generated_at`, `source_mtime_ns`,
`annotated_available`, and `total_inference_ms` at **lines 370–376**.

### Dedicated image

Preferred implementation:

1. Show the existing raw camera frame.
2. Draw only `printed_props[*].box_xyxy` client-side using an SVG or canvas
   overlay.
3. Scale X coordinates by `displayedWidth / image_size[0]` and Y coordinates
   by `displayedHeight / image_size[1]`.
4. Recalculate the overlay when the image loads or resizes.
5. Do not draw condition, zone, or Harvest-Ready boxes in this dedicated pest
   section.

Short-time fallback: show the existing main AI-annotated image. This fallback
contains condition/zone annotations and should be identified as the integrated
view, but it still keeps both dashboard views on V8.

Do not change the main camera capture or its annotation endpoint.

## 3. Safety, savepoint, acceptance, and rollback

### Savepoint before editing

List every file that will be edited in the appropriate array before running
these commands. Do not include files that will not be changed.

```bash
stamp="$(date +%Y%m%d-%H%M%S)"
save="$HOME/verde-dashboard-savepoints/pest-section-v8-$stamp"
mkdir -p "$save/VERDEapp" "$save/VERDE-Sensor-Integration"

app_files=(
  js/services/verde-api.js
  js/app.js
  tests/verde-api.test.js
)

# Add the exact backend route and test files selected by the app lead.
backend_files=(
)

for file in "${app_files[@]}"; do
  test -f "$HOME/VERDEapp/$file"
  mkdir -p "$save/VERDEapp/$(dirname "$file")"
  cp -p -- "$HOME/VERDEapp/$file" "$save/VERDEapp/$file"
  cmp -- "$HOME/VERDEapp/$file" "$save/VERDEapp/$file"
done

for file in "${backend_files[@]}"; do
  test -f "$HOME/VERDE-Sensor-Integration/$file"
  mkdir -p "$save/VERDE-Sensor-Integration/$(dirname "$file")"
  cp -p -- "$HOME/VERDE-Sensor-Integration/$file" \
    "$save/VERDE-Sensor-Integration/$file"
  cmp -- "$HOME/VERDE-Sensor-Integration/$file" \
    "$save/VERDE-Sensor-Integration/$file"
done

(
  cd "$save"
  find . -type f ! -name SHA256SUMS.txt -print0 | sort -z |
    xargs -0 sha256sum > SHA256SUMS.txt
  sha256sum -c SHA256SUMS.txt
)

echo "SAVEPOINT READY: $save"
```

If the app lead edits a file not listed above, stop and add it to the savepoint
before changing it.

### Restrictions during implementation

- Do not restart or edit `verde-ai.service`.
- Do not change AI models, fixed zones, or `vision_worker_integrated.py`.
- Leave `verde-simulated-pest.service` running. Emman will decide separately
  whether and when to stop it.
- Keep the main camera capture and annotated view unchanged.

### Acceptance checks

Using one artifact generation identified by the same `generated_at`:

1. The dedicated section count equals `len(printed_props)` in
   `data/vision/latest.json`.
2. Every displayed prop box corresponds to one `printed_props[*].box_xyxy`
   item after scaling to the displayed image.
3. The displayed status, value, confidence, and detail match
   `pest_detection` for that artifact.
4. The displayed inference timestamp matches `generated_at`, and stale output
   is visibly identified.
5. The main camera capture is visually unchanged.
6. Existing frontend and backend tests pass, plus focused tests for READY,
   VERIFYING, no-detection, stale, malformed, and missing artifacts.

### Rollback

Use the exact savepoint printed by the savepoint command:

```bash
save="$HOME/verde-dashboard-savepoints/pest-section-v8-YYYYMMDD-HHMMSS"

app_files=(
  js/services/verde-api.js
  js/app.js
  tests/verde-api.test.js
)

# Repeat the exact backend file list used when the savepoint was created.
backend_files=(
)

(
  cd "$save"
  sha256sum -c SHA256SUMS.txt
)

for file in "${app_files[@]}"; do
  cp -p -- "$save/VERDEapp/$file" "$HOME/VERDEapp/$file"
  cmp -- "$save/VERDEapp/$file" "$HOME/VERDEapp/$file"
done

for file in "${backend_files[@]}"; do
  cp -p -- "$save/VERDE-Sensor-Integration/$file" \
    "$HOME/VERDE-Sensor-Integration/$file"
  cmp -- "$save/VERDE-Sensor-Integration/$file" \
    "$HOME/VERDE-Sensor-Integration/$file"
done
```

After restore, reload the dashboard with a cache-busting refresh. Restart only
the frontend/backend service that the app lead intentionally changed, if its
runtime requires a restart. Never restart `verde-ai.service` for this UI
change.

## 4. Defense context

The pest model reported in **Table 6** of the thesis is printed-prop **V8**
(`8ef40e09...`). After this frontend/backend change, both the main integrated
camera view and the dedicated pest section will display results from that same
V8 artifact.
