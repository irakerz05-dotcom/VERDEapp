import test from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import { buildChartGeometry, escapeHtml, niceTime, normalizePage, safeResourceUrl, statusClass } from "../js/verde-ui.js";

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

test("service-worker assets match versioned index and module references", async () => {
  const [index, worker, app] = await Promise.all([
    readFile(`${root}index.html`, "utf8"),
    readFile(`${root}service-worker.js`, "utf8"),
    readFile(`${root}js/app.js`, "utf8")
  ]);

  assert.match(index, /href="styles\.css\?v=45"/);
  assert.match(index, /src="js\/app\.js\?v=45"/);
  assert.match(app, /services\/verde-api\.js\?v=45/);
  assert.match(app, /verde-ui\.js\?v=45/);
  assert.match(app, /sensor-detail/);
  assert.match(app, /Problem timeline/);
  assert.match(app, /Alerts & activity/);
  assert.match(worker, /"\.\/styles\.css\?v=45"/);
  assert.match(worker, /"\.\/js\/app\.js\?v=45"/);
  assert.match(worker, /"\.\/js\/verde-ui\.js\?v=45"/);
  assert.match(worker, /"\.\/js\/services\/verde-api\.js\?v=45"/);
  assert.match(app, /REAL-DATA RF PILOT/);
  assert.match(worker, /caches\.delete/);
  assert.match(worker, /pathname\.startsWith\("\/api\/"\)/);
  assert.match(app, /updateViaCache: "none"/);
  assert.match(app, /Acknowledge this incident/);
  assert.match(app, /data-retry-connection/);
});
