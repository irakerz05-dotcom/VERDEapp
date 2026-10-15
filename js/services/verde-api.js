// Browser API boundary. Hardware access and safety decisions stay in the
// Raspberry Pi backend; this module only translates its JSON into UI data.

const HISTORY_METRICS = [
  { key: "ph", label: "pH", unit: "", color: "#27813e" },
  { key: "ec", label: "EC", unit: "mS/cm", color: "#0f766e" },
  { key: "turbidity", label: "Turbidity", unit: "NTU", color: "#7c3aed" },
  { key: "water_temperature", label: "Water temperature", unit: "°C", color: "#d97706" },
  { key: "ambient_humidity", label: "Humidity", unit: "%", color: "#2563a8" }
];

const HISTORY = {
  Today: {
    range: "Today",
    series: {
      ph: [5.8, 5.9, 6.2, 6.1, 5.9, 5.9],
      ec: [1.43, 1.47, 1.5, 1.48, 1.51, 1.5],
      water_temperature: [21.8, 21.9, 22.2, 22.5, 22.3, 22.1],
      turbidity: [1.02, 1.01, 1.0, 1.03, 1.01, 1.0],
      ambient_humidity: [62, 63, 64, 63, 62, 62]
    },
    labels: ["12 AM", "4 AM", "8 AM", "12 PM", "4 PM", "Now"]
  },
  "24 Hours": {
    range: "24 Hours",
    series: {
      ph: [5.7, 5.8, 6.0, 6.2, 6.1, 5.9, 5.8, 5.9],
      ec: [1.41, 1.44, 1.47, 1.5, 1.49, 1.48, 1.51, 1.5],
      water_temperature: [21.5, 21.6, 21.9, 22.3, 22.6, 22.4, 22.2, 22.1],
      turbidity: [1.03, 1.02, 1.01, 1.0, 1.01, 1.0, 1.02, 1.0],
      ambient_humidity: [61, 62, 63, 64, 63, 62, 62, 62]
    },
    labels: ["24h ago", "20h", "16h", "12h", "8h", "4h", "2h", "Now"]
  },
  "7 Days": {
    range: "7 Days",
    series: {
      ph: [6.0, 5.8, 5.9, 6.1, 6.0, 5.9, 5.9],
      ec: [1.46, 1.43, 1.47, 1.52, 1.49, 1.51, 1.5],
      water_temperature: [22.4, 22.1, 21.9, 22.5, 22.2, 22.3, 22.1],
      turbidity: [1.01, 1.03, 1.02, 1.0, 1.01, 1.02, 1.0],
      ambient_humidity: [61, 63, 64, 62, 61, 62, 62]
    },
    labels: ["Thu", "Fri", "Sat", "Sun", "Mon", "Tue", "Today"]
  }
};

const MOCK_EVENT_TEMPLATES = [
  {
    id: "mock-cycle",
    minutesAgo: 0,
    category: "system",
    message: "Mock monitoring cycle completed. These entries demonstrate the incident log without claiming live hardware results."
  },
  {
    id: "mock-sensor-resolved",
    minutesAgo: 3,
    category: "problem_resolved",
    message: "Resolved: Water temperature returned to the configured range.",
    payload: { state: "RESOLVED", source: "sensor", severity: "resolved", issue_key: "sensor:water_temperature:range" }
  },
  {
    id: "mock-fusion-resolved",
    minutesAgo: 8,
    category: "problem_resolved",
    message: "Resolved: Sensor and plant-vision results are consistent again.",
    payload: { state: "RESOLVED", source: "fusion", severity: "resolved", issue_key: "fusion:low_confidence" }
  },
  {
    id: "mock-vision-resolved",
    minutesAgo: 12,
    category: "problem_resolved",
    message: "Resolved: Follow-up plant images no longer show possible pest presence.",
    payload: { state: "RESOLVED", source: "vision", severity: "resolved", issue_key: "vision:pest" }
  },
  {
    id: "mock-sensor-opened",
    minutesAgo: 18,
    category: "problem_opened",
    message: "Water temperature was outside the configured range.",
    payload: { state: "OPEN", source: "sensor", severity: "warning", issue_key: "sensor:water_temperature:range" }
  },
  {
    id: "mock-fusion-opened",
    minutesAgo: 24,
    category: "problem_opened",
    message: "Sensor and plant-vision results disagreed, producing low fusion confidence.",
    payload: { state: "OPEN", source: "fusion", severity: "warning", issue_key: "fusion:low_confidence" }
  },
  {
    id: "mock-vision-opened",
    minutesAgo: 31,
    category: "problem_opened",
    message: "Plant vision detected possible pest presence; farmer inspection recommended.",
    payload: { state: "OPEN", source: "vision", severity: "warning", issue_key: "vision:pest" }
  }
];

