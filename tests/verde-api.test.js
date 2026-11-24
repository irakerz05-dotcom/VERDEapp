import test from "node:test";
import assert from "node:assert/strict";
import {
  MockVerdeApi,
  VerdeApi,
  calibrateHumidity,
  markSnapshotStale,
  normalizeBackendEvents,
  normalizeBackendHistory,
  normalizeBackendSnapshot,
  normalizeIntegratedPest,
  normalizeLiveSensorSnapshot,
  normalizeFusionBySlot,
  normalizePlantSlots
} from "../js/services/verde-api.js";

test("humidity calibration applies once to live, history, and mock displays", async () => {
  assert.equal(calibrateHumidity(42), 48);
  assert.equal(calibrateHumidity(59), 65);
  assert.equal(calibrateHumidity(97), 100);
  assert.equal(calibrateHumidity(null), null);
  const raw = { value: 59, status: "CONNECTED: DHT11" };
  const card = normalizeLiveSensorSnapshot({ sensors: { ambient_humidity: raw } })
    .find((item) => item.label === "Humidity");
  assert.equal(card.value, "65");
  assert.equal(card.status, "OPTIMAL");
  assert.equal(raw.value, 59);
  const mock = new MockVerdeApi({ delay: 0 });
  assert.equal((await mock.getSnapshot()).sensors.find((item) => item.label === "Humidity").value, "68");
  assert.equal((await mock.getHistory("Today", "ambient_humidity")).current, 68);
});

test("per-plant fusion keeps fixed slots and invalidates old results when disconnected", () => {
  const rows = Array.from({ length: 6 }, (_, index) => ({
    slot: index + 1,
    sensor_status: "Optimal",
    plant_condition: index === 0 ? "Healthy" : index === 5 ? "Yellowing" : null,
    confidence: index === 0 ? "High" : index === 5 ? "Medium" : null,
    status: index === 0 || index === 5 ? "READY" : "NO DETECTION",
    reason: "Descriptive confidence only."
  }));
  const normalized = normalizeFusionBySlot([...rows].reverse());
  assert.equal(normalized[0].slot, 1);
  assert.equal(normalized[0].confidence, "High");
  assert.equal(normalized[5].slot, 6);
  assert.equal(normalized[5].confidence, "Medium");
  assert.equal(normalized.length, 6);
  assert.equal(normalizeFusionBySlot([...rows.slice(0, 5), rows[0]]), null);
  assert.equal(normalizeFusionBySlot(Array.from({ length: 10 }, (_, index) => ({ slot: index + 1 }))), null);
  const stale = markSnapshotStale({ online: true, sensors: [], fusionBySlot: normalized }, "Offline");
  assert.equal(stale.fusionBySlot[0].confidence, null);
  assert.equal(stale.fusionBySlot[0].status, "Stale");
});

test("experimental water result is clearly labeled while legacy status stays separate", () => {
  const base = { sensors: {}, automation: { selected_mode: "Semi-Automation Mode",
    active_mode: "Semi-Automation Mode", override: true },
    water_quality: { status: "CLASSIFIER NOT LOADED", value: null },
    water_quality_experimental: { status: "EXPERIMENTAL", value: "Suboptimal",
      detail: "Prototype trained on paper-rule examples." },
    fusion: { status: "READY", value: "Medium", detail: "Prototype descriptive fusion." } };
  const display = normalizeBackendSnapshot(base);
  assert.equal(display.waterQuality.status, "Prototype: Suboptimal");
  assert.equal(display.waterQuality.summary, "Random Forest Model");
  const recovering = normalizeBackendSnapshot({ ...base,
    water_quality_experimental: { status: "EXPERIMENTAL_RECOVERING", value: "Suboptimal",
      detail: "Provisional: last valid water temperature; not a live measurement." }
  });
  assert.equal(recovering.waterQuality.status, "Prototype (recovering): Suboptimal");
  assert.equal(recovering.waterQuality.summary, "Random Forest Model");
  assert.equal(display.fusion.confidence, "Medium");
  const unavailable = normalizeBackendSnapshot({ ...base,
    water_quality_experimental: { status: "SENSOR INPUT UNAVAILABLE", value: null,
      detail: "Four fresh water sensor readings are required." } });
  assert.equal(unavailable.waterQuality.status, "SENSOR INPUT UNAVAILABLE");
});

