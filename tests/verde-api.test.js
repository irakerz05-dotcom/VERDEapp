import test from "node:test";
import assert from "node:assert/strict";
import {
  MockVerdeApi,
  VerdeApi,
  normalizeBackendEvents,
  normalizeBackendHistory,
  normalizeBackendSnapshot,
  normalizeLiveSensorSnapshot
} from "../js/services/verde-api.js";

test("sensor connection status controls fault display without value thresholds", () => {
  const snapshot = normalizeLiveSensorSnapshot({ sensors: {
    ph: { value: 18.5430, status: "CONNECTED" },
    ec: { value_mScm: 0.0386, status: "CONNECTED" },
    turbidity: { value_ntu: 54.6178, status: "CONNECTED" },
    water_temperature: { value: null, status: "ERROR", detail: "RuntimeError: no valid device" },
    ambient_humidity: { value: 51, status: "CONNECTED" }
  } }, { sensors: {
    turbidity: { status: "NOT CONNECTED" },
    water_temperature: { status: "NOT CONNECTED" }
  } });

  for (const label of ["pH", "Turbidity", "Water Temperature"]) {
    const sensor = snapshot.find((item) => item.label === label);
    assert.equal(sensor.status, "Faulty Sensors");
    assert.equal(sensor.value, "—");
    assert.equal(sensor.detail, "");
  }
  const ec = snapshot.find((item) => item.label === "EC");
  assert.equal(ec.status, "CONNECTED");
  assert.equal(ec.value, "0.0386");
  assert.equal(snapshot.find((item) => item.label === "Humidity").value, "51");

  const normalPh = normalizeLiveSensorSnapshot({ sensors: {
    ph: { value: 7, status: "CONNECTED" },
    ec: { value_mScm: 1.2, status: "CONNECTED" },
    turbidity: { value_ntu: 3, status: "CONNECTED" },
    water_temperature: { value_C: 22, status: "CONNECTED" },
    ambient_humidity: { value: 51, status: "CONNECTED" }
  } }).find((item) => item.label === "pH");
  assert.equal(normalPh.status, "CONNECTED");
  assert.equal(normalPh.value, "7.0000");
});

test("snapshot contains complete mock dashboard, plant, fusion, and settings data", async () => {
  const api = new MockVerdeApi({ delay: 0 });
  const snapshot = await api.getSnapshot();

  assert.equal(snapshot.mode, "Full Automation");
  assert.equal(snapshot.sensors.length, 6);
  assert.equal(snapshot.plant.condition, "Healthy");
  assert.equal(snapshot.fusion.confidence, "High");
  assert.equal(snapshot.settings.backendConnected, false);
});

test("history ranges return distinct data and calculated summaries", async () => {
  const api = new MockVerdeApi({ delay: 0 });
  const today = await api.getHistory("Today");
  const week = await api.getHistory("7 Days");

  assert.equal(today.range, "Today");
  assert.equal(week.range, "7 Days");
  assert.notDeepEqual(today.values, week.values);
  assert.equal(week.current, week.values.at(-1));
  assert.equal(week.maximum, Math.max(...week.values));
});

test("alerts are supplied by the mock API with valid timestamps", async () => {
  const api = new MockVerdeApi({ delay: 0 });
  const alerts = await api.getAlerts();

  assert.equal(alerts.length, 7);
  assert.ok(alerts.every((alert) => !Number.isNaN(Date.parse(alert.createdAt))));
  assert.ok(alerts.some((alert) => alert.tone === "good"));
  assert.ok(alerts.some((alert) => alert.tone === "warn"));
  assert.ok(alerts.some((alert) => alert.source === "vision"));
  assert.ok(alerts.some((alert) => alert.source === "fusion"));
  assert.ok(alerts.some((alert) => alert.source === "sensor"));
  assert.ok(alerts.some((alert) => alert.issueKey === "vision:pest" && alert.tone === "warn"));
});

test("accepted mode changes persist in subsequent snapshots", async () => {
  const api = new MockVerdeApi({ delay: 0 });
  const result = await api.requestModeChange("Semi-Automation");
  const snapshot = await api.getSnapshot();

  assert.equal(result.accepted, true);
  assert.equal(result.mode, "Semi-Automation");
  assert.equal(snapshot.mode, "Semi-Automation");
});