function mockEventRows(now = Date.now()) {
  return MOCK_EVENT_TEMPLATES.map(({ minutesAgo, ...event }) => ({
    ...event,
    timestamp: new Date(now - minutesAgo * 60_000).toISOString()
  }));
}

const SENSOR_PRESENTATION = {
  ph: { label: "pH", icon: "◈" },
  ec: { label: "EC", icon: "⌁" },
  turbidity: { label: "Turbidity", icon: "≋" },
  water_temperature: { label: "Water Temperature", icon: "♨" },
  ambient_humidity: { label: "Humidity", icon: "○" }
};

const DISPLAY_TO_BACKEND_MODE = {
  "Full Automation": "Full Automation Mode",
  "Semi-Automation": "Semi-Automation Mode"
};

const copy = (value) => JSON.parse(JSON.stringify(value));
const displayMode = (mode) => String(mode ?? "").replace(/ Mode$/, "") || "Unavailable";
const resultValue = (result, fallback = "Unavailable") => result?.value ?? result?.status ?? fallback;

function finiteNumber(value) {
  if (value === null || value === undefined || value === "") return null;
  const number = Number(value);
  return Number.isFinite(number) ? number : null;
}

function liveSensorValue(key, sensor) {
  if (key === "ec") return finiteNumber(sensor.value_mScm ?? sensor.value);
  if (key === "turbidity") return finiteNumber(sensor.value_ntu ?? sensor.value);
  if (key === "water_temperature") return finiteNumber(sensor.value_C ?? sensor.value);
  return finiteNumber(sensor.value);
}

function liveSensorUnit(key, sensor) {
  if (key === "ph") return "pH";
  if (key === "ec") return "mS/cm";
  if (key === "turbidity") return "NTU";
  if (key === "water_temperature") return "°C";
  if (key === "ambient_humidity") return "%";
  return sensor.unit ?? "";
}

function liveSensorBadge(key, sensor, value) {
  const backendStatus = String(sensor.status ?? "UNAVAILABLE");
  if (value === null) {
    if (/baseline_pending/i.test(backendStatus)) return "BASELINE PENDING";
    if (/error|fault/i.test(backendStatus)) return "ERROR";
    return "UNAVAILABLE";
  }

  const classification = String(sensor.classification ?? "").trim();
  if (classification && classification.toUpperCase() !== "UNAVAILABLE") return classification;
  if (/error|fault/i.test(backendStatus)) return "ERROR";
  if (/warning/i.test(backendStatus)) return "WARNING";
  return "CONNECTED";
}

function liveSensorDetail(key, sensor, healthStatus) {
  if (["ph", "ec", "turbidity"].includes(key)) return "";
  const details = [];
  const backendStatus = String(sensor.status ?? healthStatus ?? "").trim();
  if (backendStatus) details.push(backendStatus);

  const filteredVoltage = finiteNumber(sensor.filtered_voltage_V);
  if (filteredVoltage !== null) details.push(`Filtered ${filteredVoltage.toFixed(4)} V`);
  if (sensor.spike === true) details.push("Spike flagged by backend");

  if (key === "turbidity") {
    const reference = finiteNumber(sensor.reference_voltage_V);
    if (reference !== null) details.push(`1.00 NTU reference ${reference.toFixed(4)} V`);
  }
  return details.join(" · ");
}