test("real-reading pilot is a separate descriptive result", () => {
  const base = { sensors: {}, automation: { selected_mode: "Semi-Automation Mode",
    active_mode: "Semi-Automation Mode", override: true },
    water_quality: { status: "CLASSIFIER NOT LOADED", value: null },
    water_quality_experimental: { status: "EXPERIMENTAL", value: "Suboptimal",
      detail: "Synthetic prototype." },
    water_quality_real_pilot: { status: "EXPERIMENTAL", value: "Optimal",
      detail: "Paper thresholds: Suboptimal. Pilot and thresholds disagree." } };
  const display = normalizeBackendSnapshot(base);
  assert.equal(display.waterQuality.status, "Prototype: Suboptimal");
  assert.equal(display.waterQualityPilot.status, "Pilot: Optimal");
  assert.match(display.waterQualityPilot.summary, /disagree/);
  assert.equal(normalizeBackendSnapshot({ ...base, water_quality_real_pilot: undefined }).waterQualityPilot, null);
});

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
  assert.equal(snapshot.find((item) => item.label === "Humidity").value, "57");

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

test("a valid live value without a status remains visible; explicit faults still hide readings", () => {
  const readings = normalizeLiveSensorSnapshot({ sensors: {
    ph: { value: 6.2 },
    ec: { value_mScm: 1.45 },
    turbidity: { value_ntu: 3.1 },
    water_temperature: { value_C: 23 },
    ambient_humidity: { value: 65 }
  } });
  assert.equal(readings.find((item) => item.label === "EC").value, "1.4500");
  assert.equal(readings.find((item) => item.label === "Humidity").status, "OPTIMAL");

  const withFault = normalizeLiveSensorSnapshot({ sensors: {
    ec: { value_mScm: 1.45, status: "CONNECTED" }
  } }, { sensors: { ec: { status: "DISCONNECTED" } } });
  assert.equal(withFault.find((item) => item.label === "EC").value, "—");
  assert.equal(withFault.find((item) => item.label === "EC").status, "Faulty Sensors");
});

test("unrelated ADS1115 A0 voltage is never shown as turbidity", () => {
  const health = { sensors: { turbidity: "UNAVAILABLE: accepted turbidity calibration record is missing or invalid" } };
  const sensor = {
    value_ntu: null,
    status: health.sensors.turbidity,
    calibration_error: "turbidity calibration is not for ADS1115 A0",
    raw_voltage_V: 0.072125,
    filtered_voltage_V: 0.072
  };
  const reading = normalizeLiveSensorSnapshot({ sensors: { turbidity: sensor } }, health)
    .find((item) => item.label === "Turbidity");
  assert.equal(reading.value, "—");
  assert.equal(reading.unit, "NTU");
  assert.equal(reading.status, "Faulty Sensors");
  assert.equal(reading.isRaw, false);

  const disconnected = normalizeLiveSensorSnapshot({ sensors: { turbidity: sensor } },
    { sensors: { turbidity: "NOT CONNECTED" } })
    .find((item) => item.label === "Turbidity");
  assert.equal(disconnected.status, "Faulty Sensors");
  assert.equal(disconnected.value, "—");
});

test("GPIO5 turbidity reports only a fresh digital level, never NTU", () => {
  for (const [level, expected] of [[0, "LOW"], [1, "HIGH"]]) {
    const reading = normalizeLiveSensorSnapshot({
      timestamp: "2026-10-26T20:00:00+08:00",
      sensors: { turbidity: { measurement_type: "DIGITAL_THRESHOLD_ONLY",
        status: "DIGITAL_THRESHOLD", digital_level: level, value_ntu: null } }
    }).find((item) => item.label === "Turbidity");
    assert.equal(reading.value, expected);
    assert.equal(reading.unit, "");
    assert.equal(reading.status, "DIGITAL ONLY");
    assert.equal(reading.isRaw, true);
  }
  const missing = normalizeLiveSensorSnapshot({ sensors: { turbidity: {
    measurement_type: "DIGITAL_THRESHOLD_ONLY", status: "ERROR", digital_level: null
  } } }).find((item) => item.label === "Turbidity");
  assert.equal(missing.value, "—");
  assert.equal(missing.status, "Faulty Sensors");
});

test("a project-reference NTU reading remains numeric with metadata retained", () => {
  const sensor = { value_ntu: 0.3, reference_ntu: 0.3, status: "CALIBRATED", classification: "OPTIMAL",
    reference_voltage_V: 0.5762, raw_voltage_V: 0.5761, filtered_voltage_V: 0.5762 };
  const reading = normalizeLiveSensorSnapshot({ sensors: { turbidity: sensor } })
    .find((item) => item.label === "Turbidity");
  assert.equal(reading.value, "0.3000");
  assert.equal(reading.unit, "NTU");
  assert.match(reading.detail, /Project NTU estimate/);
  assert.match(reading.detail, /user-assigned 0\.3 reference/);
  assert.match(reading.detail, /0\.5762 V/);
});