test("unsupported modes and configured mock failures reject safely", async () => {
  const api = new MockVerdeApi({ delay: 0 });
  const failingApi = new MockVerdeApi({ delay: 0, shouldFail: true });

  await assert.rejects(api.requestModeChange("Unsafe Mode"), /Unsupported/);
  await assert.rejects(failingApi.getSnapshot(), /unavailable/);
});

const backendState = {
  timestamp: "2026-09-25T04:00:00+00:00",
  version: "0.1",
  system_status: "RUNNING — DEGRADED / INTEGRATION PENDING",
  sensors: {
    ph: { status: "CONNECTED", value: 6.1, unit: null, detail: "" },
    ec: { status: "CONNECTED", value: 1.5, unit: "mS/cm", detail: "" },
    tds: { status: "CONNECTED — CALIBRATION REQUIRED", value: null, unit: "ppm", detail: "ADS1115 A2 raw voltage", raw_value: 3.35, raw_unit: "V" },
    water_temperature: { status: "NOT CONNECTED", value: null, unit: "°C", detail: "Pending" },
    turbidity: { status: "NOT CONNECTED", value: null, unit: "NTU", detail: "Pending" },
    ambient_humidity: { status: "CONNECTED", value: 77, unit: "% RH", detail: "DHT11", last_reading_timestamp: "2026-09-25T03:59:59+00:00" }
  },
  camera: { status: "CONNECTED", image_available: true, capture_version: 4, last_capture_timestamp: "2026-09-25T03:59:58+00:00" },
  water_quality: { status: "CLASSIFIER NOT LOADED", value: null, unit: null, detail: "Pending" },
  plant_condition: { status: "MODEL NOT LOADED", value: null, unit: null, detail: "Pending" },
  pest_detection: { status: "MODEL NOT LOADED", value: null, unit: null, detail: "Pending" },
  fusion: { status: "FUSION UNAVAILABLE", value: null, unit: null, detail: "Pending" },
  automation: {
    selected_mode: "Full Automation Mode",
    active_mode: "Semi-Automation Mode",
    override: true,
    override_reason: "Required water sensor unavailable/faulty, critical water condition, or system fault."
  },
  alerts: ["AI results unavailable"],
  incidents: [{
    issue_key: "vision:pest", source: "vision", severity: "warning",
    message: "Possible pest presence; farmer inspection recommended.", state: "OPEN",
    opened_at: "2026-09-25T03:58:00+00:00", acknowledged_at: null
  }]
};

test("backend status is normalized without inventing unavailable readings or AI results", () => {
  const snapshot = normalizeBackendSnapshot(backendState);
  assert.equal(snapshot.isMock, false);
  assert.equal(snapshot.mode, "Semi-Automation");
  assert.equal(snapshot.requestedMode, "Full Automation");
  assert.match(snapshot.modeOverride, /Required water sensor/);
  assert.equal(snapshot.sensors.find((sensor) => sensor.label === "TDS").value, "3.35");
  assert.equal(snapshot.sensors.find((sensor) => sensor.label === "TDS").unit, "V");
  assert.equal(snapshot.sensors.find((sensor) => sensor.label === "TDS").isRaw, true);
  assert.match(snapshot.sensors.find((sensor) => sensor.label === "TDS").detail, /raw voltage/);
  assert.equal(snapshot.sensors.find((sensor) => sensor.label === "Ambient Humidity").value, "77");
  assert.equal(snapshot.plant.pestDetected, null);
  assert.equal(snapshot.plant.frameUrl, "/api/camera/frame?v=4");
  assert.equal(snapshot.incidents[0].issueKey, "vision:pest");
  assert.equal(snapshot.incidents[0].state, "OPEN");
});