export function normalizeLiveSensorSnapshot(payload, health = null) {
  const source = payload?.sensors;
  if (!source || typeof source !== "object") {
    return Object.entries(SENSOR_PRESENTATION).map(([key, presentation]) => ({
      ...presentation,
      value: "—",
      unit: liveSensorUnit(key, {}),
      status: "UNAVAILABLE",
      detail: "The live sensor snapshot is unavailable.",
      isRaw: false,
      lastReadingAt: null
    }));
  }

  return Object.entries(SENSOR_PRESENTATION).map(([key, presentation]) => {
    const sensor = source[key] && typeof source[key] === "object" ? source[key] : {};
    const value = liveSensorValue(key, sensor);
    const healthKey = key;
    return {
      ...presentation,
      value: value === null ? "—" : (["ph", "ec", "turbidity"].includes(key) ? Number(value).toFixed(4) : String(value)),
      unit: liveSensorUnit(key, sensor),
      status: liveSensorBadge(key, sensor, value),
      detail: liveSensorDetail(key, sensor, health?.sensors?.[healthKey]),
      isRaw: false,
      lastReadingAt: payload.timestamp ?? health?.timestamp ?? null
    };
  });
}

function historyStart(range, now) {
  if (range === "Today") {
    const start = new Date(now);
    start.setHours(0, 0, 0, 0);
    return start.getTime();
  }
  const duration = range === "7 Days" ? 7 * 24 * 60 * 60 * 1_000 : 24 * 60 * 60 * 1_000;
  return now.getTime() - duration;
}

function historyLabel(timestamp, range) {
  const date = new Date(timestamp);
  if (Number.isNaN(date.getTime())) return "Unknown";
  if (range === "7 Days") return new Intl.DateTimeFormat(undefined, { weekday: "short", hour: "numeric" }).format(date);
  return new Intl.DateTimeFormat(undefined, { hour: "numeric", minute: "2-digit" }).format(date);
}

export function normalizeBackendSnapshot(state, liveSensors = null, sensorHealth = null) {
  if (!state || typeof state !== "object" || !state.sensors || !state.automation) {
    throw new Error("The VERDE backend returned an invalid status response.");
  }

  const sensors = normalizeLiveSensorSnapshot(liveSensors, sensorHealth);

  const plant = state.plant_condition ?? {};
  const pest = state.pest_detection ?? {};
  const camera = state.camera ?? {};
  const fusion = state.fusion ?? {};
  const selectedMode = displayMode(state.automation.selected_mode);
  const activeMode = displayMode(state.automation.active_mode);

  return {
    online: true,
    isMock: false,
    mode: activeMode,
    requestedMode: selectedMode,
    modeOverride: state.automation.override ? state.automation.override_reason : null,
    updatedAt: liveSensors?.timestamp ?? sensorHealth?.timestamp ?? state.timestamp,
    systemStatus: sensorHealth?.status ?? liveSensors?.system?.overall_status ?? state.system_status ?? "UNAVAILABLE",
    sensors,
    waterQuality: {
      status: resultValue(state.water_quality),
      summary: state.water_quality?.detail || state.water_quality?.status || "No classifier detail is available."
    },
    plant: {
      condition: resultValue(plant),
      status: plant.status ?? "UNAVAILABLE",
      pestDetected: pest.value === "Pest Detected" ? true : pest.value === "No Pest Detected" ? false : null,
      pestStatus: resultValue(pest),
      confidence: "Unavailable",
      frameUrl: camera.image_available ? `/api/camera/frame?v=${encodeURIComponent(camera.capture_version ?? "latest")}` : null,
      lastCaptureAt: camera.last_capture_timestamp ?? null,
      cameraStatus: camera.status ?? "UNAVAILABLE"
    },
    fusion: {
      confidence: resultValue(fusion),
      reason: fusion.detail || fusion.status || "Fusion output is unavailable."
    },
    alerts: Array.isArray(state.alerts) ? state.alerts : [],
    incidents: (Array.isArray(state.incidents) ? state.incidents : []).map((incident) => ({
      issueKey: incident.issue_key ?? null,
      source: incident.source ?? "system",
      severity: incident.severity ?? "warning",
      message: incident.message ?? "Active incident",
      state: incident.state ?? "OPEN",
      openedAt: incident.opened_at ?? null,
      acknowledgedAt: incident.acknowledged_at ?? null
    })),
    settings: {
      backendConnected: true,
      backendLabel: sensorHealth?.status ? `Sensors ${sensorHealth.status}` : "Connected locally",
      version: `v${state.version ?? "0.1"}`
    }
  };
}

