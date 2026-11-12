import { MockVerdeApi, VerdeApi, markSnapshotStale } from "./services/verde-api.js?v=77";
import { PAGES, buildChartGeometry, escapeHtml, formatHistoryValue, harvestReadiness, niceTime, normalizePage, safeResourceUrl, statusClass } from "./verde-ui.js?v=77";

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
const ALERT_FILTERS = ["All", "Active", "Acknowledged", "Resolved", "System"];
let activePage = pageFromHash();
let historyRange = "Today";
let historyMetric = null;
let alertFilter = "All";
let renderSequence = 0;
let renderedPage = null;
let lastSnapshot = null;
let deferredInstallPrompt = null;
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
    return `<aside class="connection-banner offline-banner" role="status"><div><b>Stale data</b><span>${safe(data.staleReason || "The backend is unavailable. Values may no longer be current.")}</span></div><button type="button" data-retry-connection>Try now</button></aside>`;
  }
  if (!navigator.onLine) {
    return `<aside class="connection-banner offline-banner" role="status"><div><b>Offline</b><span>${data?.isMock ? "Showing mock development data." : "Showing the last successful response when available."}</span></div><button type="button" data-retry-connection>Retry</button></aside>`;
  }
  if (!data.online) {
    return `<aside class="connection-banner offline-banner" role="status"><div><b>${data?.isMock ? "Mock adapter offline" : "Backend unavailable"}</b><span>${data?.isMock ? "Data is available for interface testing only." : "Live readings could not be refreshed."}</span></div><button type="button" data-retry-connection>Retry</button></aside>`;
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
  const showDetail = sensor.detail && sensor.status !== "Recovering"
    && !["Turbidity", "Water Temperature", "Humidity"].includes(sensor.label);
  return `<article class="sensor-card">
    <span class="sensor-icon" aria-hidden="true">${safe(sensor.icon)}</span>
    <div><h2>${safe(sensor.label)}</h2><p class="reading">${safe(sensor.value)}<small>${safe(sensor.unit)}</small></p>
    <span class="status ${tone}"><b aria-hidden="true">${marker}</b>${safe(sensor.status)}</span>
    ${showDetail ? `<p class="sensor-detail">${safe(sensor.detail)}</p>` : ""}</div>
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
  document.querySelector("[data-retry-connection]")?.addEventListener("click", () => render());
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
      : "The Raspberry Pi will check live sensors and safety rules before changing mode. If Full Automation becomes active, it can control the connected pumps.",
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

function bindDoseConfirmation(data) {
  const buttons = document.querySelectorAll("[data-confirm-dose]");
  if (!buttons.length) return;
  buttons.forEach((button) => button.addEventListener("click", () => {
    if (data.stale || !data.online) {
      showToast("Wait for fresh live readings before confirming a dose.", "warn");
      return;
    }
    showModal({
      title: `Confirm ${button.dataset.pumpLabel}?`,
      text: data.pumpAutomation?.manualDosingArmed || (data.pumpAutomation?.criticalManualDose && data.pumpAutomation?.circulationStopRequired)
        ? `Circulation is stopped. Verify the reservoir with a separate meter before confirming. The Pi will recheck the matching sensor, then run only ${button.dataset.pumpLabel} ${data.pumpAutomation?.criticalManualDose ? "for 4.5 seconds (estimated 3.69 mL)" : `using its saved volume (up to ${Number(data.pumpAutomation?.doseSettings?.max_pulse_ml || 3.69).toFixed(2)} mL)`}. Watch the outlet, mix the reservoir manually, and check with the separate meter before another dose. A new reading and another confirmation are required for any repeat.`
        : `The Pi will recheck the sensors, then run only ${button.dataset.pumpLabel} using its saved volume (up to ${Number(data.pumpAutomation?.doseSettings?.max_pulse_ml || 3.69).toFixed(2)} mL). Allow at least 1 minute of mixing before another dose.`,
      confirmText: "Confirm dose",
      onConfirm: async () => {
        button.disabled = true;
        try {
          const result = await withTimeout(api.confirmDose(button.dataset.pump), 45_000);
          showToast(result.detail || "One dose completed.");
          await render();
        } catch (error) {
          showToast(error?.message || "The dose was blocked.", "danger");
          await render();
        } finally {
          if (button.isConnected) button.disabled = false;
        }
      }
    });
  }));
}

function bindPumpDoseSettings(data) {
  document.querySelector("[data-pump-dose-settings]")?.addEventListener("click", () => {
    if (data.stale || !data.online || data.requestedMode !== "Semi-Automation") {
      showToast("Use fresh data and select Semi-Automation before changing pump volumes.", "warn");
      return;
    }
    const settings = data.pumpAutomation.doseSettings;
    const maximum = Number(settings.max_pulse_ml);
    const dialog = document.createElement("dialog");
    const labels = { pump1: "Pump 1 · nutrients", pump2: "Pump 2 · pH Up", pump3: "Pump 3 · pH Down" };
    dialog.innerHTML = `<form><h2>Dose volume per activation</h2>
      <p>Set each pump's requested dose. The Pi keeps the ${maximum.toFixed(2)} mL pulse limit and 1-minute mixing wait. There is no rolling 24-hour volume block. Saving does not activate a pump.</p>
      ${Object.entries(labels).map(([pump, label]) => `<label class="dose-field">${safe(label)} <input name="${pump}" type="number" inputmode="decimal" min="0.01" max="${maximum}" step="0.01" required value="${Number(settings.volumes_ml[pump]).toFixed(2)}" /> mL</label>`).join("")}
      <p class="dose-form-error" role="alert" hidden></p>
      <div class="dialog-actions"><button type="button" data-dose-cancel class="secondary">Cancel</button><button type="submit" class="primary">Save volumes</button></div></form>`;
    dialog.addEventListener("close", () => dialog.remove());
    dialog.querySelector("[data-dose-cancel]").addEventListener("click", () => dialog.close());
    dialog.querySelector("form").addEventListener("submit", async (event) => {
      event.preventDefault();
      const form = event.currentTarget;
      const volumes = Object.fromEntries(["pump1", "pump2", "pump3"].map((pump) => [pump, Number(form.elements[pump].value)]));
      const errorLine = form.querySelector(".dose-form-error");
      if (!Object.values(volumes).every((volume) => Number.isFinite(volume) && volume > 0 && volume <= maximum)) {
        errorLine.textContent = `Each volume must be above 0 and at most ${maximum.toFixed(2)} mL.`;
        errorLine.hidden = false;
        return;
      }
      form.querySelector('[type="submit"]').disabled = true;
      try {
        await withTimeout(api.updatePumpDoseSettings(volumes));
        dialog.close();
        showToast("Pump dose volumes saved. No pump was activated.");
        await render();
      } catch (error) {
        errorLine.textContent = error?.message || "Pump volumes could not be saved.";
        errorLine.hidden = false;
        form.querySelector('[type="submit"]').disabled = false;
      }
    });
    document.body.append(dialog);
    dialog.showModal();
  });
}

function isInstalledPwa() {
  return window.matchMedia?.("(display-mode: standalone)").matches === true;
}

async function requestPwaInstallation(button) {
  if (isInstalledPwa()) {
    showToast("VERDE is already installed on this device.");
    return;
  }
  if (!window.isSecureContext) {
    showToast("Open VERDE through its private HTTPS address before installing.", "warn");
    return;
  }
  if (!deferredInstallPrompt) {
    showToast("In Android Chrome, open the menu and choose Install app or Add to Home screen.", "warn");
    return;
  }
  button.disabled = true;
  try {
    await deferredInstallPrompt.prompt();
    const choice = await deferredInstallPrompt.userChoice;
    deferredInstallPrompt = null;
    showToast(choice.outcome === "accepted" ? "VERDE installation accepted." : "Installation was cancelled.",
      choice.outcome === "accepted" ? "good" : "warn");
  } catch {
    showToast("The browser could not open the installation prompt. Use Chrome's Install app menu instead.", "warn");
  } finally {
    if (button.isConnected) button.disabled = false;
  }
}

function bindInstallButton() {
  const button = document.querySelector("[data-install-button]");
  button?.addEventListener("click", () => requestPwaInstallation(button));
}

function showSmsSettingsDialog(settings) {
  const dialog = document.createElement("dialog");
  const current = settings.recipient_configured
    ? `Current recipient: ${safe(settings.recipient_masked || "number saved")}. Enter a new number to change it.`
    : "No recipient saved yet. Enter a mobile number.";
  dialog.innerHTML = `<form id="sms-settings-form">
    <h2>SMS alert destination</h2>
    <p>${current}</p>
    <label class="sms-field" for="sms-recipient">Mobile number</label>
    <input id="sms-recipient" name="recipient" type="tel" inputmode="tel" autocomplete="tel"
      pattern="[+]?[0-9]{7,15}" maxlength="16" placeholder="+639171234567" />
    <label class="sms-toggle"><input name="sms_enabled" type="checkbox"${settings.sms_enabled ? " checked" : ""} /> Enable SMS alerts for new qualifying events</label>
    <p class="sms-form-error" role="alert" hidden></p>
    <div class="dialog-actions"><button type="button" data-sms-cancel class="secondary">Cancel</button><button type="submit" class="primary">Save settings</button></div>
  </form>`;
  dialog.addEventListener("close", () => dialog.remove());
  dialog.querySelector("[data-sms-cancel]").addEventListener("click", () => dialog.close());
  dialog.querySelector("form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const form = event.currentTarget;
    const recipient = form.elements.recipient.value.trim();
    const smsEnabled = form.elements.sms_enabled.checked;
    const errorLine = form.querySelector(".sms-form-error");
    errorLine.hidden = true;
    if (smsEnabled && !recipient && !settings.recipient_configured) {
      errorLine.textContent = "Enter a mobile number before enabling SMS alerts.";
      errorLine.hidden = false;
      return;
    }
    const submit = form.querySelector('[type="submit"]');
    submit.disabled = true;
    try {
      await withTimeout(api.updateSmsSettings({ smsEnabled, ...(recipient ? { recipient } : {}) }));
      dialog.close();
      showToast("SMS settings saved. No test SMS was sent.");
      await render();
    } catch (error) {
      errorLine.textContent = error?.message || "SMS settings could not be saved.";
      errorLine.hidden = false;
    } finally {
      submit.disabled = false;
    }
  });
  document.body.append(dialog);
  dialog.showModal();
}

function bindSmsSettingsButton(settings, data) {
  document.querySelector("[data-sms-settings]")?.addEventListener("click", () => {
    if (data.stale || !data.online) {
      showToast("Reconnect to the backend before changing SMS settings.", "warn");
      return;
    }
    showSmsSettingsDialog(settings);
  });
}

function correctionGuidance(data) {
  if (!data.online || data.stale) return "";
  const recommendations = data.pumpAutomation?.recommendations ?? [];
  const choices = [
    ["pH-Up dosing", "pump2", "pH Up", "pH", "5.5–6.5"],
    ["pH-Down dosing", "pump3", "pH Down", "pH", "5.5–6.5"],
    ["EC nutrient dosing", "pump1", "Nutrients", "EC", "1.2–1.8 mS/cm"]
  ].filter(([recommendation]) => recommendations.includes(recommendation));
  const critical = data.sensors.some((sensor) => /critical/i.test(sensor.status))
    || /critical/i.test(data.waterQuality?.status ?? "");
  const sensorReading = (name) => {
    const sensor = data.sensors.find((item) => item.label === name);
    const value = Number(sensor?.value);
    return sensor && Number.isFinite(value) && !["Recovering", "Faulty Sensors", "Stale"].includes(sensor.status)
      ? `${sensor.value}${sensor.unit ? ` ${sensor.unit}` : ""}` : "Unavailable";
  };
  const actions = choices.map(([, pump, label, sensor, target]) => `<li><strong>${critical ? "Manual correction requested: " : ""}Pump ${pump.slice(-1)} · ${safe(label)}</strong><span>Current ${safe(sensor)}: ${safe(sensorReading(sensor))} · Optimal ${safe(target)}</span></li>`).join("");
  const highEc = recommendations.includes("High EC: manual inspection; correction procedure pending")
    ? "<li><strong>High EC · manual inspection</strong><span>No automatic correction pump is configured for high EC.</span></li>" : "";
  const canConfirm = data.pumpAutomation?.confirmationAvailable === true;
  const buttons = canConfirm ? `<div class="dose-choice-list">${choices.map(([, pump, label]) => `<button data-confirm-dose data-pump="${pump}" data-pump-label="${safe(label)}" type="button" class="primary">${critical ? "Manually dose" : "Confirm"} ${safe(label)}</button>`).join("")}</div>` : "";
  const manualRequest = critical ? `<p class="correction-request"><strong>Manual correction required for Critical readings.</strong> ${choices.length ? "The pumps named below indicate which solution is needed. Correct one condition at a time under supervision and remeasure after mixing." : "No dosing pump is recommended from the available readings; inspect the Critical condition."}</p>` : "";
  return `<section class="correction-plan" aria-label="Live correction guidance"><header><p class="eyebrow">LIVE CORRECTION GUIDANCE</p><a href="#History">View pump dosing history</a></header>
    ${manualRequest}
    ${actions || highEc ? `<ul>${actions}${highEc}</ul>` : `<p>No pH or EC pump correction is recommended from these readings.</p>`}
    ${buttons}</section>`;
}

function renderDashboard(data) {
  const time = niceTime(data.updatedAt);
  const content = `<section class="overview" aria-label="System overview">
      <div><span class="meta">LAST SAMPLE</span><strong>${safe(time)}</strong></div>
      <button data-mode-button class="mode" type="button"><span aria-hidden="true">⚙</span><div><span class="meta">ACTIVE MODE</span><strong>${safe(data.mode)}</strong><small>Requested: ${safe(data.requestedMode || data.mode)}</small></div></button>
    </section>
    ${data.modeOverride ? `<aside class="safety-note" role="status"><b>Safety override active</b><span>${safe(data.modeOverride)}</span></aside>` : ""}
    ${correctionGuidance(data)}
    <section class="section-heading"><div><h2>Live readings</h2><p>${safe(sourceLabel(data))}</p></div><time datetime="${safe(data.updatedAt)}">Updated ${safe(time)}</time></section>
    <section class="sensor-grid" aria-label="Sensor readings">${data.sensors.map(renderCard).join("")}</section>
    <section class="insight-list" aria-label="System insights">
      <article class="insight water"><span class="big-icon" aria-hidden="true">◈</span><div><p class="eyebrow">WATER QUALITY</p><h2>${safe(data.waterQuality.status)}</h2><p>${safe(data.waterQuality.summary)}</p></div></article>
    </section>`;
  app.innerHTML = renderShell(content, data);
  bindModeButton(data);
  bindDoseConfirmation(data);
  bindNav();
}

function plantAge(slot) {
  return slot?.daysGrowing === null || slot?.daysGrowing === undefined
    ? "Set date" : `${slot.daysGrowing} day${slot.daysGrowing === 1 ? "" : "s"}`;
}

function plantSlotRow(slots, first, overlay = false) {
  return `<div class="nft-slot-row${overlay ? " overlay-row" : ""}">${Array.from({ length: 3 }, (_, index) => first + index).map((number) => {
    const slot = slots?.supported ? slots.slots[number - 1] : null;
    return `<button type="button" class="nft-slot${slot?.plantedOn ? " planted" : ""}" data-plant-slot="${number}" aria-label="Plant ${number}, ${safe(plantAge(slot))}" ${slots?.supported ? "" : "disabled"}><strong>P${number}</strong><small>${safe(plantAge(slot))}</small></button>`;
  }).join("")}</div>`;
}

function plantFusionRow(rows, first) {
  return `<div class="nft-fusion-row">${Array.from({ length: 3 }, (_, index) => first + index).map((number) => {
    const item = rows[number - 1];
    const confidence = item.confidence ?? (item.status === "NO DETECTION" ? "No detection" : "Unavailable");
    const tone = item.confidence === "High" ? "good" : item.confidence === "Medium" ? "warn"
      : item.confidence === "Low" ? "danger" : "inactive";
    return `<article class="nft-fusion-card ${tone}" aria-label="Plant ${number}: ${safe(confidence)} fusion confidence"><strong>P${number}</strong><span>${safe(item.plantCondition ?? "No plant classified")}</span><b>${safe(confidence)}</b><small>${safe(item.sensorStatus ?? "Water status unavailable")}</small></article>`;
  }).join("")}</div>`;
}

function harvestRow(rows, first) {
  return `<div class="nft-fusion-row nft-harvest-row">${rows.slice(first - 1, first + 2).map((item) =>
    `<article class="nft-fusion-card ${item.tone}" aria-label="Plant ${item.slot}: ${safe(item.status)}"><strong>P${item.slot}</strong><b>${safe(item.status)}</b><small>${safe(item.detail)}</small></article>`
  ).join("")}</div>`;
}

function showPlantSlotDialog(slot, slots) {
  const dialog = document.createElement("dialog");
  dialog.innerHTML = `<form id="plant-slot-form"><h2>Plant ${slot.slot}</h2>
    <p>This date belongs to the plant in NFT slot ${slot.slot}. Update it when you plant or move lettuce.</p>
    <label for="plant-date">Date planted</label><input id="plant-date" name="planted_on" type="date" required max="${safe(slots.asOf || "")}" value="${safe(slot.plantedOn || "")}" />
    <label for="plant-swap">Swap with another slot</label><select id="plant-swap" name="swap"><option value="">Choose a slot</option>${slots.slots.filter((item) => item.slot !== slot.slot).map((item) => `<option value="${item.slot}">Plant ${item.slot} · ${safe(plantAge(item))}</option>`).join("")}</select>
    <p class="plant-slot-error" role="alert" hidden></p>
    <div class="dialog-actions"><button type="button" class="secondary" data-plant-cancel>Cancel</button><button type="button" class="secondary" data-plant-clear ${slot.plantedOn ? "" : "disabled"}>Erase date</button><button type="button" class="secondary" data-plant-swap>Swap dates</button><button type="submit" class="primary">Save date</button></div></form>`;
  const form = dialog.querySelector("form");
  const errorLine = form.querySelector(".plant-slot-error");
  const save = async (change, message) => {
    form.querySelectorAll("button").forEach((button) => { button.disabled = true; });
    errorLine.hidden = true;
    try {
      const updated = await withTimeout(api.updatePlantSlots(change));
      lastPageData.set("Plants", updated);
      dialog.close();
      await render();
      showToast(message);
    } catch (error) {
      errorLine.textContent = error?.message || "Could not save the planting record.";
      errorLine.hidden = false;
      form.querySelectorAll("button").forEach((button) => { button.disabled = false; });
      form.querySelector("[data-plant-clear]").disabled = !slot.plantedOn;
    }
  };
  form.addEventListener("submit", (event) => {
    event.preventDefault();
    save({ operation: "set", slot: slot.slot, planted_on: form.elements.planted_on.value }, `Plant ${slot.slot} date saved.`);
  });
  form.querySelector("[data-plant-clear]").addEventListener("click", () => {
    if (window.confirm(`Erase the planting date for Plant ${slot.slot}?`)) save({ operation: "clear", slot: slot.slot }, `Plant ${slot.slot} date erased.`);
  });
  form.querySelector("[data-plant-swap]").addEventListener("click", () => {
    const second = Number(form.elements.swap.value);
    if (!Number.isInteger(second) || second < 1 || second > 6 || second === slot.slot) {
      errorLine.textContent = "Choose another slot to swap with.";
      errorLine.hidden = false;
      return;
    }
    if (window.confirm(`Swap saved dates for Plant ${slot.slot} and Plant ${second}? Move the physical plants to match.`)) save({ operation: "swap", first: slot.slot, second }, "Planting dates swapped.");
  });
  form.querySelector("[data-plant-cancel]").addEventListener("click", () => dialog.close());
  dialog.addEventListener("close", () => dialog.remove());
  document.body.append(dialog);
  dialog.showModal();
}

function renderPlants(data, slots = null) {
  const readiness = harvestReadiness(slots, data.fusionBySlot, data.online && !data.stale);
  const readyCount = readiness.filter((item) => item.status === "Harvest-Ready").length;
  const readinessSummary = data.online && !data.stale && slots?.supported && !slots.error && data.fusionBySlot
    ? `${readyCount} of 6 Harvest-Ready` : "Waiting for current planting and vision data";
  const frameUrl = safeResourceUrl(data.plant.frameUrl, window.location.href);
  const camera = frameUrl
    ? `<figure class="camera-frame"><div class="nft-camera"><img src="${safe(frameUrl)}" alt="${data.plant.aiAnnotated ? "Latest AI-annotated plant detection frame" : "Latest camera frame"}" /><div class="nft-camera-labels"><div class="nft-camera-row top">${plantSlotRow(slots, 1, true)}</div><div class="nft-camera-row bottom">${plantSlotRow(slots, 4, true)}</div></div></div></figure>`
    : `<section class="camera-placeholder" aria-label="Latest camera frame unavailable"><span aria-hidden="true">▧</span><h2>${data.plant.cameraStatus === "Faulty Camera" ? "Faulty Camera" : "Camera frame unavailable"}</h2><p>${safe(data.plant.cameraStatus || "No camera capture is available.")}</p></section>`;
  const pestKnown = typeof data.plant.pestDetected === "boolean";
  const pestSection = data.stale ? null : data.plant.pestSection;
  const pestDisplay = pestSection || { detected: null, status: "Pest analysis unavailable", detail: "No recent verified camera pest result.", confidence: null, frameUrl: null };
  const pestFrameUrl = safeResourceUrl(pestDisplay.frameUrl, window.location.href);
  const pestBoxes = pestDisplay.boxes ?? [];
  const pestSize = pestDisplay.imageSize;
  const pestOverlay = pestSize && pestBoxes.length
    ? `<svg class="pest-overlay" viewBox="0 0 ${pestSize[0]} ${pestSize[1]}" aria-label="${pestBoxes.length} pest annotations">${pestBoxes.map((item) => {
      const [x1, y1, x2, y2] = item.box_xyxy;
      const labelY = y1 < 56 ? y1 + 64 : y1 - 12;
      return `<rect x="${x1}" y="${y1}" width="${x2 - x1}" height="${y2 - y1}" /><text x="${x1}" y="${labelY}">Pest ${Math.round(item.confidence * 100)}%</text>`;
    }).join("")}</svg>` : "";
  const classificationCards = (data.plant.classifications ?? []).map((classification) => {
    const detected = Number.isInteger(classification.count) && classification.count > 0;
    const tone = classification.label === "Wilting" ? "danger"
      : classification.label === "Yellowing" ? "warn" : "good";
    const count = classification.count === null
      ? "Unavailable"
      : `${classification.count} plant${classification.count === 1 ? "" : "s"}`;
    const confidence = classification.confidence ? `${classification.confidence} max confidence` : "No qualifying result";
    return `<article class="classification-card ${detected ? tone : "inactive"}"><span>${safe(classification.label)}</span><strong>${safe(count)}</strong><small>${safe(confidence)}</small></article>`;
  }).join("");
  const content = `<section class="page-title"><h2>Plant Monitoring</h2><p>${safe(sourceLabel(data))}</p></section>
    ${camera}
    <section class="plant-panel nft-panel"><div class="panel-head"><span class="big-icon" aria-hidden="true">▦</span><div><p class="eyebrow">NFT PLANTING RECORDS</p><h2>6 fixed plant slots</h2></div></div>${slots?.supported ? `<div class="nft-rows" aria-label="Plant slots"><span>Top NFT row</span>${plantSlotRow(slots, 1)}<span>Bottom NFT row</span>${plantSlotRow(slots, 4)}</div>${data.stale || !data.online || slots.error ? `<p role="status">${safe(slots.error || "Planting records may be stale. Reconnect before editing.")}</p>` : ""}` : `<p role="status">Planting records are unavailable until the Pi backend is updated.</p>`}</section>
    <section class="plant-panel"><div class="panel-head"><span class="big-icon" aria-hidden="true">♧</span><div><p class="eyebrow">PLANT CONDITION</p><h2>Vision analysis</h2></div></div><div class="classification-grid" aria-label="Latest per-class plant analysis">${classificationCards}</div></section>
    <section class="plant-panel"><div class="panel-head"><span class="big-icon" aria-hidden="true">◌</span><div><p class="eyebrow">PEST DETECTION</p><h2>Printed insect props</h2></div></div><div class="notice ${pestDisplay.detected === null ? "warn" : pestDisplay.detected ? "danger" : "good"}"><b aria-hidden="true">${pestDisplay.detected === false ? "✓" : "!"}</b><div><strong>${safe(pestDisplay.status)}</strong><small>${safe(pestDisplay.detail)}${pestDisplay.confidence ? ` · ${safe(pestDisplay.confidence)}` : ""}</small></div></div>${pestFrameUrl ? `<figure class="camera-frame"><div class="pest-camera"><img src="${safe(pestFrameUrl)}" alt="Camera photo with pest-only annotations when available" />${pestOverlay}</div></figure>` : ""}</section>
    <section class="plant-panel"><div class="panel-head"><span class="big-icon" aria-hidden="true">◉</span><div><p class="eyebrow">SENSOR-VISION FUSION</p><h2>By plant slot</h2></div></div>${data.fusionBySlot ? `<div class="nft-fusion" aria-label="Fusion confidence by NFT plant slot"><span>Top NFT row</span>${plantFusionRow(data.fusionBySlot, 1)}<span>Bottom NFT row</span>${plantFusionRow(data.fusionBySlot, 4)}</div>` : `<p class="classification-note" role="status">Per-plant fusion is unavailable.</p>`}</section>
    <section class="plant-panel"><div class="panel-head"><span class="big-icon" aria-hidden="true">♧</span><div><p class="eyebrow">HARVEST READINESS</p><h2>Healthy plants at 30+ days</h2></div></div><div class="nft-fusion" aria-label="Harvest readiness by NFT plant slot"><strong class="harvest-summary">${safe(readinessSummary)}</strong><span>Top NFT row</span>${harvestRow(readiness, 1)}<span>Bottom NFT row</span>${harvestRow(readiness, 4)}</div></section>`;
  app.innerHTML = renderShell(content, data);
  document.querySelectorAll("[data-plant-slot]").forEach((button) => button.addEventListener("click", () => {
    if (data.stale || !data.online || slots?.error) {
      showToast("Reconnect before editing planting records.", "warn");
      return;
    }
    showPlantSlotDialog(slots.slots[Number(button.dataset.plantSlot) - 1], slots);
  }));
  bindNav();
}

function renderHistory(data, history) {
  historyMetric = history.metricKey;
  const chart = buildChartGeometry(history.values);
  const circles = chart.points.map((point) => `<circle cx="${point.x}" cy="${point.y}" r="5" />`).join("");
  const area = chart.points.length
    ? `M${chart.points[0].x} 125 ${chart.points.map((point) => `L${point.x} ${point.y}`).join(" ")} L${chart.points.at(-1).x} 125 Z`
    : "";
  const unit = history.unit ? ` ${history.unit}` : "";
  const valueWithUnit = (value) => {
    const formatted = formatHistoryValue(value);
    return formatted === "—" ? formatted : `${formatted}${unit}`;
  };
  const metricButtons = history.metrics.map((metric) => `<button type="button" data-history-metric="${safe(metric.key)}" class="metric-chip ${metric.key === history.metricKey ? "selected" : ""}" aria-pressed="${metric.key === history.metricKey}"><span>${safe(metric.label)}</span><small>${metric.sampleCount} sample${metric.sampleCount === 1 ? "" : "s"}</small></button>`).join("");
  const recent = history.samples.slice(-6).reverse().map((sample) => `<li><time datetime="${safe(sample.timestamp)}">${safe(sample.label)}</time><strong>${safe(valueWithUnit(sample.value))}</strong></li>`).join("");
  const incidentState = (incident) => incident.state === "RESOLVED" ? "Resolved" : incident.state === "ACKNOWLEDGED" ? "Acknowledged" : "Problem detected";
  const incidents = history.incidents.map((incident) => `<li class="incident-item ${incident.tone}"><span class="incident-marker" aria-hidden="true">${incident.state === "RESOLVED" ? "✓" : incident.state === "ACKNOWLEDGED" ? "◎" : "!"}</span><div><div class="incident-title-row"><strong>${safe(incident.title)}</strong><span>${incidentState(incident)}</span></div><p>${safe(incident.message)}</p><time datetime="${safe(incident.createdAt)}">${safe(niceTime(incident.createdAt))} · ${safe(relativeAlertTime(incident.createdAt))}</time></div></li>`).join("");
  const pumpLabel = { pump1: "Pump 1 · nutrients", pump2: "Pump 2 · pH Up", pump3: "Pump 3 · pH Down" };
  const pumpDoses = (history.pumpDoses ?? []).slice().reverse().map((dose) => `<li class="pump-dose-item"><div><strong>${safe(pumpLabel[dose.pump] ?? dose.pump)}</strong><span>${safe(String(dose.action ?? "dose").replaceAll("_", " "))} · ${safe(dose.mode ?? "Mode unavailable")}${dose.requestedSeconds === null ? "" : ` · requested ${safe(formatHistoryValue(dose.requestedSeconds))} s`}</span></div><b>${dose.estimatedMl === null ? "Volume unavailable" : `Est. ${safe(formatHistoryValue(dose.estimatedMl))} mL`}</b><time datetime="${safe(dose.timestamp)}">${safe(dose.label)} · ${safe(relativeAlertTime(dose.timestamp))}</time></li>`).join("");
  const content = `<section class="page-title"><h2>History</h2><p>${safe(sourceLabel(data))}</p></section>
    <div class="filter-row" role="group" aria-label="History range">${HISTORY_RANGES.map((range) => `<button type="button" data-history-range="${range}" class="${range === history.range ? "selected" : ""}" aria-pressed="${range === history.range}">${range}</button>`).join("")}</div>
    <section class="metric-picker" aria-label="Sensor history metric">${metricButtons}</section>
    <section class="chart-card history-chart" style="--metric-color:${safe(history.color)}"><header class="chart-head"><div><p class="eyebrow">${safe(history.metricKey.replaceAll("_", " "))}</p><h2>${safe(history.title)}</h2><p>${safe(history.description)}</p></div><span class="sample-count">${history.sampleCount}<small>samples</small></span></header><svg viewBox="0 0 320 150" role="img" aria-label="${safe(history.description)}"><defs><linearGradient id="history-fill" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="var(--metric-color)" stop-opacity=".24"/><stop offset="1" stop-color="var(--metric-color)" stop-opacity="0"/></linearGradient></defs><path d="M20 125H304M20 90H304M20 55H304M20 20H304" stroke="#dbe6dd" stroke-dasharray="3"/>${area ? `<path d="${area}" fill="url(#history-fill)"/><path d="${chart.path}" fill="none" stroke="var(--metric-color)" stroke-width="4" stroke-linecap="round" stroke-linejoin="round"/><g fill="var(--surface)" stroke="var(--metric-color)" stroke-width="3">${circles}</g>` : ""}</svg>${history.values.length ? `<div class="chart-labels"><span>${safe(history.labels[0])}</span><span>${safe(history.labels[Math.floor(history.labels.length / 2)])}</span><span>${safe(history.labels.at(-1))}</span></div>` : `<div class="no-chart-data"><strong>No ${safe(history.title.toLowerCase())} data yet</strong><span>This sensor has no calibrated samples in the selected range.</span></div>`}</section>
    <section class="history-stats" aria-label="${safe(history.title)} summary"><article><span>Current</span><strong>${safe(valueWithUnit(history.current))}</strong></article><article><span>Average</span><strong>${safe(valueWithUnit(history.average))}</strong></article><article><span>Range</span><strong>${safe(valueWithUnit(history.minimum))} – ${safe(valueWithUnit(history.maximum))}</strong></article></section>
    <section class="recent-readings"><header><div><h2>Recent readings</h2><p>Newest valid samples in this range</p></div><span>${safe(history.unit || "Value")}</span></header>${recent ? `<ol>${recent}</ol>` : `<div class="empty-inline"><strong>No readings available</strong><span>Values will appear after the backend records valid measurements.</span></div>`}</section>
    <section class="incident-timeline"><header><div><h2>Problem timeline</h2><p>Detected problems and recorded recoveries</p></div><span>${history.incidents.length} event${history.incidents.length === 1 ? "" : "s"}</span></header>${incidents ? `<ol>${incidents}</ol>` : `<div class="empty-inline"><strong>No problem transitions in this range</strong><span>Sensor, vision, fusion, and system incidents will appear when they are detected or resolved.</span></div>`}</section>
    <section class="incident-timeline pump-history"><header><div><h2>Pump dosing history</h2><p>Last 7 days · Pump 1 nutrients, Pump 2 pH Up, Pump 3 pH Down</p></div><span>${history.pumpDoses?.length ?? 0} dose${(history.pumpDoses?.length ?? 0) === 1 ? "" : "s"}</span></header>${pumpDoses ? `<ol>${pumpDoses}</ol>` : `<div class="empty-inline"><strong>No recorded pump doses in the last 7 days</strong><span>Only doses recorded by the automatic gateway appear here; manual hardware tests are not logged as app doses.</span></div>`}</section>`;
  app.innerHTML = renderShell(content, data);
  app.querySelector(".page-title")?.after(app.querySelector(".pump-history"));
  document.querySelectorAll("[data-history-range]").forEach((button) => button.addEventListener("click", () => {
    historyRange = HISTORY_RANGES.includes(button.dataset.historyRange) ? button.dataset.historyRange : "Today";
    render();
  }));
  document.querySelectorAll("[data-history-metric]").forEach((button) => button.addEventListener("click", () => {
    historyMetric = button.dataset.historyMetric;
    render();
  }));
  bindNav();
}

function relativeAlertTime(iso) {
  const timestamp = new Date(iso).getTime();
  if (!Number.isFinite(timestamp)) return "Time unavailable";
  const minutes = Math.max(0, Math.round((Date.now() - timestamp) / 60_000));
  if (minutes === 0) return "Just now";
  if (minutes >= 1_440) return `${Math.floor(minutes / 1_440)}d ago`;
  if (minutes >= 60) return `${Math.floor(minutes / 60)}h ago`;
  return `${minutes} minute${minutes === 1 ? "" : "s"} ago`;
}

function renderAlerts(data, alerts) {
  const activeIncidents = new Map((data.incidents || []).map((incident) => [incident.issueKey, incident]));
  const loggedIssueKeys = new Set(alerts.map((alert) => alert.issueKey).filter(Boolean));
  const currentOnly = (data.incidents || []).filter((incident) => !loggedIssueKeys.has(incident.issueKey)).map((incident) => ({
    id: `current-${incident.issueKey}`,
    category: "current_incident",
    state: incident.state,
    source: incident.source,
    issueKey: incident.issueKey,
    tone: incident.severity === "notice" ? "info" : incident.severity === "critical" ? "danger" : "warn",
    icon: incident.severity === "notice" ? "◉" : incident.state === "ACKNOWLEDGED" ? "◎" : incident.severity === "critical" ? "!" : "△",
    title: incident.severity === "notice" ? "Harvest notification" : `${incident.source.replace(/\b\w/g, (letter) => letter.toUpperCase())} ${incident.state === "ACKNOWLEDGED" ? "acknowledged" : "problem"}`,
    message: incident.message,
    createdAt: incident.acknowledgedAt || incident.openedAt || data.updatedAt
  }));
  const alertRows = [...currentOnly, ...alerts];
  const counts = {
    Active: (data.incidents || []).filter((incident) => incident.state === "OPEN").length,
    Acknowledged: (data.incidents || []).filter((incident) => incident.state === "ACKNOWLEDGED").length,
    Resolved: alertRows.filter((alert) => alert.state === "RESOLVED").length
  };
  const filtered = alertRows.filter((alert) => alertFilter === "All"
    || (alertFilter === "Active" && alert.state === "OPEN" && activeIncidents.get(alert.issueKey)?.state === "OPEN")
    || (alertFilter === "Acknowledged" && alert.state === "ACKNOWLEDGED")
    || (alertFilter === "Resolved" && alert.state === "RESOLVED")
    || (alertFilter === "System" && !alert.state));
  const items = filtered.map((alert) => {
    const tone = ["good", "warn", "danger"].includes(alert.tone) ? alert.tone : "info";
    const label = alert.state === "NOTICE" || alert.state === "NOTICE_ENDED" ? "Notification" : tone === "danger" ? "Critical" : tone === "warn" ? "Warning" : tone === "good" ? "Resolved" : "System";
    const active = alert.issueKey ? activeIncidents.get(alert.issueKey) : null;
    const canAcknowledge = alert.state === "OPEN" && active?.state === "OPEN";
    return `<article class="alert-item ${tone}"><span class="alert-symbol" aria-hidden="true">${safe(alert.icon)}</span><div class="alert-copy"><div class="alert-title-row"><h2>${safe(alert.title)}</h2><span class="severity ${tone}">${label}</span></div><p>${safe(alert.message)}</p><div class="alert-meta"><time datetime="${safe(alert.createdAt)}">${safe(relativeAlertTime(alert.createdAt))}</time><span aria-hidden="true">•</span><time datetime="${safe(alert.createdAt)}">${safe(niceTime(alert.createdAt))}</time></div>${canAcknowledge ? `<button type="button" class="acknowledge-button" data-acknowledge-issue="${safe(alert.issueKey)}">Acknowledge</button>` : ""}</div></article>`;
  }).join("");
  const summary = `<section class="alert-summary" aria-label="Incident summary"><article class="danger"><span>Active</span><strong>${counts.Active}</strong></article><article class="warn"><span>Acknowledged</span><strong>${counts.Acknowledged}</strong></article><article class="good"><span>Resolved log</span><strong>${counts.Resolved}</strong></article></section>`;
  const filters = `<div class="filter-row alert-filters" role="group" aria-label="Filter alerts">${ALERT_FILTERS.map((filter) => `<button type="button" data-alert-filter="${filter}" class="${filter === alertFilter ? "selected" : ""}" aria-pressed="${filter === alertFilter}">${filter}</button>`).join("")}</div>`;
  const empty = `<article class="empty-list"><span aria-hidden="true">✓</span><div><h2>${alertRows.length ? `No ${safe(alertFilter.toLowerCase())} events` : "No events recorded"}</h2><p>${alertRows.length ? "Choose another filter to review the remaining system activity." : "New warnings, faults, recoveries, and system activity will appear here."}</p></div></article>`;
  const content = `<section class="page-title page-title-split"><div><h2>Alerts & activity</h2><p>${safe(sourceLabel(data))}</p></div><span class="read-only-label">Incident audit trail</span></section>${summary}${filters}<section class="alert-list" aria-live="polite">${items || empty}</section>`;
  app.innerHTML = renderShell(content, data);
  document.querySelectorAll("[data-alert-filter]").forEach((button) => button.addEventListener("click", () => {
    alertFilter = ALERT_FILTERS.includes(button.dataset.alertFilter) ? button.dataset.alertFilter : "All";
    renderAlerts(data, alerts);
  }));
  document.querySelectorAll("[data-acknowledge-issue]").forEach((button) => button.addEventListener("click", () => {
    showModal({
      title: "Acknowledge this incident?",
      text: "This records that the farmer has seen the warning. It does not mark the problem resolved and does not operate pumps, relays, or pesticides.",
      confirmText: "Acknowledge",
      onConfirm: async () => {
        button.disabled = true;
        try {
          await withTimeout(api.acknowledgeIssue(button.dataset.acknowledgeIssue));
          showToast("Incident acknowledged. It will remain active until the condition recovers.");
          await render();
        } catch (error) {
          showToast(error?.message || "The incident could not be acknowledged.", "danger");
        }
      }
    });
  }));
  bindNav();
}

function renderSettings(data, smsSettings = { supported: false }) {
  const installed = isInstalledPwa();
  const installLabel = installed ? "Installed" : deferredInstallPrompt ? "Install app" : "Installation help";
  const smsSupported = smsSettings?.supported !== false && typeof smsSettings?.sms_enabled === "boolean";
  const smsSummary = smsSupported
    ? `${smsSettings.sms_enabled ? "Enabled" : "Disabled"} · ${smsSettings.recipient_configured ? `Recipient ${smsSettings.recipient_masked || "saved"}` : "No recipient saved"}`
    : "Backend SMS settings are unavailable. Update the Pi backend to configure alerts here.";
  const pumpSettings = data.pumpAutomation?.doseSettings;
  const pumpSummary = pumpSettings?.volumes_ml
    ? `Nutrients ${Number(pumpSettings.volumes_ml.pump1).toFixed(2)} mL · pH Up ${Number(pumpSettings.volumes_ml.pump2).toFixed(2)} mL · pH Down ${Number(pumpSettings.volumes_ml.pump3).toFixed(2)} mL per activation`
    : "Pump dose settings are unavailable from the Pi.";
  const content = `<section class="page-title"><h2>Settings</h2><p>${safe(sourceLabel(data))}</p></section>
    <section class="settings-list">
      <article><div><h2>Install on this device</h2><p>Installation requires the private HTTPS address. Live readings still require a connection to the Raspberry Pi.</p></div><button data-install-button type="button" class="secondary"${installed ? " disabled" : ""}>${installLabel}</button></article>
      <article><div><h2>Operating mode</h2><p>Active: ${safe(data.mode)} · Requested: ${safe(data.requestedMode || data.mode)}. Safety validation is enforced by the backend.</p></div><button data-mode-button type="button" class="secondary">Change mode</button></article>
      <article><div><h2>Pumps 1–3 dose volumes</h2><p>${safe(pumpSummary)}</p><p>Settings can be changed in Semi-Automation. Critical manual correction uses a fixed 4.5-second pulse (estimated 3.69 mL); other doses use the saved volumes. Saving does not run a pump.</p></div>${pumpSettings?.volumes_ml ? '<button data-pump-dose-settings type="button" class="secondary">Adjust volumes</button>' : ""}</article>
      <article><div><h2>GSM SMS alerts</h2><p>${safe(smsSummary)}</p><p>Mode: ${safe(data.settings.gsmStatus || "Unavailable")}</p></div>${smsSupported ? '<button data-sms-settings type="button" class="secondary">Configure</button>' : ""}</article>
      <article><div><h2>Application version</h2><p>VERDE monitoring PWA</p></div><span>${safe(data.settings.version)}</span></article>
    </section>`;
  app.innerHTML = renderShell(content, data);
  bindModeButton(data);
  bindPumpDoseSettings(data);
  bindInstallButton();
  if (smsSupported) bindSmsSettingsButton(smsSettings, data);
  bindNav();
}

function unavailableSnapshot(error) {
  const now = new Date().toISOString();
  const sensors = [
    ["pH", "◈"], ["EC", "⌁"], ["TDS", "⋮"],
    ["Water Temperature", "♨"], ["Turbidity", "≋"], ["Ambient Humidity", "◌"]
  ].map(([label, sensorIcon]) => ({
    label, icon: sensorIcon, value: "—", unit: "", status: "Faulty Sensors",
    detail: "Backend unavailable; no reading detected."
  }));
  return {
    online: false, isMock: false, unavailable: true,
    unavailableReason: error?.message || "The backend is unavailable.",
    mode: "Unavailable", requestedMode: "Unavailable", modeOverride: null,
    updatedAt: now, systemStatus: "BACKEND UNAVAILABLE", sensors,
    waterQuality: { status: "Unavailable", summary: "The backend is unavailable, so water quality cannot be evaluated." },
    plant: { condition: "Unavailable", status: "Faulty Camera", pestDetected: null,
      pestStatus: "Unavailable", pestDetail: "Pest analysis is unavailable.", confidence: "Unavailable", classifications: [], frameUrl: null,
      lastCaptureAt: null, cameraStatus: "Faulty Camera" },
    fusion: { confidence: "Unavailable", reason: "The backend is unavailable." },
    alerts: [], settings: { backendConnected: false, backendLabel: "Backend unavailable", version: "Unavailable" }
  };
}

function renderLoading() {
  const content = `<section class="state-card" role="status"><span class="spinner" aria-hidden="true"></span><h2>Loading ${safe(activePage)}</h2><p>${usingMock ? "Reading explicit mock development data…" : "Connecting to the local VERDE backend…"}</p></section>`;
  app.innerHTML = `<div class="app-shell">${renderHeader({ online: navigator.onLine, isMock: usingMock })}${content}${renderNav()}</div>`;
  bindNav();
}

function renderError(error) {
  if (!usingMock) {
    renderUnavailable(unavailableSnapshot(error));
    return;
  }
  const isTimeout = error?.name === "TimeoutError";
  const content = `<section class="state-card error-card" role="alert"><span aria-hidden="true">!</span><h2>${isTimeout ? "Request timed out" : `Unable to load ${usingMock ? "mock data" : "the VERDE backend"}`}</h2><p>${safe(error?.message || "An unexpected error occurred.")}</p>${usingMock ? "" : "<p>Start the backend with this PWA as its web root, then retry. Live failures never fall back to fake readings.</p>"}<button id="retry-button" class="primary" type="button">Try again</button></section>`;
  app.innerHTML = `<div class="app-shell">${renderHeader({ online: false, isMock: usingMock })}${content}${renderNav()}</div>`;
  document.querySelector("#retry-button").addEventListener("click", render);
  bindNav();
}

function renderUnavailable(data) {
  if (activePage === "Plants") renderPlants(data, lastPageData.get("Plants"));
  else if (activePage === "Settings") renderSettings(data);
  else renderDashboard(data);
}

async function render() {
  const sequence = ++renderSequence;
  if (!lastSnapshot || renderedPage !== activePage) renderLoading();
  try {
    const requests = [api.getSnapshot()];
    if (activePage === "History") requests.push(api.getHistory(historyRange, historyMetric));
    if (activePage === "Alerts") requests.push(api.getAlerts());
    if (activePage === "Settings") requests.push(api.getSmsSettings());
    if (activePage === "Plants") requests.push(api.getPlantSlots().catch((error) => ({ supported: false, error: error.message })));
    let [data, pageData] = await withTimeout(Promise.all(requests));
    if (sequence !== renderSequence) return;
    const age = Date.now() - Date.parse(data.updatedAt);
    if (!data.isMock && Number.isFinite(age) && age > 65_000) {
      data = markSnapshotStale(data, `The last backend sample is ${Math.max(1, Math.floor(age / 1_000))} seconds old.`);
    }
    lastSnapshot = data;
    if (pageData !== undefined) lastPageData.set(activePage, pageData);

    if (activePage === "Plants") renderPlants(data, pageData);
    else if (activePage === "History") renderHistory(data, pageData);
    else if (activePage === "Alerts") renderAlerts(data, pageData);
    else if (activePage === "Settings") renderSettings(data, pageData);
    else renderDashboard(data);
    renderedPage = activePage;
  } catch (error) {
    if (sequence !== renderSequence) return;
    const cachedPageData = lastPageData.get(activePage);
    const pageNeedsData = activePage === "History" || activePage === "Alerts";
    if (lastSnapshot && (!pageNeedsData || cachedPageData !== undefined)) {
      const staleData = markSnapshotStale(lastSnapshot, error?.message || "The backend could not be refreshed.");
      if (activePage === "Plants") renderPlants(staleData, cachedPageData);
      else if (activePage === "History") renderHistory(staleData, cachedPageData);
      else if (activePage === "Alerts") renderAlerts(staleData, cachedPageData);
      else if (activePage === "Settings") renderSettings(staleData, cachedPageData);
      else renderDashboard(staleData);
      renderedPage = activePage;
    } else {
      const unavailableData = unavailableSnapshot(error);
      renderUnavailable(unavailableData);
      renderedPage = activePage;
    }
  }
}

window.addEventListener("hashchange", () => {
  activePage = pageFromHash();
  render();
});
window.addEventListener("online", () => { showToast("Network connection restored. Refreshing live data."); render(); });
window.addEventListener("offline", render);
document.addEventListener("visibilitychange", () => { if (!document.hidden) render(); });
window.addEventListener("beforeinstallprompt", (event) => {
  event.preventDefault();
  deferredInstallPrompt = event;
  if (activePage === "Settings" && lastSnapshot) renderSettings(lastSnapshot, lastPageData.get("Settings"));
});
window.addEventListener("appinstalled", () => {
  deferredInstallPrompt = null;
  showToast("VERDE was installed successfully.");
  if (activePage === "Settings" && lastSnapshot) renderSettings(lastSnapshot, lastPageData.get("Settings"));
});

if (!window.location.hash) window.history.replaceState(null, "", "#Dashboard");
if ("serviceWorker" in navigator) {
  let reloadingForUpdate = false;
  navigator.serviceWorker.addEventListener("controllerchange", () => {
    if (!reloadingForUpdate && navigator.serviceWorker.controller) {
      reloadingForUpdate = true;
      window.location.reload();
    }
  });
  document.addEventListener("visibilitychange", () => {
    if (!document.hidden) navigator.serviceWorker.getRegistration().then((registration) => registration?.update()).catch(() => {});
  });
  window.addEventListener("load", async () => {
    try {
      const registration = await navigator.serviceWorker.register("./service-worker.js?v=77", { updateViaCache: "none" });
      registration.addEventListener("updatefound", () => {
        const worker = registration.installing;
        worker?.addEventListener("statechange", () => {
          if (worker.state === "installed" && navigator.serviceWorker.controller) {
            showToast("Updating VERDE to the latest version…");
          }
        });
      });
    } catch {
      showToast("Offline installation is unavailable in this browser.", "warn");
    }
  });
}

render();
window.setInterval(() => {
  if (!document.hidden && !document.querySelector("dialog[open]")) render();
}, 5_000);
