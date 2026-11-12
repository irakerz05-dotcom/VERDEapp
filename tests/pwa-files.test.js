import test from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";

const read = (path) => readFile(new URL(`../${path}`, import.meta.url), "utf8");

test("manifest defines an installable standalone VERDE application", async () => {
  const manifest = JSON.parse(await read("manifest.webmanifest"));
  assert.equal(manifest.id, "./");
  assert.equal(manifest.scope, "./");
  assert.match(manifest.start_url, /#Dashboard$/);
  assert.equal(manifest.display, "standalone");
  assert.ok(manifest.icons.some((icon) => icon.sizes === "192x192" && icon.type === "image/png"));
  assert.ok(manifest.icons.some((icon) => icon.sizes === "512x512" && icon.type === "image/png"));
  assert.ok(manifest.icons.some((icon) => icon.purpose.includes("maskable")));
});

test("service worker caches the application shell but never API responses", async () => {
  const worker = await read("service-worker.js");
  assert.match(worker, /verde-pwa-/);
  assert.match(worker, /pathname\.startsWith\("\/api\/"\)/);
  assert.match(worker, /caches\.match\("\.\/index\.html"\)/);
});

test("page exposes mobile installation metadata and current assets", async () => {
  const page = await read("index.html");
  assert.match(page, /mobile-web-app-capable/);
  assert.match(page, /manifest\.webmanifest/);
  assert.match(page, /js\/app\.js\?v=76/);
});
