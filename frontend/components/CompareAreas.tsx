"use client";

import { useEffect, useState } from "react";
import { getArea, type AreaResult } from "@/lib/api";
import { shortDate, type BBox } from "@/lib/area";
import type { SavedArea } from "@/lib/areas";

type Props = {
  areas: SavedArea[];
  onOpen: (bbox: BBox) => void;
};

type Side = { id: string; result: AreaResult | null; error: string | null };

const pct = (r: AreaResult) => {
  const share = r.summary.main_roads?.share;
  return share == null ? "–" : `${Math.round(share * 100)}%`;
};

const latest = (r: AreaResult, key: "fetched_at" | "latest_edit") => {
  const dates = r.summary.sources.map((s) => s[key]).filter((d): d is string => !!d).sort();
  return shortDate(dates[dates.length - 1] ?? null) ?? "–";
};

const ROWS: [string, (r: AreaResult) => string][] = [
  ["Sensors mapped", (r) => String(r.summary.sensor_count)],
  ["Area", (r) => `${r.summary.area_km2.toLocaleString()} km²`],
  ["Per 100 km²", (r) => (r.summary.sensors_per_100km2 == null ? "–" : String(r.summary.sensors_per_100km2))],
  ["Direction known", (r) => `${r.summary.with_direction} of ${r.summary.sensor_count}`],
  ["Main roads near a sensor", pct],
  ["Latest map edit", (r) => latest(r, "latest_edit")],
  ["Data fetched", (r) => latest(r, "fetched_at")],
];

/**
 * Two saved areas side by side. Results stay in this component's memory; comparing does not
 * replace the stored last look, so "Since your last visit" still compares with the user's own visits.
 */
export default function CompareAreas({ areas, onOpen }: Props) {
  const [pick, setPick] = useState<[string, string]>(["", ""]);
  const [sides, setSides] = useState<[Side, Side] | null>(null);
  const [loading, setLoading] = useState(false);

  // Keep the picks pointing at saved areas (defaults: the first two) as the list changes.
  useEffect(() => {
    const ids = areas.map((a) => a.id);
    setPick(([a, b]) => {
      const na = ids.includes(a) ? a : ids[0] ?? "";
      const nb = ids.includes(b) && b !== na ? b : ids.find((id) => id !== na) ?? "";
      return na === a && nb === b ? [a, b] : [na, nb];
    });
  }, [areas]);
  useEffect(() => setSides(null), [pick]);

  const byId = (id: string) => areas.find((a) => a.id === id);

  async function compare() {
    setLoading(true);
    const out = await Promise.all(pick.map(async (id): Promise<Side> => {
      const a = byId(id);
      if (!a) return { id, result: null, error: "This area is no longer saved." };
      try {
        return { id, result: await getArea(a.bbox), error: null };
      } catch (err) {
        return { id, result: null, error: (err as Error).message };
      }
    }));
    setSides([out[0], out[1]]);
    setLoading(false);
  }

  return (
    <section className="naive" aria-labelledby="ca-title">
      <div className="nb-head">
        <span id="ca-title">Compare areas</span>
        <span className="nb-badge">public data</span>
      </div>
      {areas.length < 2 ? (
        <div className="nb-note">Save two areas, for example where you live and where you work, to compare them side by side.</div>
      ) : (
        <>
          <div className="ca-picks">
            {(["A", "B"] as const).map((label, i) => (
              <label key={label}>
                <span className="ex-k">Area {label}</span>
                <select value={pick[i]} disabled={loading}
                  onChange={(e) => setPick(i === 0 ? [e.target.value, pick[1]] : [pick[0], e.target.value])}>
                  {areas.map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}
                </select>
              </label>
            ))}
          </div>
          {pick[0] === pick[1] && <div className="nb-note">Pick two different areas.</div>}
          <div className="ex-actions">
            <button className="ex-share" onClick={compare} disabled={loading || !pick[0] || pick[0] === pick[1]}>
              {loading ? "Loading public map data…" : sides ? "Compare again" : "Compare"}
            </button>
          </div>

          {sides && (
            <div aria-live="polite">
              <table className="ca-table">
                <thead>
                  <tr>
                    <th scope="col"><span className="sr-only">Measure</span></th>
                    {sides.map((s) => {
                      const a = byId(s.id);
                      return (
                        <th scope="col" key={s.id}>
                          {a?.name ?? "Removed area"}
                          {a && <button className="ex-share ca-open" onClick={() => onOpen(a.bbox)}>Open</button>}
                        </th>
                      );
                    })}
                  </tr>
                </thead>
                <tbody>
                  {ROWS.map(([label, value]) => (
                    <tr key={label}>
                      <th scope="row">{label}</th>
                      {sides.map((s) => <td key={s.id}>{s.result ? value(s.result) : "–"}</td>)}
                    </tr>
                  ))}
                </tbody>
              </table>
              {sides.map((s) => s.error && (
                <div key={s.id} className="error" role="alert">{byId(s.id)?.name ?? "Area"}: {s.error}</div>
              ))}
              <div className="nb-note">
                Counts reflect what has been mapped in public data, and how completely sensors are mapped varies from
                place to place. Per 100 km² makes areas of different sizes easier to compare. Comparing does not change
                the last-look dates used by &ldquo;Since your last visit&rdquo;.
              </div>
            </div>
          )}
        </>
      )}
    </section>
  );
}
