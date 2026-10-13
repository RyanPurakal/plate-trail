// Simulated times are local New Jersey wall-clock times without a zone ("2026-10-12T07:56:42.2");
// parse the fields directly so the browser's time zone never shifts them.

const DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

export function parts(iso: string) {
  const [d, t = "00:00:00"] = iso.split("T");
  const [y, m, day] = d.split("-").map(Number);
  const weekday = DAYS[(new Date(Date.UTC(y, m - 1, day)).getUTCDay() + 6) % 7];
  return { date: d, weekday, time: t.slice(0, 8) };
}

export const dayKey = (iso: string) => iso.slice(0, 10);

export function stamp(iso: string) {
  const p = parts(iso);
  return `${p.weekday} ${p.date.slice(5)} ${p.time}`;
}

export function shortTime(iso: string) {
  const p = parts(iso);
  return `${p.weekday} ${p.time.slice(0, 5)}`;
}

export const km = (m: number) => `${(m / 1000).toFixed(1)} km`;

export function templateName(generator: string) {
  return generator.replace(/^template:/, "").replace("_", " ");
}