function summarizeHistoryMetric(metric, samples) {
  const values = samples.map((sample) => sample.value);
  return {
    ...metric,
    values,
    samples,
    sampleCount: values.length,
    current: values.length ? values.at(-1) : "—",
    minimum: values.length ? Math.min(...values) : "—",
    maximum: values.length ? Math.max(...values) : "—",
    average: values.length ? Number((values.reduce((sum, value) => sum + value, 0) / values.length).toFixed(2)) : "—"
  };
}

function historyDescription(metric, range) {
  const period = range === "Today" ? "today" : range === "24 Hours" ? "over the last 24 hours" : "over the last 7 days";
  return `${metric.label} samples ${period}`;
}

function historyView(range, metrics, selectedMetric, incidents = []) {
  const requested = metrics.find((metric) => metric.key === selectedMetric);
  const selected = requested ?? metrics.find((metric) => metric.sampleCount) ?? metrics[0];
  return {
    range,
    metrics: metrics.map(({ key, label, unit, color, sampleCount }) => ({ key, label, unit, color, sampleCount })),
    metricKey: selected.key,
    title: `${selected.label} trend`,
    description: historyDescription(selected, range),
    unit: selected.unit,
    color: selected.color,
    values: selected.values,
    labels: selected.samples.length ? selected.samples.map((sample) => sample.label) : ["No data"],
    samples: selected.samples,
    sampleCount: selected.sampleCount,
    current: selected.current,
    minimum: selected.minimum,
    maximum: selected.maximum,
    average: selected.average,
    incidents
  };
}

export function normalizeBackendHistory(rows, range = "Today", now = new Date(), selectedMetric = null, eventRows = []) {
  const selectedRange = ["Today", "24 Hours", "7 Days"].includes(range) ? range : "Today";
  const start = historyStart(selectedRange, now);
  const validRows = (Array.isArray(rows) ? rows : [])
    .filter((row) => Number.isFinite(Date.parse(row?.timestamp)) && Date.parse(row.timestamp) >= start)
    .sort((left, right) => Date.parse(left.timestamp) - Date.parse(right.timestamp));
  const metrics = HISTORY_METRICS.map((metric) => summarizeHistoryMetric(metric, validRows
    .map((row) => ({ timestamp: row.timestamp, label: historyLabel(row.timestamp, selectedRange), value: finiteNumber(row[metric.key]) }))
    .filter((sample) => sample.value !== null)));
  const incidents = normalizeBackendEvents(eventRows).filter((event) =>
    (event.state === "OPEN" || event.state === "RESOLVED")
    && Number.isFinite(Date.parse(event.createdAt))
    && Date.parse(event.createdAt) >= start);
  return historyView(selectedRange, metrics, selectedMetric, incidents);
}

function eventPayload(value) {
  if (value && typeof value === "object" && !Array.isArray(value)) return value;
  try {
    const parsed = JSON.parse(value ?? "{}");
    return parsed && typeof parsed === "object" && !Array.isArray(parsed) ? parsed : {};
  } catch {
    return {};
  }
}

