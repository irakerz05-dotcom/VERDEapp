import { MockVerdeApi, VerdeApi } from "./services/verde-api.js?v=10";
import { PAGES, buildChartGeometry, escapeHtml, niceTime, normalizePage, safeResourceUrl, statusClass } from "./verde-ui.js?v=10";

const query = new URLSearchParams(window.location.search);
const requestedDelay = query.has("mockDelay") ? Number(query.get("mockDelay")) : 120;
const usingMock = query.get("api") === "mock";
const api = usingMock
  ? new MockVerdeApi({
    delay: Number.isFinite(requestedDelay) ? Math.min(Math.max(requestedDelay, 0), 10_000) : 120,
    shouldFail: query.get("mockError") === "1",
    online: query.get("mockOffline") !== "1"
  })
  : new VerdeApi();

const app = document.querySelector("#app");
const API_TIMEOUT_MS = 4_000;
const HISTORY_RANGES = ["Today", "24 Hours", "7 Days"];
let activePage = pageFromHash();
let historyRange = "Today";
let renderSequence = 0;
let renderedPage = null;
let lastSnapshot = null;
const lastPageData = new Map();

const icon = (name) => ({ Dashboard: "⌂", Plants: "♧", History: "◷", Alerts: "♢", Settings: "⚙" })[name] ?? "•";
const safe = escapeHtml;

function pageFromHash() {
  try {
    return normalizePage(decodeURIComponent(window.location.hash.slice(1)));
  } catch {
    return "Dashboard";
  }
}

function withTimeout(promise, milliseconds = API_TIMEOUT_MS) {
  let timer;
  const timeout = new Promise((_, reject) => {
    timer = window.setTimeout(() => {
      const error = new Error("The VERDE service took too long to respond.");
      error.name = "TimeoutError";
      reject(error);
    }, milliseconds);
  });
  return Promise.race([promise, timeout]).finally(() => window.clearTimeout(timer));
}

function connectionState(data) {
  if (!navigator.onLine) return { online: false, label: "Offline" };
  if (data?.stale) return { online: false, label: "Stale data" };
  if (!data?.online) return { online: false, label: data?.isMock ? "Mock offline" : "Backend unavailable" };
  return { online: true, label: data?.isMock ? "Mock data" : "Backend connected" };
}

function sourceLabel(data) {
  if (data?.stale) return "Last successful data — backend currently unavailable";
  return data?.isMock ? "Mock development data — no hardware connection" : "Live data from the local VERDE backend";
}

function renderHeader(data) {
  const connection = connectionState(data);
  return `<header class="topbar">
    <div class="brand"><img src="icons/icon.svg" alt="" /><div><h1>VERDE</h1><p>Hydroponics Monitoring System</p></div></div>
    <span class="online ${connection.online ? "" : "offline"}"><i></i>${safe(connection.label)}</span>
  </header>`;
}

function renderConnectionBanner(data) {
  if (data?.stale) {
    return `<aside class="connection-banner offline-banner" role="status"><b>Stale data</b><span>${safe(data.staleReason || "The backend is unavailable. Values may no longer be current.")}</span></aside>`;
  }
  if (!navigator.onLine) {
    return `<aside class="connection-banner offline-banner" role="status"><b>Offline</b><span>${data?.isMock ? "Showing mock development data." : "Showing the last successful response when available."}</span></aside>`;
  }
  if (!data.online) {
    return `<aside class="connection-banner offline-banner" role="status"><b>${data?.isMock ? "Mock adapter offline" : "Backend unavailable"}</b><span>${data?.isMock ? "Data is available for interface testing only." : "Live readings could not be refreshed."}</span></aside>`;
  }
  return "";
}

function renderNav() {
  return `<nav aria-label="Main navigation">${PAGES.map((item) => {
    const current = item === activePage;
    return `<button class="nav-item ${current ? "active" : ""}" type="button" data-page="${item}"${current ? ' aria-current="page"' : ""}><span aria-hidden="true">${icon(item)}</span>${item}</button>`;
  }).join("")}</nav>`;
}

function renderShell(content, data) {
  return `<div class="app-shell">${renderHeader(data)}${renderConnectionBanner(data)}${content}${renderNav()}</div>`;
}

function renderCard(sensor) {
  const tone = statusClass(sensor.status);
  const marker = tone === "good" ? "✓" : tone === "danger" ? "!" : "·";
  return `<article class="sensor-card">
    <span class="sensor-icon" aria-hidden="true">${safe(sensor.icon)}</span>
    <div><h2>${safe(sensor.label)}</h2><p class="reading">${safe(sensor.value)}<small>${safe(sensor.unit)}</small></p>
    <span class="status ${tone}"><b aria-hidden="true">${marker}</b>${safe(sensor.status)}</span>
    ${sensor.detail ? `<p class="sensor-detail">${safe(sensor.detail)}</p>` : ""}</div>
  </article>`;
}

