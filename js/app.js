import { MockVerdeApi } from "./services/verde-api.js";

const api = new MockVerdeApi();
const app = document.querySelector("#app");
let activePage = decodeURIComponent(window.location.hash.slice(1)) || "Dashboard";
const icon = (name) => ({ Dashboard: "⌂", Plants: "♧", History: "◷", Alerts: "♢", Settings: "⚙" }[name] ?? "•");
const niceTime = (iso) => new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short" }).format(new Date(iso));

function statusClass(status) {
  return /optimal|normal|healthy|high/i.test(status) ? "good" : /critical|fault/i.test(status) ? "danger" : "warn";
}

function renderCard(sensor) {
  const status = statusClass(sensor.status);
  return `<article class="sensor-card">
    <span class="sensor-icon" aria-hidden="true">${sensor.icon}</span>
    <div><h2>${sensor.label}</h2><p class="reading">${sensor.value}<small>${sensor.unit}</small></p>
    <span class="status ${status}"><b aria-hidden="true">✓</b>${sensor.status}</span></div>
  </article>`;
}

function renderNav() {
  return `<nav aria-label="Main navigation">${["Dashboard", "Plants", "History", "Alerts", "Settings"].map((item) => `<button class="nav-item ${item === activePage ? "active" : ""}" type="button" data-page="${item}" aria-current="${item === activePage ? "page" : "false"}"><span aria-hidden="true">${icon(item)}</span>${item}</button>`).join("")}</nav>`;
}

function bindNav() {
  document.querySelectorAll("[data-page]").forEach((button) => button.addEventListener("click", () => {
    activePage = button.dataset.page;
    window.location.hash = activePage;
    render();
  }));
}

function showModal(title, text, confirmText, onConfirm) {
  const dialog = document.createElement("dialog");
  dialog.innerHTML = `<form method="dialog"><h2>${title}</h2><p>${text}</p><div class="dialog-actions"><button value="cancel" class="secondary">Cancel</button><button value="confirm" class="primary">${confirmText}</button></div></form>`;
  dialog.addEventListener("close", async () => { if (dialog.returnValue === "confirm") await onConfirm(); dialog.remove(); });
  document.body.append(dialog); dialog.showModal();
}