export function normalizeBackendEvents(rows) {
  return (Array.isArray(rows) ? rows : []).map((row) => {
    const category = String(row.category ?? "event");
    const payload = eventPayload(row.payload);
    const state = payload.state
      ?? (category === "problem_resolved" ? "RESOLVED"
        : category === "problem_acknowledged" ? "ACKNOWLEDGED"
          : category === "problem_opened" ? "OPEN" : null);
    const source = String(payload.source ?? category).replaceAll("_", " ");
    const danger = payload.severity === "critical" || /error|fault|critical/i.test(`${category} ${row.message ?? ""}`);
    const warning = payload.severity === "warning" || category === "warning" || /warning|pending|unavailable/i.test(String(row.message ?? ""));
    const resolved = state === "RESOLVED";
    const acknowledged = state === "ACKNOWLEDGED";
    const tone = resolved ? "good" : danger ? "danger" : warning || acknowledged ? "warn" : "info";
    const title = state
      ? `${source.replace(/\b\w/g, (letter) => letter.toUpperCase())} ${resolved ? "recovered" : acknowledged ? "acknowledged" : "problem"}`
      : category.replaceAll("_", " ").replace(/\b\w/g, (letter) => letter.toUpperCase());
    return {
      id: `event-${row.id ?? `${row.timestamp}-${category}`}`,
      category,
      state,
      source,
      issueKey: payload.issue_key ?? null,
      tone,
      icon: resolved ? "✓" : acknowledged ? "◎" : danger ? "!" : warning ? "△" : "◉",
      title,
      message: row.message ?? "Backend event",
      createdAt: row.timestamp
    };
  });
}

export class VerdeApi {
  constructor({ fetchImpl = globalThis.fetch, baseUrl = "" } = {}) {
    if (typeof fetchImpl !== "function") throw new TypeError("A fetch implementation is required.");
    this.fetchImpl = fetchImpl.bind(globalThis);
    this.baseUrl = String(baseUrl).replace(/\/$/, "");
    this.token = null;
  }

  async request(path, options = {}) {
    const response = await this.fetchImpl(`${this.baseUrl}${path}`, { cache: "no-store", ...options });
    let payload;
    try {
      payload = await response.json();
    } catch {
      payload = null;
    }
    if (!response.ok) {
      const error = new Error(payload?.error || `VERDE backend request failed (HTTP ${response.status}).`);
      error.status = response.status;
      throw error;
    }
    return payload;
  }

  async getSnapshot() {
    const [state, liveSensors, sensorHealth] = await Promise.all([
      this.request("/api/status"),
      this.request("/api/sensors/latest"),
      this.request("/api/sensors/health")
    ]);
    return normalizeBackendSnapshot(state, liveSensors, sensorHealth);
  }

  async getHistory(range = "Today", selectedMetric = null) {
    const [historyPayload, eventPayload] = await Promise.all([
      this.request("/api/history"),
      this.request("/api/events")
    ]);
    return normalizeBackendHistory(historyPayload?.rows, range, new Date(), selectedMetric, eventPayload?.rows);
  }

  async getAlerts() {
    const payload = await this.request("/api/events");
    return normalizeBackendEvents(payload?.rows);
  }

  async sessionToken(forceRefresh = false) {
    if (!this.token || forceRefresh) this.token = (await this.request("/api/session")).token;
    if (!this.token) throw new Error("The VERDE backend did not provide a session token.");
    return this.token;
  }

  async requestModeChange(mode) {
    const backendMode = DISPLAY_TO_BACKEND_MODE[mode];
    if (!backendMode) throw new Error("Unsupported operating mode.");

    const post = async (refreshToken = false) => this.request("/api/mode", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-VERDE-Token": await this.sessionToken(refreshToken)
      },
      body: JSON.stringify({ mode: backendMode })
    });

    let state;
    try {
      state = await post(false);
    } catch (error) {
      if (error.status !== 403) throw error;
      this.token = null;
      state = await post(true);
    }
    const normalized = normalizeBackendSnapshot(state);
    const overridden = normalized.mode !== normalized.requestedMode;
    return {
      accepted: true,
      mode: normalized.requestedMode,
      activeMode: normalized.mode,
      message: overridden
        ? `${normalized.requestedMode} was requested, but the safety override keeps ${normalized.mode} active.`
        : `Operating mode changed to ${normalized.mode}. Physical outputs remain disabled.`
    };
  }

  async acknowledgeIssue(issueKey) {
    if (typeof issueKey !== "string" || !issueKey) throw new Error("A valid incident is required.");
    const post = async (refreshToken = false) => this.request("/api/incidents/acknowledge", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-VERDE-Token": await this.sessionToken(refreshToken)
      },
      body: JSON.stringify({ issue_key: issueKey })
    });
    try {
      return await post(false);
    } catch (error) {
      if (error.status !== 403) throw error;
      this.token = null;
      return post(true);
    }
  }
}

