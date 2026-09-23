import { MockVerdeApi } from "./services/verde-api.js";

const api = new MockVerdeApi();
const app = document.querySelector("#app");
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

function showModal(title, text, confirmText, onConfirm) {
  const dialog = document.createElement("dialog");
  dialog.innerHTML = `<form method="dialog"><h2>${title}</h2><p>${text}</p><div class="dialog-actions"><button value="cancel" class="secondary">Cancel</button><button value="confirm" class="primary">${confirmText}</button></div></form>`;
  dialog.addEventListener("close", async () => { if (dialog.returnValue === "confirm") await onConfirm(); dialog.remove(); });
  document.body.append(dialog); dialog.showModal();
}

async function render() {
  const data = await api.getSnapshot();
  const time = niceTime(data.updatedAt);
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
    <nav aria-label="Main navigation">${["Dashboard", "Plants", "History", "Alerts", "Settings"].map((item, index) => `<button class="nav-item ${index === 0 ? "active" : ""}" type="button" aria-current="${index === 0 ? "page" : "false"}"><span aria-hidden="true">${icon(item)}</span>${item}</button>`).join("")}</nav>
  </div>`;
  document.querySelector("#mode-button").addEventListener("click", () => showModal("Switch operating mode?", "The future Raspberry Pi backend must confirm that no Critical, Faulty Sensor, or Faulty Vision safety override is active.", "Request change", async () => {
    const button = document.querySelector("#mode-button"); button.disabled = true;
    await api.requestModeChange(data.mode === "Full Automation" ? "Semi-Automation" : "Full Automation"); button.disabled = false;
  }));
}

if ("serviceWorker" in navigator) window.addEventListener("load", () => navigator.serviceWorker.register("./service-worker.js"));
render();
