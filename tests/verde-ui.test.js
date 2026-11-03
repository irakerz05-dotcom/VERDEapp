import test from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import { buildChartGeometry, escapeHtml, formatHistoryValue, harvestReadiness, niceTime, normalizePage, safeResourceUrl, statusClass } from "../js/verde-ui.js";

test("harvest readiness requires a current Healthy result and at least 30 growing days", () => {
  const slots = { supported: true, slots: [29, 30, 31, 35, null, 40, 30, 31].map((daysGrowing, index) => ({
    slot: index + 1, plantedOn: daysGrowing === null ? null : "2026-09-01", daysGrowing
  })) };
  const fusion = ["Healthy", "Healthy", "Yellowing", null, "Healthy", "Healthy", "Healthy", "Wilting"].map((plantCondition, index) => ({
    slot: index + 1, plantCondition, status: plantCondition ? "READY" : "NO DETECTION"
  }));
  assert.deepEqual(harvestReadiness(slots, fusion, true).map((item) => item.status),
    ["Growing", "Harvest-Ready", "Not ready", "No detection", "Set date", "Harvest-Ready", "Harvest-Ready", "Not ready"]);
  assert.ok(harvestReadiness(slots, fusion, false).every((item) => item.status === "Unavailable"));
  fusion[5].status = "Stale";
  assert.equal(harvestReadiness(slots, fusion, true)[5].status, "Unavailable");
});

const root = fileURLToPath(new URL("../", import.meta.url));

test("dynamic HTML is escaped before template rendering", () => {
  assert.equal(
    escapeHtml('<img src=x onerror="alert(1)"> & data'),
    "&lt;img src=x onerror=&quot;alert(1)&quot;&gt; &amp; data"
  );
  assert.equal(safeResourceUrl("javascript:alert(1)"), "");
  assert.equal(safeResourceUrl("/camera/latest.jpg"), "http://localhost/camera/latest.jpg");
});

test("route normalization accepts known pages and rejects unknown hashes", () => {
  assert.equal(normalizePage("history"), "History");
  assert.equal(normalizePage(" Settings "), "Settings");
  assert.equal(normalizePage("<script>"), "Dashboard");
});

test("status tones and invalid timestamps have safe fallbacks", () => {
  assert.equal(statusClass("Optimal"), "good");
  assert.equal(statusClass("Critical"), "danger");
  assert.equal(statusClass("Suboptimal"), "warn");
  assert.equal(niceTime("not-a-date"), "Unavailable");
});

test("chart geometry contains only finite coordinates", () => {
  const chart = buildChartGeometry([5.8, 6.1, 5.9]);
  assert.equal(chart.points.length, 3);
  assert.match(chart.path, /^M/);
  assert.ok(chart.points.every(({ x, y }) => Number.isFinite(x) && Number.isFinite(y)));
});

test("history values display four decimals without changing stored precision", () => {
  assert.equal(formatHistoryValue(1.5034913245873889), "1.5035");
  assert.equal(formatHistoryValue(65), "65.0000");
  assert.equal(formatHistoryValue(-2.5), "-2.5000");
  assert.equal(formatHistoryValue(null), "—");
  assert.equal(formatHistoryValue(Number.NaN), "—");
});

test("service-worker assets match versioned index and module references", async () => {
  const [index, worker, app] = await Promise.all([
    readFile(`${root}index.html`, "utf8"),
    readFile(`${root}service-worker.js`, "utf8"),
    readFile(`${root}js/app.js`, "utf8")
  ]);

  assert.match(index, /href="styles\.css\?v=64"/);
  assert.match(index, /src="js\/app\.js\?v=64"/);
  assert.match(app, /services\/verde-api\.js\?v=64/);
  assert.match(app, /verde-ui\.js\?v=64/);
  assert.match(app, /sensor-detail/);
  assert.match(app, /Problem timeline/);
  assert.match(app, /Alerts & activity/);
  assert.match(worker, /"\.\/styles\.css\?v=64"/);
  assert.match(worker, /"\.\/js\/app\.js\?v=64"/);
  assert.match(worker, /"\.\/js\/verde-ui\.js\?v=64"/);
  assert.match(worker, /"\.\/js\/services\/verde-api\.js\?v=64"/);
  const dashboard = app.split("function renderDashboard(data) {")[1]?.split("function plantAge(slot) {")[0];
  const plants = app.split("function renderPlants(data, slots = null) {")[1];
  assert.ok(dashboard);
  assert.match(dashboard, /WATER QUALITY/);
  assert.match(dashboard, /correctionGuidance\(data\)/);
  assert.match(app, /LIVE CORRECTION GUIDANCE/);
  assert.match(app, /Manual correction requested:/);
  assert.match(app, /Manual correction required for Critical readings/);
  assert.match(app, /Critical or faulty condition: circulation is stopped/);
  assert.match(app, /Manually dose/);
  assert.match(app, /View pump dosing history/);
  assert.match(app, /\.page-title"\)\?\.after\(app\.querySelector\("\.pump-history"\)\)/);
  assert.doesNotMatch(dashboard, /REAL-DATA RF PILOT|PLANT MONITORING|SENSOR-VISION FUSION/);
  assert.match(plants, /SENSOR-VISION FUSION/);
  assert.match(plants, /Latest per-class plant analysis/);
  assert.match(plants, /Fusion confidence by NFT plant slot/);
  assert.match(plants, /8 fixed plant slots/);
  assert.match(plants, /plantSlotRow\(slots, 5\)/);
  assert.match(plants, /plantFusionRow\(data\.fusionBySlot, 5\)/);
  assert.match(plants, /HARVEST READINESS/);
  assert.match(plants, /harvestRow\(readiness, 1\)/);
  assert.match(plants, /harvestRow\(readiness, 5\)/);
  assert.doesNotMatch(plants, /plantSlotRow\(slots, 9\)|plantFusionRow\(data\.fusionBySlot, 9\)/);
  assert.doesNotMatch(plants, /class="plant-result"|class="fusion-result"/);
  assert.match(worker, /caches\.delete/);
  assert.match(worker, /pathname\.startsWith\("\/api\/"\)/);
  assert.match(app, /updateViaCache: "none"/);
  assert.match(app, /Acknowledge this incident/);
  assert.match(app, /data-retry-connection/);
  const settings = app.split("function renderSettings(data, smsSettings = { supported: false }) {")[1]
    ?.split("function unavailableSnapshot(error) {")[0];
  const smsDialog = app.split("function showSmsSettingsDialog(settings) {")[1]
    ?.split("function bindSmsSettingsButton(")[0];
  assert.ok(settings);
  assert.ok(smsDialog);
  assert.match(settings, /GSM SMS alerts/);
  assert.match(settings, /Mode: \$\{safe\(data\.settings\.gsmStatus/);
  assert.doesNotMatch(settings, /Backend connection|The number is stored on the Pi|Changing it does not send a message/);
  assert.match(smsDialog, /Current recipient:/);
  assert.match(smsDialog, /Enter a new number to change it/);
  assert.doesNotMatch(smsDialog, /Saving does not send a test SMS|Critical and persistent faulty conditions/);
});
