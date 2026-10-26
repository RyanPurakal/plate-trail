import type { AreaResult, RouteCheck } from "./api";
import type { SnapshotChange } from "./snapshots";

// Short sentences for the page's one screen-reader live region. The cards themselves are not live regions,
// so a load is read as one line instead of the whole card.

const plural = (n: number, word: string) => `${n} ${word}${n === 1 ? "" : "s"}`;

function changeText(change: SnapshotChange | null | undefined): string {
  if (!change) return "";
  if (!change.added.length && !change.removed.length) return " No sensors added or removed since your last look.";
  const bits = [
    change.added.length ? `${change.added.length} newly listed` : "",
    change.removed.length ? `${change.removed.length} no longer listed` : "",
  ].filter(Boolean);
  return ` Since your last look: ${bits.join(", ")}.`;
}

export function areaAnnouncement(a: AreaResult, change: SnapshotChange | null): string {
  const s = a.summary;
  if (s.sensor_count === 0) return "Area loaded. No fixed sensors are mapped in this box." + changeText(change);
  const roads = s.main_roads?.share != null ? ` ${Math.round(s.main_roads.share * 100)}% of main-road length is near one.` : "";
  return `Area loaded. ${plural(s.sensor_count, "fixed sensor")} mapped.${roads} Summary is in the sidebar.` + changeText(change);
}

export function routeAnnouncement(name: string, r: RouteCheck, change?: SnapshotChange | null): string {
  const legs = r.legs.map((l) =>
    `${l.direction === "outbound" ? "Start to end" : "Way back"}: ${plural(l.sensors_passed, "sensor")} passed, ${l.reads} would record it.`);
  return `${name} checked. ${legs.join(" ")}` + changeText(change);
}

/** Next text for the live region; a trailing no-break space makes a repeat of the same sentence read again. */
export function nextAnnouncement(prev: string, text: string): string {
  return prev === text ? `${text} ` : text;
}