function bindNav() {
  document.querySelectorAll("[data-page]").forEach((button) => button.addEventListener("click", () => {
    const page = normalizePage(button.dataset.page);
    const nextHash = `#${encodeURIComponent(page)}`;
    if (window.location.hash === nextHash) {
      activePage = page;
      render();
    } else {
      window.location.hash = nextHash;
    }
  }));
}

function showToast(message, tone = "good") {
  document.querySelector(".toast")?.remove();
  const toast = document.createElement("div");
  toast.className = `toast ${tone}`;
  toast.setAttribute("role", tone === "danger" ? "alert" : "status");
  toast.textContent = message;
  document.body.append(toast);
  window.setTimeout(() => toast.remove(), 5_000);
}

function showModal({ title, text, confirmText, onConfirm }) {
  const dialog = document.createElement("dialog");
  dialog.innerHTML = `<form method="dialog"><h2>${safe(title)}</h2><p>${safe(text)}</p><div class="dialog-actions"><button value="cancel" class="secondary">Cancel</button><button value="confirm" class="primary">${safe(confirmText)}</button></div></form>`;
  dialog.addEventListener("close", async () => {
    if (dialog.returnValue === "confirm") await onConfirm();
    dialog.remove();
  });
  document.body.append(dialog);
  dialog.showModal();
}

async function requestModeChange(data, sourceButton) {
  const selectedMode = data.requestedMode || data.mode;
  const nextMode = selectedMode === "Full Automation" ? "Semi-Automation" : "Full Automation";
  showModal({
    title: `Switch to ${nextMode}?`,
    text: data.isMock
      ? "This changes mock state only. It does not contact or control hardware."
      : "The Raspberry Pi backend will validate the request and keep its safety override active when required. Physical outputs remain disabled in this prototype.",
    confirmText: "Request change",
    onConfirm: async () => {
      if (sourceButton) sourceButton.disabled = true;
      try {
        const result = await withTimeout(api.requestModeChange(nextMode));
        await render();
        showToast(result.message);
      } catch (error) {
        showToast(error?.message || "The mode change could not be completed.", "danger");
      } finally {
        if (sourceButton?.isConnected) sourceButton.disabled = false;
      }
    }
  });
}

function bindModeButton(data) {
  const button = document.querySelector("[data-mode-button]");
  button?.addEventListener("click", () => requestModeChange(data, button));
}

function renderDashboard(data) {
  const time = niceTime(data.updatedAt);
  const fusionHeading = /^(High|Medium|Low)$/i.test(data.fusion.confidence)
    ? `${data.fusion.confidence} confidence`
    : data.fusion.confidence;
  const content = `<section class="overview" aria-label="System overview">
      <div><span class="meta">LAST SAMPLE</span><strong>${safe(time)}</strong></div>
      <button data-mode-button class="mode" type="button"><span aria-hidden="true">⚙</span><div><span class="meta">ACTIVE MODE</span><strong>${safe(data.mode)}</strong><small>Requested: ${safe(data.requestedMode || data.mode)}</small></div></button>
    </section>
    ${data.modeOverride ? `<aside class="safety-note" role="status"><b>Safety override active</b><span>${safe(data.modeOverride)}</span></aside>` : ""}
    <section class="section-heading"><div><h2>Live readings</h2><p>${safe(sourceLabel(data))}</p></div><time datetime="${safe(data.updatedAt)}">Updated ${safe(time)}</time></section>
    <section class="sensor-grid" aria-label="Sensor readings">${data.sensors.map(renderCard).join("")}</section>
    <section class="insight-list" aria-label="System insights">
      <article class="insight water"><span class="big-icon" aria-hidden="true">◈</span><div><p class="eyebrow">WATER QUALITY</p><h2>${safe(data.waterQuality.status)}</h2><p>${safe(data.waterQuality.summary)}</p></div></article>
      <article class="insight"><span class="big-icon" aria-hidden="true">♧</span><div><p class="eyebrow">PLANT MONITORING</p><h2>${safe(data.plant.condition)}</h2><p>${safe(data.plant.pestStatus)} · Vision ${safe(data.plant.status)}</p></div></article>
      <article class="insight"><span class="big-icon" aria-hidden="true">◉</span><div><p class="eyebrow">SENSOR-VISION FUSION</p><h2>${safe(fusionHeading)}</h2><p>${safe(data.fusion.reason)}</p></div></article>
    </section>`;
  app.innerHTML = renderShell(content, data);
  bindModeButton(data);
  bindNav();
}

