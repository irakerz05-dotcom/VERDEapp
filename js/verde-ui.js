export const PAGES = ["Dashboard", "Plants", "History", "Alerts", "Settings"];

export function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>'"]/g, (character) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    "'": "&#039;",
    '"': "&quot;"
  })[character]);
}

export function normalizePage(value) {
  const requested = String(value ?? "").trim().toLowerCase();
  return PAGES.find((page) => page.toLowerCase() === requested) ?? "Dashboard";
}

export function statusClass(status) {
  const value = String(status ?? "");
  if (/critical|fault|offline|error/i.test(value)) return "danger";
  if (/\b(optimal|normal|healthy|high|online|resolved)\b/i.test(value)) return "good";
  return "warn";
}

export function safeResourceUrl(value, base = "http://localhost/") {
  if (!value) return "";
  try {
    const url = new URL(String(value), base);
    return ["http:", "https:"].includes(url.protocol) ? url.href : "";
  } catch {
    return "";
  }
}

export function niceTime(iso, locale) {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "Unavailable";
  return new Intl.DateTimeFormat(locale, { dateStyle: "medium", timeStyle: "short" }).format(date);
}

export function buildChartGeometry(values, width = 284, height = 105, offsetX = 20, offsetY = 20) {
  const safeValues = values.map(Number).filter(Number.isFinite);
  if (!safeValues.length) return { path: "", points: [] };

  const minimum = Math.min(...safeValues);
  const maximum = Math.max(...safeValues);
  const range = maximum - minimum || 1;
  const step = safeValues.length === 1 ? 0 : width / (safeValues.length - 1);
  const points = safeValues.map((value, index) => ({
    x: Number((offsetX + step * index).toFixed(2)),
    y: Number((offsetY + height - ((value - minimum) / range) * height).toFixed(2))
  }));

  return {
    path: points.map((point, index) => `${index ? "L" : "M"}${point.x} ${point.y}`).join(""),
    points
  };
}