test("live humidity is OPTIMAL only from 65% through 78% inclusive", () => {
  for (const [value, expected] of [
    [58.9, "SUBOPTIMAL"], [59, "OPTIMAL"], [66, "OPTIMAL"],
    [72, "OPTIMAL"], [72.1, "SUBOPTIMAL"]
  ]) {
    const humidity = normalizeLiveSensorSnapshot({ sensors: {
      ambient_humidity: { value, status: "CONNECTED: DHT11" }
    } }).find((item) => item.label === "Humidity");
    assert.equal(humidity.value, String(calibrateHumidity(value)));
    assert.equal(humidity.status, expected);
  }

  const faulty = normalizeLiveSensorSnapshot({ sensors: {
    ambient_humidity: { value: null, status: "ERROR: incomplete buffer" }
  } }).find((item) => item.label === "Humidity");
  assert.equal(faulty.status, "Faulty Sensors");
  assert.equal(faulty.value, "—");

  const recovering = normalizeLiveSensorSnapshot({ sensors: {
    ambient_humidity: { value: 72, status: "RECOVERING: retrying DHT11" }
  } }).find((item) => item.label === "Humidity");
  assert.equal(recovering.status, "Recovering");
  assert.equal(recovering.value, "—");
});

test("water temperature and humidity fail and recover independently", () => {
  const liveWater = { value_C: 25.125, status: "OK: DS18B20" };
  const liveHumidity = { value: 72, status: "CONNECTED: DHT11" };
  const failedWater = { value_C: null, status: "ERROR: CRC failure", read_error: "CRC failure" };
  const failedHumidity = { value: null, status: "ERROR: incomplete buffer", read_error: "incomplete buffer" };
  const cases = [
    [failedWater, failedHumidity, "Faulty Sensors", "Faulty Sensors"],
    [failedWater, liveHumidity, "Faulty Sensors", "OPTIMAL"],
    [liveWater, failedHumidity, "CONNECTED", "Faulty Sensors"],
    [liveWater, liveHumidity, "CONNECTED", "OPTIMAL"],
    [liveWater, failedHumidity, "CONNECTED", "Faulty Sensors"]
  ];
  for (const [water, humidity, expectedWater, expectedHumidity] of cases) {
    const readings = normalizeLiveSensorSnapshot({
      system: { sample: 42 },
      sensors: { water_temperature: water, ambient_humidity: humidity }
    });
    const temperatureCard = readings.find((item) => item.label === "Water Temperature");
    const humidityCard = readings.find((item) => item.label === "Humidity");
    assert.equal(temperatureCard.status, expectedWater);
    assert.equal(humidityCard.status, expectedHumidity);
    assert.equal(temperatureCard.value, expectedWater === "CONNECTED" ? "25.13" : "—");
    assert.equal(humidityCard.value, expectedHumidity === "OPTIMAL" ? "78" : "—");
  }
});

test("corrected water temperature is shown with two decimals without changing its classification", () => {
  const readings = normalizeLiveSensorSnapshot({ sensors: {
    water_temperature: { value_C: 25.237000000000002, raw_value_C: 25.937,
      classification: "SUBOPTIMAL", status: "OK: software offset -0.7 C" }
  } });
  const water = readings.find((item) => item.label === "Water Temperature");
  assert.equal(water.value, "25.24");
  assert.equal(water.status, "SUBOPTIMAL");
});

test("transient retries and different sample generations never expose old values as live", () => {
  const recovering = normalizeLiveSensorSnapshot({ sensors: {
    water_temperature: { value_C: null, status: "RECOVERING: CRC failure", read_error: "CRC failure" },
    ambient_humidity: { value: 70, status: "CONNECTED" }
  } });
  assert.equal(recovering.find((item) => item.label === "Water Temperature").status, "Recovering");
  assert.equal(recovering.find((item) => item.label === "Water Temperature").value, "—");
  assert.equal(recovering.find((item) => item.label === "Humidity").value, "76");

  const latest = { system: { sample: 43 }, sensors: {
    water_temperature: { value_C: 25, status: "OK" },
    ambient_humidity: { value: 72, status: "CONNECTED" }
  } };
  const olderHealth = { sample: 42, sensors: {
    water_temperature: "ERROR: CRC failure", ambient_humidity: "ERROR: incomplete buffer"
  } };
  const current = normalizeLiveSensorSnapshot(latest, olderHealth);
  assert.equal(current.find((item) => item.label === "Water Temperature").value, "25.00");
  assert.equal(current.find((item) => item.label === "Humidity").value, "78");

  const newerHealth = { sample: 44, sensors: { water_temperature: "ERROR: CRC failure", ambient_humidity: "CONNECTED" } };
  const incoherent = normalizeLiveSensorSnapshot(latest, newerHealth);
  assert.equal(incoherent.find((item) => item.label === "Water Temperature").status, "Faulty Sensors");
  assert.equal(incoherent.find((item) => item.label === "Water Temperature").value, "—");
  assert.equal(incoherent.find((item) => item.label === "Humidity").status, "Stale");
  assert.equal(incoherent.find((item) => item.label === "Humidity").value, "—");
});