function renderPlants(data) {
  const conditionTone = statusClass(data.plant.condition);
  const frameUrl = safeResourceUrl(data.plant.frameUrl, window.location.href);
  const camera = frameUrl
    ? `<figure class="camera-frame"><img src="${safe(frameUrl)}" alt="Latest plant detection frame" /></figure>`
    : `<section class="camera-placeholder" aria-label="Latest camera frame unavailable"><span aria-hidden="true">▧</span><h2>Camera frame unavailable</h2><p>${safe(data.plant.cameraStatus || "No camera capture is available.")}</p></section>`;
  const pestKnown = typeof data.plant.pestDetected === "boolean";
  const content = `<section class="page-title"><h2>Plant Monitoring</h2><p>${safe(sourceLabel(data))}</p></section>
    ${camera}
    <section class="plant-panel"><div class="panel-head"><span class="big-icon" aria-hidden="true">♧</span><div><p class="eyebrow">PLANT CONDITION</p><h2>Vision analysis</h2></div></div><div class="plant-result"><div><span class="status ${conditionTone}"><b aria-hidden="true">${conditionTone === "good" ? "✓" : conditionTone === "danger" ? "!" : "·"}</b>${safe(data.plant.status)}</span><strong>${safe(data.plant.condition)}</strong></div><div class="confidence"><span>Model confidence</span><strong>${safe(data.plant.confidence)}</strong></div></div></section>
    <section class="plant-panel"><div class="panel-head"><span class="big-icon" aria-hidden="true">◌</span><div><p class="eyebrow">PEST STATUS</p><h2>Presence detection only</h2></div></div><div class="notice ${pestKnown ? (data.plant.pestDetected ? "danger" : "good") : "warn"}"><b aria-hidden="true">${!pestKnown || data.plant.pestDetected ? "!" : "✓"}</b>${safe(data.plant.pestStatus)}</div></section>
    <section class="plant-panel"><div class="panel-head"><span class="big-icon" aria-hidden="true">◉</span><div><p class="eyebrow">SENSOR-VISION FUSION</p><h2>Reliability indicator</h2></div></div><div class="fusion-result"><strong>${safe(data.fusion.confidence.toUpperCase())}</strong><p>${safe(data.fusion.reason)}</p></div></section>`;
  app.innerHTML = renderShell(content, data);
  bindNav();
}

function renderHistory(data, history) {
  const chart = buildChartGeometry(history.values);
  const circles = chart.points.map((point) => `<circle cx="${point.x}" cy="${point.y}" r="5" />`).join("");
  const content = `<section class="page-title"><h2>History</h2><p>${safe(sourceLabel(data))}</p></section>
    <div class="filter-row" role="group" aria-label="History range">${HISTORY_RANGES.map((range) => `<button type="button" data-history-range="${range}" class="${range === history.range ? "selected" : ""}" aria-pressed="${range === history.range}">${range}</button>`).join("")}</div>
    <section class="chart-card"><div><h2>${safe(history.title)}</h2><p>${safe(history.description)}</p></div><svg viewBox="0 0 320 150" role="img" aria-label="${safe(history.description)}"><path d="M20 125H304M20 90H304M20 55H304M20 20H304" stroke="#dbe6dd" stroke-dasharray="3"/><path d="${chart.path}" fill="none" stroke="#27813e" stroke-width="4"/><g fill="#27813e">${circles}</g></svg>${history.values.length ? `<div class="chart-labels"><span>${safe(history.labels[0])}</span><span>${safe(history.labels[Math.floor(history.labels.length / 2)])}</span><span>${safe(history.labels.at(-1))}</span></div>` : '<p class="no-chart-data">No pH samples are available in this range.</p>'}</section>
    <section class="stat-row" aria-label="pH summary"><div><strong>${safe(history.current)}</strong><span>Current</span></div><div><strong>${safe(history.maximum)}</strong><span>Maximum</span></div><div><strong>${safe(history.average)}</strong><span>Average</span></div></section>`;
  app.innerHTML = renderShell(content, data);
  document.querySelectorAll("[data-history-range]").forEach((button) => button.addEventListener("click", () => {
    historyRange = HISTORY_RANGES.includes(button.dataset.historyRange) ? button.dataset.historyRange : "Today";
    render();
  }));
  bindNav();
}

function relativeAlertTime(iso) {
  const minutes = Math.max(0, Math.round((Date.now() - new Date(iso).getTime()) / 60_000));
  if (!Number.isFinite(minutes) || minutes === 0) return "Just now";
  return `${minutes} minute${minutes === 1 ? "" : "s"} ago`;
}

function renderAlerts(data, alerts) {
  const items = alerts.map((alert) => `<article class="alert-item ${["good", "warn", "danger"].includes(alert.tone) ? alert.tone : ""}"><span aria-hidden="true">${safe(alert.icon)}</span><div><h2>${safe(alert.title)}</h2><p>${safe(alert.message)}</p><time datetime="${safe(alert.createdAt)}">${safe(relativeAlertTime(alert.createdAt))}</time></div></article>`).join("");
  const content = `<section class="page-title"><h2>Alerts</h2><p>${safe(sourceLabel(data))}</p></section><section class="alert-list">${items || '<article class="empty-list"><h2>No events</h2><p>The backend has not recorded any events yet.</p></article>'}</section>`;
  app.innerHTML = renderShell(content, data);
  bindNav();
}

