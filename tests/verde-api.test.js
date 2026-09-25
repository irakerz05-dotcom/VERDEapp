import test from "node:test";
import assert from "node:assert/strict";
import {
  MockVerdeApi,
  VerdeApi,
  normalizeBackendEvents,
  normalizeBackendHistory,
  normalizeBackendSnapshot
} from "../js/services/verde-api.js";

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

  assert.equal(alerts.length, 3);
  assert.ok(alerts.every((alert) => !Number.isNaN(Date.parse(alert.createdAt))));
  assert.ok(alerts.some((alert) => alert.tone === "good"));
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
  alerts: ["AI results unavailable"]
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

test("backend events are converted to safe alert presentation data", () => {
  const alerts = normalizeBackendEvents([
    { id: 1, timestamp: "2026-09-25T12:00:00Z", category: "warning", message: "Sensor unavailable" },
    { id: 2, timestamp: "2026-09-25T11:00:00Z", category: "camera_error", message: "Capture failed" }
  ]);
  assert.equal(alerts[0].tone, "warn");
  assert.equal(alerts[1].tone, "danger");
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

  assert.equal(snapshot.settings.backendConnected, true);
  assert.equal(result.activeMode, "Semi-Automation");
  assert.deepEqual(calls.map((call) => call.url), ["/api/status", "/api/session", "/api/mode"]);
  assert.equal(calls[2].options.headers["X-VERDE-Token"], "test-token");
  assert.deepEqual(JSON.parse(calls[2].options.body), { mode: "Full Automation Mode" });
});