async function render() {
  const data = await api.getSnapshot();
  const time = niceTime(data.updatedAt);
  if (activePage === "Plants") {
    app.innerHTML = `<div class="app-shell">
      <header class="topbar"><div class="brand"><img src="icons/icon.svg" alt="" /><div><h1>VERDE</h1><p>Hydroponics Monitoring System</p></div></div><span class="online"><i></i>Online</span></header>
      <section class="page-title"><h2>Plant Monitoring</h2><p>Mock data - backend not connected</p></section>
      <section class="camera-placeholder" aria-label="Latest camera frame unavailable"><span aria-hidden="true">▧</span><h2>Camera frame unavailable</h2><p>Connect the Raspberry Pi backend to show the latest detection frame.</p></section>
      <section class="plant-panel"><div class="panel-head"><span class="big-icon">♧</span><div><p class="eyebrow">PLANT CONDITION</p><h2>Vision analysis</h2></div></div><div class="plant-result"><div><span class="status good"><b aria-hidden="true">✓</b>Healthy</span><strong>Healthy</strong></div><div class="confidence"><span>Vision confidence</span><strong>${data.plant.confidence}</strong></div></div></section>
      <section class="plant-panel"><div class="panel-head"><span class="big-icon">◌</span><div><p class="eyebrow">PEST STATUS</p><h2>Presence detection only</h2></div></div><div class="notice good"><b aria-hidden="true">✓</b>No pests detected</div></section>
      <section class="plant-panel"><div class="panel-head"><span class="big-icon">◉</span><div><p class="eyebrow">SENSOR-VISION FUSION</p><h2>Reliability indicator</h2></div></div><div class="fusion-result"><strong>${data.fusion.confidence.toUpperCase()}</strong><p>${data.fusion.reason}</p></div></section>
      ${renderNav()}</div>`;
    bindNav(); return;
  }
  if (activePage === "History") {
    app.innerHTML = `<div class="app-shell"><header class="topbar"><div class="brand"><img src="icons/icon.svg" alt="" /><div><h1>VERDE</h1><p>Hydroponics Monitoring System</p></div></div><span class="online"><i></i>Online</span></header><section class="page-title"><h2>History</h2><p>Mock data - backend not connected</p></section><div class="filter-row" role="group" aria-label="History range"><button class="selected">Today</button><button>24 Hours</button><button>7 Days</button></div><section class="chart-card"><div><h2>pH trend</h2><p>Nutrient solution pH over time</p></div><svg viewBox="0 0 320 150" role="img" aria-label="Mock pH trend line"><path d="M20 125H305M20 90H305M20 55H305M20 20H305" stroke="#dbe6dd" stroke-dasharray="3"/><path d="M20 103L76 87L133 62L190 73L247 94L304 101" fill="none" stroke="#27813e" stroke-width="4"/><g fill="#27813e"><circle cx="20" cy="103" r="5"/><circle cx="76" cy="87" r="5"/><circle cx="133" cy="62" r="5"/><circle cx="190" cy="73" r="5"/><circle cx="247" cy="94" r="5"/><circle cx="304" cy="101" r="5"/></g></svg><div class="chart-labels"><span>12 AM</span><span>8 AM</span><span>4 PM</span><span>Now</span></div></section><section class="stat-row"><div><strong>5.9</strong><span>Current</span></div><div><strong>6.5</strong><span>Maximum</span></div><div><strong>6.2</strong><span>Average</span></div></section>${renderNav()}</div>`; bindNav(); return;
  }
  if (activePage === "Alerts") {
    app.innerHTML = `<div class="app-shell"><header class="topbar"><div class="brand"><img src="icons/icon.svg" alt="" /><div><h1>VERDE</h1><p>Hydroponics Monitoring System</p></div></div><span class="online"><i></i>Online</span></header><section class="page-title"><h2>Alerts</h2><p>Mock data - backend not connected</p></section><section class="alert-list"><article class="alert-item good"><span>✓</span><div><h2>No active critical alerts</h2><p>The future backend will supply live system alerts here.</p></div></article><article class="alert-item"><span>◉</span><div><h2>Plant check completed</h2><p>Healthy condition and no pest presence detected.</p><time>Mock event · just now</time></div></article><article class="alert-item"><span>◈</span><div><h2>Water quality optimal</h2><p>All four classifier inputs are within range.</p><time>Mock event · 5 minutes ago</time></div></article></section>${renderNav()}</div>`; bindNav(); return;
  }
  if (activePage === "Settings") {
    app.innerHTML = `<div class="app-shell"><header class="topbar"><div class="brand"><img src="icons/icon.svg" alt="" /><div><h1>VERDE</h1><p>Hydroponics Monitoring System</p></div></div><span class="online"><i></i>Online</span></header><section class="page-title"><h2>Settings</h2><p>Connection remains disabled in this prototype.</p></section><section class="settings-list"><article><div><h2>Backend connection</h2><p>Configure the Raspberry Pi API only after it exists.</p></div><span>Not connected</span></article><article><div><h2>Operating mode</h2><p>Mode changes require backend safety validation.</p></div><button id="settings-mode" class="secondary">View mode</button></article><article><div><h2>Application version</h2><p>VERDE PWA mock interface</p></div><span>v0.1</span></article></section>${renderNav()}</div>`; document.querySelector("#settings-mode").addEventListener("click",()=>showModal("Backend safety required","A live backend must validate Critical, Faulty Sensor, and Faulty Vision safeguards before changing modes.","Close",async()=>{})); bindNav(); return;
  }
  if (activePage !== "Dashboard") {
    app.innerHTML = `<div class="app-shell"><header class="topbar"><div class="brand"><img src="icons/icon.svg" alt="" /><div><h1>VERDE</h1><p>Hydroponics Monitoring System</p></div></div><span class="online"><i></i>Online</span></header><section class="empty-state"><span aria-hidden="true">◌</span><h2>${activePage} is next</h2><p>This screen will use mock data until the VERDE Raspberry Pi backend is ready. It is not connected to any hardware.</p></section>${renderNav()}</div>`;
    bindNav(); return;
  }
  app.innerHTML = `<div class="app-shell">
    <header class="topbar"><div class="brand"><img src="icons/icon.svg" alt="" /><div><h1>VERDE</h1><p>Hydroponics Monitoring System</p></div></div><span class="online"><i></i>${data.online ? "Online" : "Offline"}</span></header>
    <section class="overview" aria-label="System overview"><div><span class="meta">CURRENT TIME</span><strong>${time}</strong></div><button id="mode-button" class="mode"><span>⚙</span><div><span class="meta">OPERATING MODE</span><strong>${data.mode}</strong></div></button></section>
    <section class="section-heading"><div><h2>Live readings</h2><p>Mock data - backend not connected</p></div><time>Updated ${time}</time></section>
    <section class="sensor-grid" aria-label="Sensor readings">${data.sensors.map(renderCard).join("")}</section>
    <section class="insight-list" aria-label="System insights">
      <article class="insight water"><span class="big-icon">◈</span><div><p class="eyebrow">WATER QUALITY</p><h2>${data.waterQuality}</h2><p>All four classifier inputs are within their ideal ranges.</p></div><span class="arrow" aria-hidden="true">›</span></article>
      <article class="insight"><span class="big-icon">♧</span><div><p class="eyebrow">PLANT MONITORING</p><h2>${data.plant.condition}</h2><p>${data.plant.pest ? "Pest detected" : "No pests detected"} · Vision ${data.plant.confidence}</p></div><span class="arrow" aria-hidden="true">›</span></article>
      <article class="insight"><span class="big-icon">◉</span><div><p class="eyebrow">SENSOR-VISION FUSION</p><h2>${data.fusion.confidence} confidence</h2><p>${data.fusion.reason}</p></div><span class="arrow" aria-hidden="true">›</span></article>
    </section>
    ${renderNav()}
  </div>`;
  document.querySelector("#mode-button").addEventListener("click", () => showModal("Switch operating mode?", "The future Raspberry Pi backend must confirm that no Critical, Faulty Sensor, or Faulty Vision safety override is active.", "Request change", async () => {
    const button = document.querySelector("#mode-button"); button.disabled = true;
    await api.requestModeChange(data.mode === "Full Automation" ? "Semi-Automation" : "Full Automation"); button.disabled = false;
  }));
  bindNav();
}

if ("serviceWorker" in navigator) window.addEventListener("load", () => navigator.serviceWorker.register("./service-worker.js"));
render();