test("recovering water temperature shows a recent last reading as non-live", () => {
  const recent = new Date(Date.now() - 30_000).toISOString();
  const expired = new Date(Date.now() - 120_000).toISOString();
  const sensors = {
    water_temperature: { value_C: null, status: "RECOVERING: CRC failure",
      read_error: "CRC failure", last_valid_value_C: 24.625,
      last_valid_measured_at: recent },
    ambient_humidity: { value: null, status: "RECOVERING: incomplete buffer",
      read_error: "incomplete buffer", last_valid_value: 70,
      last_valid_measured_at: recent }
  };
  const readings = normalizeLiveSensorSnapshot({ sensors });
  const water = readings.find((item) => item.label === "Water Temperature");
  const humidity = readings.find((item) => item.label === "Humidity");
  assert.equal(water.value, "24.63");
  assert.equal(humidity.value, "—");
  assert.equal(water.status, "Recovering");
  assert.equal(humidity.status, "Recovering");
  assert.match(water.detail, /not live/);
  assert.equal(water.lastReadingAt, recent);
  sensors.water_temperature.last_valid_measured_at = expired;
  sensors.ambient_humidity.status = "ERROR: disconnected";
  const degraded = normalizeLiveSensorSnapshot({ sensors });
  assert.equal(degraded.find((item) => item.label === "Water Temperature").value, "—");
  assert.equal(degraded.find((item) => item.label === "Humidity").status, "Faulty Sensors");
  assert.equal(degraded.find((item) => item.label === "Humidity").value, "—");
  sensors.water_temperature.last_valid_measured_at = recent;
  sensors.water_temperature.stale = true;
  assert.equal(normalizeLiveSensorSnapshot({ sensors })
    .find((item) => item.label === "Water Temperature").value, "—");
});

test("a stale dashboard hides old numbers and records their previous state", () => {
  const stale = markSnapshotStale({ online: true, sensors: [
    { label: "Water Temperature", value: "25.125", unit: "°C", status: "CONNECTED" },
    { label: "Humidity", value: "—", unit: "%", status: "Faulty Sensors" }
  ] }, "Backend timed out");
  assert.equal(stale.online, false);
  assert.equal(stale.stale, true);
  assert.deepEqual(stale.sensors.map((sensor) => sensor.status), ["Stale", "Stale"]);
  assert.deepEqual(stale.sensors.map((sensor) => sensor.value), ["—", "—"]);
  assert.match(stale.sensors[1].detail, /Faulty Sensors/);
});

test("snapshot contains complete mock dashboard, plant, fusion, and settings data", async () => {
  const api = new MockVerdeApi({ delay: 0 });
  const snapshot = await api.getSnapshot();

  assert.equal(snapshot.mode, "Full Automation");
  assert.equal(snapshot.sensors.length, 5);
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
  const snapshot = normalizeBackendSnapshot(backendState, { sensors: backendState.sensors });
  assert.equal(snapshot.isMock, false);
  assert.equal(snapshot.mode, "Semi-Automation");
  assert.equal(snapshot.requestedMode, "Full Automation");
  assert.match(snapshot.modeOverride, /Required water sensor/);
  assert.equal(snapshot.sensors.find((sensor) => sensor.label === "Water Temperature").value, "—");
  assert.equal(snapshot.sensors.find((sensor) => sensor.label === "Water Temperature").status, "Faulty Sensors");
  assert.equal(snapshot.sensors.find((sensor) => sensor.label === "Humidity").value, "83");
  assert.equal(snapshot.plant.pestDetected, null);
  assert.equal(snapshot.plant.frameUrl, "/api/camera/frame?v=4");
  assert.equal(snapshot.incidents[0].issueKey, "vision:pest");
  assert.equal(snapshot.incidents[0].state, "OPEN");
});

test("manual dosing arm is exposed separately from a Critical circulation stop", () => {
  const state = { ...backendState, automation: {
    ...backendState.automation,
    hardware_status: "MANUAL DOSING ARMED — CIRCULATION STOPPED",
    auto_resume_available: true,
    critical_manual_dose: true,
    manual_wait_reason: "Wait for a new sensor reading after the previous dose",
    circulation_stop_required: true,
    confirmation_available: true,
    recommendations: ["pH-Down dosing", "EC nutrient dosing"]
  } };
  const snapshot = normalizeBackendSnapshot(state, { sensors: state.sensors });
  assert.equal(snapshot.pumpAutomation.manualDosingArmed, true);
  assert.equal(snapshot.pumpAutomation.autoResumeAvailable, true);
  assert.equal(snapshot.pumpAutomation.criticalManualDose, true);
  assert.match(snapshot.pumpAutomation.manualWaitReason, /new sensor reading/);
  assert.equal(snapshot.pumpAutomation.circulationStopRequired, true);
  assert.equal(snapshot.pumpAutomation.confirmationAvailable, true);
});