test("backend history filters ranges, orders samples, and keeps empty ranges honest", () => {
  const now = new Date("2026-09-25T12:00:00Z");
  const rows = [
    { timestamp: "2026-09-25T11:00:00Z", ph: 6.2 },
    { timestamp: "2026-09-25T10:00:00Z", ph: 5.9 },
    { timestamp: "2026-09-10T10:00:00Z", ph: 7 },
    { timestamp: "2026-09-25T09:00:00Z", ph: null }
  ];
  const history = normalizeBackendHistory(rows, "24 Hours", now);
  assert.deepEqual(history.values, [5.9, 6.2]);
  assert.equal(history.current, 6.2);
  assert.equal(history.maximum, 6.2);
  assert.equal(normalizeBackendHistory([], "7 Days", now).current, "—");
});

test("history supports every sensor and selects an available metric without inventing data", () => {
  const now = new Date("2026-09-25T12:00:00Z");
  const rows = [
    { timestamp: "2026-09-25T11:00:00Z", ph: null, water_temperature: 30.2, ambient_humidity: 82 },
    { timestamp: "2026-09-25T11:05:00Z", ph: null, water_temperature: 30.3, ambient_humidity: 83 }
  ];
  const automatic = normalizeBackendHistory(rows, "Today", now);
  const humidity = normalizeBackendHistory(rows, "Today", now, "ambient_humidity");

  assert.equal(automatic.metricKey, "water_temperature");
  assert.deepEqual(automatic.values, [30.2, 30.3]);
  assert.equal(humidity.metricKey, "ambient_humidity");
  assert.equal(humidity.current, 83);
  assert.equal(humidity.metrics.find((metric) => metric.key === "ph").sampleCount, 0);
});

test("backend events are converted to safe alert presentation data", () => {
  const alerts = normalizeBackendEvents([
    { id: 1, timestamp: "2026-09-25T12:00:00Z", category: "warning", message: "Sensor unavailable" },
    { id: 2, timestamp: "2026-09-25T11:00:00Z", category: "camera_error", message: "Capture failed" },
    { id: 3, timestamp: "2026-09-25T10:00:00Z", category: "problem_opened", message: "Plant vision detected Wilting.", payload: JSON.stringify({ state: "OPEN", source: "vision", severity: "warning", issue_key: "vision:plant_condition" }) },
    { id: 4, timestamp: "2026-09-25T10:30:00Z", category: "problem_resolved", message: "Resolved: Plant vision detected Wilting.", payload: JSON.stringify({ state: "RESOLVED", source: "vision", severity: "resolved", issue_key: "vision:plant_condition" }) },
    { id: 5, timestamp: "2026-09-25T10:15:00Z", category: "problem_acknowledged", message: "Acknowledged: Plant vision detected Wilting.", payload: JSON.stringify({ state: "ACKNOWLEDGED", source: "vision", severity: "warning", issue_key: "vision:plant_condition" }) }
  ]);
  assert.equal(alerts[0].tone, "warn");
  assert.equal(alerts[1].tone, "danger");
  assert.equal(alerts[2].state, "OPEN");
  assert.equal(alerts[2].title, "Vision problem");
  assert.equal(alerts[3].tone, "good");
  assert.equal(alerts[3].state, "RESOLVED");
  assert.equal(alerts[4].state, "ACKNOWLEDGED");
  assert.equal(alerts[4].title, "Vision acknowledged");
});

test("real adapter uses same-origin routes, session token, and backend mode names", async () => {
  const calls = [];
  const fetchImpl = async (url, options = {}) => {
    calls.push({ url, options });
    const payload = url.endsWith("/api/session") ? { token: "test-token" } : backendState;
    return { ok: true, status: 200, json: async () => payload };
  };
  const api = new VerdeApi({ fetchImpl });
  const snapshot = await api.getSnapshot();
  const result = await api.requestModeChange("Full Automation");
  const acknowledged = await api.acknowledgeIssue("vision:pest");

  assert.equal(snapshot.settings.backendConnected, true);
  assert.equal(result.activeMode, "Semi-Automation");
  assert.equal(acknowledged.system_status, backendState.system_status);
  assert.deepEqual(calls.map((call) => call.url), ["/api/status", "/api/session", "/api/mode", "/api/incidents/acknowledge"]);
  assert.equal(calls[2].options.headers["X-VERDE-Token"], "test-token");
  assert.deepEqual(JSON.parse(calls[2].options.body), { mode: "Full Automation Mode" });
  assert.deepEqual(JSON.parse(calls[3].options.body), { issue_key: "vision:pest" });
});