export class MockVerdeApi {
  constructor({ delay = 120, shouldFail = false, online = true } = {}) {
    this.delay = Math.max(0, Number(delay) || 0);
    this.shouldFail = Boolean(shouldFail);
    this.online = Boolean(online);
    this.mode = "Full Automation";
  }

  async respond(value) {
    if (this.delay) await new Promise((resolve) => setTimeout(resolve, this.delay));
    if (this.shouldFail) throw new Error("The mock VERDE service is unavailable.");
    return copy(value);
  }

  async getSnapshot() {
    return this.respond({
      online: this.online,
      isMock: true,
      mode: this.mode,
      requestedMode: this.mode,
      modeOverride: null,
      updatedAt: new Date().toISOString(),
      systemStatus: "MOCK DEVELOPMENT DATA",
      sensors: [
        { label: "pH", value: "5.9", unit: "", status: "Optimal", icon: "◈" },
        { label: "EC", value: "1.5", unit: "mS/cm", status: "Optimal", icon: "⌁" },
        { label: "Turbidity", value: "1.00", unit: "NTU", status: "Optimal", icon: "≋", detail: "Project 1.00 NTU reference calibration" },
        { label: "Water Temperature", value: "22.1", unit: "°C", status: "Optimal", icon: "♨" },
        { label: "Humidity", value: "62", unit: "%", status: "Connected", icon: "○" },
      ],
      waterQuality: {
        status: "Optimal",
        summary: "All four classifier inputs are within their ideal ranges."
      },
      plant: {
        condition: "Healthy",
        status: "READY",
        pestDetected: false,
        pestStatus: "No Pest Detected",
        confidence: "92%",
        frameUrl: null,
        lastCaptureAt: null,
        cameraStatus: "MOCK"
      },
      fusion: {
        confidence: "High",
        reason: "Sensor readings and plant condition agree."
      },
      alerts: [],
      settings: {
        backendConnected: false,
        backendLabel: "Mock adapter",
        version: "v0.3"
      }
    });
  }

  async getHistory(range = "Today", selectedMetric = null) {
    const selected = HISTORY[range] ?? HISTORY.Today;
    const metrics = HISTORY_METRICS.map((metric) => summarizeHistoryMetric(metric,
      selected.series[metric.key].map((value, index) => ({
        timestamp: new Date(Date.now() - (selected.labels.length - 1 - index) * 60 * 60 * 1_000).toISOString(),
        label: selected.labels[index],
        value
      }))));
    const incidents = normalizeBackendEvents(mockEventRows()).filter((event) => event.state);
    return this.respond(historyView(selected.range, metrics, selectedMetric, incidents));
  }

  async getAlerts() {
    return this.respond(normalizeBackendEvents(mockEventRows()));
  }

  async requestModeChange(mode) {
    if (!Object.hasOwn(DISPLAY_TO_BACKEND_MODE, mode)) throw new Error("Unsupported operating mode.");
    await this.respond(null);
    this.mode = mode;
    return {
      accepted: true,
      mode,
      activeMode: mode,
      message: `Mock mode changed to ${mode}. The live backend will validate real requests.`
    };
  }

  async acknowledgeIssue(issueKey) {
    if (typeof issueKey !== "string" || !issueKey) throw new Error("A valid incident is required.");
    return this.respond({ issueKey, state: "ACKNOWLEDGED" });
  }
}