function renderSettings(data) {
  const content = `<section class="page-title"><h2>Settings</h2><p>${safe(sourceLabel(data))}</p></section>
    <section class="settings-list">
      <article><div><h2>Backend connection</h2><p>${data.isMock ? "Explicit development adapter; no hardware connection." : "Same-origin connection to the local VERDE service."}</p></div><span>${safe(data.settings.backendLabel)}</span></article>
      <article><div><h2>Operating mode</h2><p>Active: ${safe(data.mode)} · Requested: ${safe(data.requestedMode || data.mode)}. Safety validation is enforced by the backend.</p></div><button data-mode-button type="button" class="secondary">Change mode</button></article>
      <article><div><h2>Application version</h2><p>VERDE monitoring PWA</p></div><span>${safe(data.settings.version)}</span></article>
    </section>`;
  app.innerHTML = renderShell(content, data);
  bindModeButton(data);
  bindNav();
}

function renderLoading() {
  const content = `<section class="state-card" role="status"><span class="spinner" aria-hidden="true"></span><h2>Loading ${safe(activePage)}</h2><p>${usingMock ? "Reading explicit mock development data…" : "Connecting to the local VERDE backend…"}</p></section>`;
  app.innerHTML = `<div class="app-shell">${renderHeader({ online: navigator.onLine, isMock: usingMock })}${content}${renderNav()}</div>`;
  bindNav();
}

function renderError(error) {
  const isTimeout = error?.name === "TimeoutError";
  const content = `<section class="state-card error-card" role="alert"><span aria-hidden="true">!</span><h2>${isTimeout ? "Request timed out" : `Unable to load ${usingMock ? "mock data" : "the VERDE backend"}`}</h2><p>${safe(error?.message || "An unexpected error occurred.")}</p>${usingMock ? "" : "<p>Start the backend with this PWA as its web root, then retry. Live failures never fall back to fake readings.</p>"}<button id="retry-button" class="primary" type="button">Try again</button></section>`;
  app.innerHTML = `<div class="app-shell">${renderHeader({ online: false, isMock: usingMock })}${content}${renderNav()}</div>`;
  document.querySelector("#retry-button").addEventListener("click", render);
  bindNav();
}

async function render() {
  const sequence = ++renderSequence;
  if (!lastSnapshot || renderedPage !== activePage) renderLoading();
  try {
    const requests = [api.getSnapshot()];
    if (activePage === "History") requests.push(api.getHistory(historyRange));
    if (activePage === "Alerts") requests.push(api.getAlerts());
    const [data, pageData] = await withTimeout(Promise.all(requests));
    if (sequence !== renderSequence) return;
    lastSnapshot = data;
    if (pageData !== undefined) lastPageData.set(activePage, pageData);

    if (activePage === "Plants") renderPlants(data);
    else if (activePage === "History") renderHistory(data, pageData);
    else if (activePage === "Alerts") renderAlerts(data, pageData);
    else if (activePage === "Settings") renderSettings(data);
    else renderDashboard(data);
    renderedPage = activePage;
  } catch (error) {
    if (sequence !== renderSequence) return;
    const cachedPageData = lastPageData.get(activePage);
    const pageNeedsData = activePage === "History" || activePage === "Alerts";
    if (lastSnapshot && (!pageNeedsData || cachedPageData !== undefined)) {
      const staleData = { ...lastSnapshot, online: false, stale: true, staleReason: error?.message || "The backend could not be refreshed." };
      if (activePage === "Plants") renderPlants(staleData);
      else if (activePage === "History") renderHistory(staleData, cachedPageData);
      else if (activePage === "Alerts") renderAlerts(staleData, cachedPageData);
      else if (activePage === "Settings") renderSettings(staleData);
      else renderDashboard(staleData);
      renderedPage = activePage;
    } else {
      renderError(error);
    }
  }
}

window.addEventListener("hashchange", () => {
  activePage = pageFromHash();
  render();
});
window.addEventListener("online", render);
window.addEventListener("offline", render);

if (!window.location.hash) window.history.replaceState(null, "", "#Dashboard");
if ("serviceWorker" in navigator) {
  window.addEventListener("load", () => navigator.serviceWorker.register("./service-worker.js", { updateViaCache: "none" }).catch(() => {
    showToast("Offline installation is unavailable in this browser.", "warn");
  }));
}

render();
window.setInterval(() => {
  if (!document.hidden && !document.querySelector("dialog[open]")) render();
}, 5_000);
