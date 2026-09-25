// Browser API boundary. Hardware access and safety decisions stay in the
// Raspberry Pi backend; this module only translates its JSON into UI data.

const HISTORY = {
  Today: {
    range: "Today",
    title: "pH trend",
    description: "Nutrient solution pH today",
    values: [5.8, 5.9, 6.2, 6.1, 5.9, 5.9],
    labels: ["12 AM", "4 AM", "8 AM", "12 PM", "4 PM", "Now"]
  },
  "24 Hours": {
    range: "24 Hours",
    title: "pH trend",
    description: "Nutrient solution pH over 24 hours",
    values: [5.7, 5.8, 6.0, 6.2, 6.1, 5.9, 5.8, 5.9],
    labels: ["24h ago", "20h", "16h", "12h", "8h", "4h", "2h", "Now"]
  },
  "7 Days": {
    range: "7 Days",
    title: "pH trend",
    description: "Available daily pH samples from the last 7 days",
    values: [6.0, 5.8, 5.9, 6.1, 6.0, 5.9, 5.9],
    labels: ["Thu", "Fri", "Sat", "Sun", "Mon", "Tue", "Today"]
  }
};

const ALERT_TEMPLATES = [
  {
    id: "system-clear",
    tone: "good",
    icon: "✓",
    title: "No active critical alerts",
    message: "All monitored mock systems are currently within their configured ranges.",
    minutesAgo: 0
  },
  {
    id: "plant-check",
    tone: "info",
    icon: "◉",
    title: "Plant check completed",
    message: "Healthy condition and no pest presence detected.",
    minutesAgo: 2
  },
  {
    id: "water-quality",
    tone: "info",
    icon: "◈",
    title: "Water quality optimal",
    message: "All four water-classifier inputs are within range.",
    minutesAgo: 5
  }
];

const SENSOR_PRESENTATION = {
  ph: { label: "pH", icon: "◈" },
  ec: { label: "EC", icon: "⌁" },
  tds: { label: "TDS", icon: "⋮" },
  water_temperature: { label: "Water Temperature", icon: "♨" },
  turbidity: { label: "Turbidity", icon: "≋" },
  ambient_humidity: { label: "Ambient Humidity", icon: "◌" }
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

export function normalizeBackendSnapshot(state) {
  if (!state || typeof state !== "object" || !state.sensors || !state.automation) {
    throw new Error("The VERDE backend returned an invalid status response.");
  }

  const sensors = Object.entries(SENSOR_PRESENTATION).map(([key, presentation]) => {
    const sensor = state.sensors[key] ?? {};
    const value = sensor.value;
    return {
      ...presentation,
      value: value === null || value === undefined ? "—" : String(value),
      unit: sensor.unit ?? "",
      status: sensor.status ?? "UNAVAILABLE",
      detail: sensor.detail ?? "",
      lastReadingAt: sensor.last_reading_timestamp ?? null
    };
  });

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
    updatedAt: state.timestamp,
    systemStatus: state.system_status ?? "UNAVAILABLE",
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
    settings: {
      backendConnected: true,
      backendLabel: "Connected locally",
      version: `v${state.version ?? "0.1"}`
    }
  };
}

export function normalizeBackendHistory(rows, range = "Today", now = new Date()) {
  const selectedRange = ["Today", "24 Hours", "7 Days"].includes(range) ? range : "Today";
  const start = historyStart(selectedRange, now);
  const samples = (Array.isArray(rows) ? rows : [])
    .map((row) => ({ timestamp: row.timestamp, value: finiteNumber(row.ph) }))
    .filter((row) => row.value !== null && Number.isFinite(Date.parse(row.timestamp)) && Date.parse(row.timestamp) >= start)
    .sort((left, right) => Date.parse(left.timestamp) - Date.parse(right.timestamp));
  const values = samples.map((sample) => sample.value);
  const description = {
    Today: "Available nutrient solution pH samples today",
    "24 Hours": "Available nutrient solution pH samples over 24 hours",
    "7 Days": "Available nutrient solution pH samples over 7 days"
  }[selectedRange];

  return {
    range: selectedRange,
    title: "pH trend",
    description,
    values,
    labels: samples.length ? samples.map((sample) => historyLabel(sample.timestamp, selectedRange)) : ["No data"],
    current: values.length ? values.at(-1) : "—",
    maximum: values.length ? Math.max(...values) : "—",
    average: values.length ? Number((values.reduce((sum, value) => sum + value, 0) / values.length).toFixed(2)) : "—"
  };
}

export function normalizeBackendEvents(rows) {
  return (Array.isArray(rows) ? rows : []).map((row) => {
    const category = String(row.category ?? "event");
    const danger = /error|fault|critical/i.test(`${category} ${row.message ?? ""}`);
    const warning = category === "warning" || /warning|pending|unavailable/i.test(String(row.message ?? ""));
    return {
      id: `event-${row.id ?? `${row.timestamp}-${category}`}`,
      tone: danger ? "danger" : warning ? "warn" : "info",
      icon: danger ? "!" : warning ? "△" : "◉",
      title: category.replaceAll("_", " ").replace(/\b\w/g, (letter) => letter.toUpperCase()),
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
    return normalizeBackendSnapshot(await this.request("/api/status"));
  }

  async getHistory(range = "Today") {
    const payload = await this.request("/api/history");
    return normalizeBackendHistory(payload?.rows, range);
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
        { label: "TDS", value: "750", unit: "ppm", status: "Normal", icon: "⋮" },
        { label: "Water Temperature", value: "22.1", unit: "°C", status: "Optimal", icon: "♨" },
        { label: "Turbidity", value: "3.2", unit: "NTU", status: "Optimal", icon: "≋" },
        { label: "Ambient Humidity", value: "72", unit: "%", status: "Normal", icon: "◌" }
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

  async getHistory(range = "Today") {
    const selected = HISTORY[range] ?? HISTORY.Today;
    const values = selected.values;
    return this.respond({
      ...selected,
      current: values.at(-1),
      maximum: Math.max(...values),
      average: Number((values.reduce((sum, value) => sum + value, 0) / values.length).toFixed(2))
    });
  }

  async getAlerts() {
    const now = Date.now();
    return this.respond(ALERT_TEMPLATES.map(({ minutesAgo, ...alert }) => ({
      ...alert,
      createdAt: new Date(now - minutesAgo * 60_000).toISOString()
    })));
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
}