test("fresh AI artifacts select the annotated frame and expose real confidence", () => {
  const state = {
    ...backendState,
    camera: {
      ...backendState.camera,
      ai_status: "READY",
      ai_image_available: true,
      ai_capture_version: "2026-10-23T02:00:00+00:00",
      ai_detail: "Experimental two-stage YOLO analysis"
    },
    plant_condition: {
      status: "READY", value: "Healthy", confidence: 0.7578,
      detail: "Experimental per-lettuce analysis: 5 plant(s); 5 classified Healthy.",
      classifications: {
        Healthy: { count: 5, confidence: 0.7578 },
        Yellowing: { count: 0, confidence: null },
        Wilting: { count: 0, confidence: null },
        "Harvest-Ready": { count: 0, confidence: null }
      }
    },
    pest_detection: {
      status: "READY", value: "No Pest Detected", confidence: null,
      detail: "No qualifying pest detection in the latest frame; this does not confirm pest-free plants."
    }
  };
  const snapshot = normalizeBackendSnapshot(state, { sensors: state.sensors });
  assert.equal(snapshot.plant.condition, "Healthy");
  assert.equal(snapshot.plant.confidence, "76%");
  assert.equal(snapshot.plant.pestDetected, false);
  assert.equal(snapshot.plant.pestStatus, "No Pest Detected");
  assert.match(snapshot.plant.pestDetail, /does not confirm/);
  assert.deepEqual(snapshot.plant.classifications, [
    { label: "Healthy", count: 5, confidence: "76%" },
    { label: "Yellowing", count: 0, confidence: null },
    { label: "Wilting", count: 0, confidence: null },
    { label: "Harvest-Ready", count: 0, confidence: null }
  ]);
  assert.equal(snapshot.plant.aiAnnotated, true);
  assert.match(snapshot.plant.frameUrl, /^\/api\/camera\/annotated\?v=/);
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

test("history averages retain precision until the UI formats them", () => {
  const now = new Date("2026-09-25T12:00:00Z");
  const rows = [
    { timestamp: "2026-09-25T10:00:00Z", turbidity: 1.23456 },
    { timestamp: "2026-09-25T11:00:00Z", turbidity: 1.23458 }
  ];
  const history = normalizeBackendHistory(rows, "24 Hours", now, "turbidity");
  assert.ok(Math.abs(history.average - 1.23457) < 1e-12);
  assert.deepEqual(history.values, [1.23456, 1.23458]);
});

test("live history requests the selected time range from the Pi", async () => {
  const calls = [];
  const fetchImpl = async (url) => {
    calls.push(url);
    return { ok: true, status: 200, json: async () => ({ rows: [] }) };
  };
  await new VerdeApi({ fetchImpl }).getHistory("7 Days");
  assert.deepEqual(calls.slice(0, 2), ["/api/history?range=7%20Days", "/api/events"]);
  assert.match(calls[2], /^\/api\/pump\/history\?since=/);
  assert.equal(calls.length, 3);
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
  assert.deepEqual(humidity.values, [88, 89]);
  assert.equal(humidity.current, 89);
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

test("pump actuator events appear in history with their selected pump", () => {
  const now = new Date("2026-09-25T12:00:00Z");
  const history = normalizeBackendHistory([], "24 Hours", now, null, [{
    id: 20, timestamp: "2026-09-25T11:30:00Z", category: "actuator",
    message: "Automatic dose completed",
    payload: { mode: "Full Automation Mode", pump: "pump2", action: "ph_up",
      requested_seconds: 2, estimated_ml: 1.64 }
  }]);
  assert.equal(history.pumpDoses.length, 1);
  assert.equal(history.pumpDoses[0].pump, "pump2");
  assert.equal(history.pumpDoses[0].estimatedMl, 1.64);
});

test("dedicated pump history includes farmer-confirmed doses beyond recent general events", () => {
  const now = new Date("2026-09-25T12:00:00Z");
  const generalEvents = [{ id: 99, timestamp: "2026-09-25T11:59:00Z",
    category: "camera", message: "Captured" }];
  const pumpEvents = [{ id: 20, timestamp: "2026-09-25T10:30:00Z",
    category: "actuator", message: "DOSED", payload: JSON.stringify({
      status: "DOSED", value: { mode: "Semi-Automation Mode", pump: "pump1",
        action: "nutrient_dosing", requested_seconds: 1.5, estimated_ml: 1.23 }
    }) }];
  const history = normalizeBackendHistory([], "Today", now, null, generalEvents, pumpEvents);
  assert.equal(history.pumpDoses.length, 1);
  assert.equal(history.pumpDoses[0].pump, "pump1");
  assert.equal(history.pumpDoses[0].mode, "Semi-Automation Mode");
  assert.equal(history.pumpDoses[0].requestedSeconds, 1.5);
  assert.equal(history.pumpDoses[0].estimatedMl, 1.23);
});

test("Today sensor view still shows last week's recorded pump doses", () => {
  const now = new Date("2026-11-03T07:00:00Z");
  const olderDose = { id: 20, timestamp: "2026-10-29T08:11:57Z", category: "actuator",
    message: "DOSED", payload: JSON.stringify({ status: "DOSED",
      value: { pump: "pump3", seconds: 4.5, estimated_ml: 3.69 },
      detail: "Farmer confirmed ph_down" }) };
  const history = normalizeBackendHistory([], "Today", now, null, [], [olderDose]);
  assert.equal(history.sampleCount, 0);
  assert.equal(history.pumpDoses.length, 1);
  assert.equal(history.pumpDoses[0].action, "ph_down");
  assert.equal(history.pumpDoses[0].mode, "Semi-Automation Mode");
  assert.equal(history.pumpDoses[0].requestedSeconds, 4.5);
});

test("harvest detection is a notification, never a vision warning", () => {
  const [notice] = normalizeBackendEvents([{
    id: 12, timestamp: "2026-10-28T07:12:00+08:00",
    category: "notification_opened",
    message: "Plant 4 is now Harvest-Ready. Check its planting date and harvest schedule.",
    payload: { issue_key: "vision:slot:4:harvest_ready", source: "vision",
      severity: "notice", state: "NOTICE" }
  }]);
  assert.equal(notice.title, "Harvest notification");
  assert.equal(notice.state, "NOTICE");
  assert.equal(notice.tone, "info");
  assert.match(notice.message, /Plant 4 is now Harvest-Ready/);
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
  assert.deepEqual(calls.map((call) => call.url), ["/api/status", "/api/sensors/latest", "/api/sensors/health", "/api/camera/pest-overlay", "/api/session", "/api/mode", "/api/incidents/acknowledge"]);
  assert.equal(calls[5].options.headers["X-VERDE-Token"], "test-token");
  assert.deepEqual(JSON.parse(calls[5].options.body), { mode: "Full Automation Mode" });
  assert.deepEqual(JSON.parse(calls[6].options.body), { issue_key: "vision:pest" });
});

test("farmer dose confirmation uses the protected backend route and reports a blocked result", async () => {
  const calls = [];
  const fetchImpl = async (url, options = {}) => {
    calls.push({ url, options });
    if (url.endsWith("/api/session")) return { ok: true, status: 200, json: async () => ({ token: "test-token" }) };
    return { ok: false, status: 409, json: async () => ({ status: "BLOCKED — PUMP GATEWAY DISARMED OR BUSY" }) };
  };
  const api = new VerdeApi({ fetchImpl });
  await assert.rejects(api.confirmDose(), /DISARMED/);
  assert.equal(calls[1].url, "/api/confirm");
  assert.equal(calls[1].options.headers["X-VERDE-Token"], "test-token");
  assert.deepEqual(JSON.parse(calls[1].options.body), {});
});

test("farmer dose confirmation can select one pump", async () => {
  const calls = [];
  const fetchImpl = async (url, options = {}) => {
    calls.push({ url, options });
    if (url.endsWith("/api/session")) return { ok: true, status: 200, json: async () => ({ token: "test-token" }) };
    return { ok: true, status: 200, json: async () => ({ status: "DOSED" }) };
  };
  const api = new VerdeApi({ fetchImpl });
  await api.confirmDose("pump3");
  assert.deepEqual(JSON.parse(calls[1].options.body), { pump: "pump3" });
});

test("pump dose settings use the authenticated route and preserve per-pump volumes", async () => {
  const calls = [];
  const fetchImpl = async (url, options = {}) => {
    calls.push({ url, options });
    return { ok: true, status: 200, json: async () => url.endsWith("/api/session")
      ? { token: "test-token" } : { volumes_ml: { pump1: 1, pump2: 2, pump3: 3 } } };
  };
  const api = new VerdeApi({ fetchImpl });
  const result = await api.updatePumpDoseSettings({ pump1: 1, pump2: 2, pump3: 3 });
  assert.deepEqual(result.volumes_ml, { pump1: 1, pump2: 2, pump3: 3 });
  assert.equal(calls[1].url, "/api/pump/dose-settings");
  assert.equal(calls[1].options.headers["X-VERDE-Token"], "test-token");
  assert.deepEqual(JSON.parse(calls[1].options.body), { volumes_ml: { pump1: 1, pump2: 2, pump3: 3 } });
});

test("real adapter keeps status and camera data when optional sensor routes are unavailable", async () => {
  const calls = [];
  const fetchImpl = async (url) => {
    calls.push(url);
    if (url.endsWith("/api/status")) return { ok: true, status: 200, json: async () => backendState };
    return { ok: false, status: 404, json: async () => ({ error: "Not found" }) };
  };
  const snapshot = await new VerdeApi({ fetchImpl }).getSnapshot();

  assert.equal(snapshot.online, true);
  assert.equal(snapshot.plant.cameraStatus, "CONNECTED");
  assert.equal(snapshot.plant.frameUrl, "/api/camera/frame?v=4");
  assert.equal(snapshot.sensors.find((sensor) => sensor.label === "pH").value, "6.1000");
  assert.deepEqual(calls, ["/api/status", "/api/sensors/latest", "/api/sensors/health", "/api/camera/pest-overlay"]);
});

test("integrated V8 pest result preserves backend text and confidence with a raw fallback", () => {
  const now = Date.parse("2026-11-05T09:00:30Z");
  const camera = { ai_capture_version: "2026-11-05T09:00:00Z", ai_image_available: true, ai_status: "READY",
    image_available: true, status: "CONNECTED", capture_version: 42 };
  const pest = { status: "READY", value: "Pest Detected", confidence: 0.689,
    detail: "5 possible printed insect prop(s) detected; farmer inspection recommended." };
  const result = normalizeIntegratedPest(pest, camera, now);
  assert.deepEqual(result, { detected: true, status: "Pest Detected", detail: pest.detail,
    confidence: "69% confidence", frameUrl: "/api/camera/frame?v=42", boxes: [], imageSize: null });
  assert.equal(normalizeIntegratedPest({ status: "READY", value: "No Pest Detected",
    detail: "No qualifying printed props.", confidence: null }, camera, now).detected, false);
});

test("dedicated pest photo uses matching V8 boxes while main camera stays annotated", () => {
  const version = new Date().toISOString();
  const state = { ...backendState, camera: { ...backendState.camera,
    ai_capture_version: version, ai_image_available: true, ai_status: "READY",
    image_available: true, status: "CONNECTED", capture_version: 42 },
    pest_detection: { status: "READY", value: "Pest Detected", detail: "5 possible printed props.", confidence: .7 } };
  const overlay = { generated_at: version, capture_id: "capture-3.jpg", image_size: [4608, 2592],
    boxes: [{ box_xyxy: [100, 200, 180, 280], confidence: .8 }] };
  const snapshot = normalizeBackendSnapshot(state, { sensors: state.sensors }, null, overlay);
  assert.equal(snapshot.plant.pestSection.status, state.pest_detection.value);
  assert.equal(snapshot.plant.pestSection.detail, state.pest_detection.detail);
  assert.equal(snapshot.plant.pestSection.frameUrl, `/api/camera/history/capture-3.jpg?v=${encodeURIComponent(version)}`);
  assert.deepEqual(snapshot.plant.pestSection.boxes, overlay.boxes);
  assert.equal(snapshot.plant.frameUrl, `/api/camera/annotated?v=${encodeURIComponent(version)}`);
  assert.equal(snapshot.plant.aiAnnotated, true);
  const mismatched = normalizeBackendSnapshot(state, { sensors: state.sensors }, null,
    { ...overlay, generated_at: "old" });
  assert.equal(mismatched.plant.pestSection.frameUrl, "/api/camera/frame?v=42");
  assert.deepEqual(mismatched.plant.pestSection.boxes, []);
});

test("integrated pest fallback rejects non-READY, malformed and stale responses", () => {
  const now = Date.parse("2026-11-05T09:00:30Z");
  const camera = { ai_capture_version: "2026-11-05T09:00:00Z", ai_image_available: true, ai_status: "READY" };
  const valid = { status: "READY", value: "Pest Detected", detail: "5 props", confidence: 0.8 };
  for (const [pest, frame] of [
    [{ ...valid, status: "MODEL NOT LOADED" }, camera],
    [{ ...valid, value: null }, camera],
    [{ ...valid, detail: null }, camera],
    [{ ...valid, confidence: "0.8" }, camera],
    [null, camera],
    [valid, { ...camera, ai_capture_version: "2026-11-05T08:55:00Z" }]
  ]) {
    const result = normalizeIntegratedPest(pest, frame, now);
    assert.equal(result.detected, null);
    assert.equal(result.frameUrl, null);
  }
});

test("SMS settings use the authenticated backend and never put a number in browser storage", async () => {
  const calls = [];
  const fetchImpl = async (url, options = {}) => {
    calls.push({ url, options });
    const payload = url === "/api/session" ? { token: "session-token" }
      : { sms_enabled: true, recipient_configured: true, recipient_masked: "••••4567", modem_configured: true };
    return { ok: true, status: 200, json: async () => payload };
  };
  const api = new VerdeApi({ fetchImpl });
  assert.equal((await api.getSmsSettings()).recipient_masked, "••••4567");
  await api.updateSmsSettings({ smsEnabled: true, recipient: "+639171234567" });
  assert.deepEqual(calls.map(({ url }) => url), ["/api/gsm/settings", "/api/session", "/api/gsm/settings"]);
  assert.equal(calls[2].options.headers["X-VERDE-Token"], "session-token");
  assert.deepEqual(JSON.parse(calls[2].options.body), {
    sms_enabled: true, recipient: "+639171234567"
  });
  await assert.rejects(api.updateSmsSettings({ smsEnabled: true, recipient: "invalid" }), /7–15 digits/);
  assert.equal(calls.length, 3);
});

test("SMS settings degrade safely on older backends", async () => {
  const fetchImpl = async () => ({ ok: false, status: 404, json: async () => ({ error: "Not found" }) });
  assert.deepEqual(await new VerdeApi({ fetchImpl }).getSmsSettings(), { supported: false });
});

test("mock SMS settings are separate from the live modem", async () => {
  const api = new MockVerdeApi({ delay: 0 });
  assert.equal((await api.getSmsSettings()).sms_enabled, false);
  await api.updateSmsSettings({ smsEnabled: true, recipient: "+639171234567" });
  assert.equal((await api.getSmsSettings()).recipient_masked, "••••4567");
  assert.equal((await api.getSmsSettings()).modem_configured, false);
});

test("plant slots normalize six fixed positions and reject older slot APIs", () => {
  const records = Array.from({ length: 6 }, (_, index) => ({
    slot: index + 1, planted_on: index === 0 ? "2026-10-01" : null,
    days_growing: index === 0 ? 25 : null
  }));
  const slots = normalizePlantSlots({ as_of: "2026-10-26", slot_count: 6, slots: records });
  assert.equal(slots.supported, true);
  assert.equal(slots.slots.length, 6);
  assert.deepEqual(slots.slots[0], { slot: 1, plantedOn: "2026-10-01", daysGrowing: 25 });
  assert.deepEqual(slots.slots[5], { slot: 6, plantedOn: null, daysGrowing: null });
  assert.equal(normalizePlantSlots({ slot_count: 8, slots: [...records, { slot: 7 }, { slot: 8 }] }).supported, false);
  assert.equal(normalizePlantSlots({ slot_count: 10, slots: Array.from({ length: 10 }, (_, index) => ({ slot: index + 1 })) }).supported, false);
});

test("plant slot updates use the authenticated backend", async () => {
  const calls = [];
  const fetchImpl = async (url, options = {}) => {
    calls.push({ url, options });
    const payload = url === "/api/session" ? { token: "session-token" }
      : { as_of: "2026-10-26", slot_count: 6,
        slots: Array.from({ length: 6 }, (_, index) => ({ slot: index + 1,
          planted_on: index === 0 ? "2026-10-01" : null, days_growing: index === 0 ? 25 : null })) };
    return { ok: true, status: 200, json: async () => payload };
  };
  const api = new VerdeApi({ fetchImpl });
  assert.equal((await api.getPlantSlots()).slots.length, 6);
  await api.updatePlantSlots({ operation: "set", slot: 1, planted_on: "2026-10-01" });
  assert.deepEqual(calls.map(({ url }) => url), ["/api/plant-slots", "/api/session", "/api/plant-slots"]);
  assert.equal(calls[2].options.headers["X-VERDE-Token"], "session-token");
  assert.equal(JSON.parse(calls[2].options.body).slot, 1);
});

test("mock plant slot dates can be swapped and erased", async () => {
  const api = new MockVerdeApi({ delay: 0 });
  await api.updatePlantSlots({ operation: "set", slot: 1, planted_on: "2026-01-01" });
  await api.updatePlantSlots({ operation: "swap", first: 1, second: 6 });
  let slots = await api.getPlantSlots();
  assert.equal(slots.slots[0].plantedOn, null);
  assert.equal(slots.slots[5].plantedOn, "2026-01-01");
  await api.updatePlantSlots({ operation: "clear", slot: 6 });
  slots = await api.getPlantSlots();
  assert.equal(slots.slots[5].plantedOn, null);
});
