"use client";

import { useEffect, useMemo, useState } from "react";
import { API_URL } from "@/lib/api";
import { BarChart, LineChart } from "./Charts";

type PopulationItem = {
  id: number;
  drivers: number;
  weeks: number;
  seed: number;
  generator: string;
  extra_cameras: number;
  stale: boolean;
  summary: { reads: number; reads_per_driver_median: number; drivers_never_read: number };
};
type UnicityRow = { size: number; p: number; eligible_share: number; unique_share: number };
type Stat = { estimated: number; median_km: number | null; within_1km: number; within_1km_of_all: number };
type PolicyRow = {
  policy: string;
  description: string;
  reads: number;
  engine_home: Stat;
  engine_work: Stat;
  naive_home: Stat;
  unicity_p2: number;
  unicity_p4: number;
  unicity_resolution_min: number;
};

const POLICY_LABELS: Record<string, string> = {
  baseline: "No limits",
  retention_28d: "Keep 28 days",
  retention_14d: "Keep 14 days",
  retention_7d: "Keep 7 days",
  retention_1d: "Keep 1 day",
  baseline_15min: "No limits (15-min points)",
  round_hour: "Round to the hour",
  window_72h: "Search window ±36 h",
  window_24h: "Search window ±12 h",
  aggregate_only: "Aggregate counts only",
};

async function get<T>(path: string): Promise<T> {
  const r = await fetch(`${API_URL}${path}`);
  if (!r.ok) throw new Error(`${path}: ${r.status}`);
  return r.json();
}

type Props = {
  scenarioTown: string; // where hypothetical cameras are placed (region's scenario_town)
  exampleRegion: boolean; // true for the bundled NJ example, which has published figures to compare against
};

export default function PopulationView({ scenarioTown, exampleRegion }: Props) {
  const [pops, setPops] = useState<PopulationItem[]>([]);
  const [pid, setPid] = useState<number | null>(null);
  const [unicity, setUnicity] = useState<UnicityRow[] | null>(null);
  const [policies, setPolicies] = useState<PolicyRow[] | null>(null);
  const [selected, setSelected] = useState<string>("baseline");
  const [table, setTable] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    get<PopulationItem[]>("/populations").then((ps) => {
      const real = ps.filter((p) => p.drivers >= 100);
      setPops(real);
      const first = real.find((p) => !p.stale) ?? real[0];
      if (first) setPid(first.id);
    }).catch((e: Error) => setError(e.message));
  }, []);

  useEffect(() => {
    if (pid == null) return;
    setUnicity(null);
    setPolicies(null);
    const pop = pops.find((p) => p.id === pid);
    const sizes = [100, 300, pop?.drivers ?? 1000].filter((v, i, a) => a.indexOf(v) === i && v <= (pop?.drivers ?? 1000));
    get<{ rows: UnicityRow[] }>(`/populations/${pid}/unicity?p=1,2,3,4,6,8&size=${sizes.join(",")}`)
      .then((u) => setUnicity(u.rows)).catch((e: Error) => setError(e.message));
    get<{ rows: PolicyRow[] }>(`/populations/${pid}/policies`)
      .then((p) => setPolicies(p.rows)).catch((e: Error) => setError(e.message));
  }, [pid, pops]);

  const series = useMemo(() => {
    if (!unicity) return [];
    const sizes = [...new Set(unicity.map((r) => r.size))].sort((a, b) => a - b);
    return sizes.map((n) => ({
      name: `${n} cars`,
      points: unicity.filter((r) => r.size === n).map((r) => ({ x: r.p, y: r.unique_share * r.eligible_share })),
    }));
  }, [unicity]);

  const shown = (policies ?? []).filter((r) => r.policy !== "baseline_15min");
  const sel = policies?.find((r) => r.policy === selected);
  const pop = pops.find((p) => p.id === pid);

  return (
    <div className="popview">
      <section className="picker">
        <label htmlFor="pop">Population</label>
        <select id="pop" value={pid ?? ""} onChange={(e) => setPid(Number(e.target.value))}>
          {pops.map((p) => (
            <option key={p.id} value={p.id}>
              #{p.id} · {p.drivers} drivers · {p.weeks} wk · {p.generator}{p.extra_cameras ? ` · +${p.extra_cameras} hypothetical cams` : ""}
              {p.stale ? " · stale" : ""}
            </option>
          ))}
        </select>
        {!pops.length && !error && <div className="nb-note">No populations yet: run `python -m platetrail.population`.</div>}
      </section>
      {error && <div className="error">{error}</div>}
      {pop && (
        <section className="readout">
          <p>
            <b>{pop.drivers}</b> synthetic drivers over <b>{pop.weeks}</b> week{pop.weeks > 1 ? "s" : ""}: median{" "}
            <b>{pop.summary.reads_per_driver_median}</b> reads per driver; <b>{pop.summary.drivers_never_read}</b> never read.
          </p>
          {pop.extra_cameras > 0 && (
            <div className="nb-note">
              Includes {pop.extra_cameras} hypothetical cameras in {scenarioTown}.
              {exampleRegion && " Edison's 92 approved cameras have no public locations."} Placement is simulated: arterial roads (trunk to tertiary) chosen in proportion to length, at least 300 m from any other camera, each reading one direction, drawn per seed.
            </div>
          )}
        </section>
      )}

      <section className="charts">
        {unicity ? (
          <LineChart series={series} xLabel="sightings known (camera + hour)"
                     title="Drivers singled out by p sightings, in a crowd of N cars" />
        ) : <div className="nb-note">Computing unicity…</div>}
        <div className="nb-note">
          Unicity (after de Montjoye et al. 2013): if plates were hashed, would p known sightings pick out one car?
          It falls as the crowd grows.{" "}
          {exampleRegion ? (
            <>Edison PD&apos;s portal reports 518,797 &ldquo;unique plate reads&rdquo; in 30 days, far more than any
            simulated crowd, so these shares are upper bounds.</>
          ) : (
            <>A real network sees far more cars than any simulated crowd, so these shares are upper bounds.</>
          )}
        </div>
      </section>

      <section className="charts">
        <div className="policy-head">
          <span>Policy comparison</span>
          <button className="linkish" onClick={() => setTable(!table)}>{table ? "charts" : "table view"}</button>
        </div>
        {policies ? (
          table ? (
            <table className="policy-table">
              <thead><tr><th>Policy</th><th>Reads</th><th>Home ≤1 km (of all drivers)</th><th>Work est.</th><th>Unique p2</th><th>p4</th></tr></thead>
              <tbody>
                {policies.map((r) => (
                  <tr key={r.policy}>
                    <td>{POLICY_LABELS[r.policy] ?? r.policy}</td><td>{r.reads}</td>
                    <td>{Math.round(r.engine_home.within_1km_of_all * 100)}%</td>
                    <td>{Math.round(r.engine_work.estimated * 100)}%</td>
                    <td>{Math.round(r.unicity_p2 * 100)}%</td><td>{Math.round(r.unicity_p4 * 100)}%</td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : (
            <>
              <BarChart title="Drivers singled out by 2 hourly sightings" selected={selected} onSelect={setSelected}
                        rows={shown.map((r) => ({ key: r.policy, label: POLICY_LABELS[r.policy] ?? r.policy, value: r.unicity_p2 }))} />
              <BarChart title="Drivers whose home the engine places within 1 km (share of all drivers)" selected={selected} onSelect={setSelected}
                        rows={shown.map((r) => ({ key: r.policy, label: POLICY_LABELS[r.policy] ?? r.policy, value: r.engine_home.within_1km_of_all }))} />
            </>
          )
        ) : <div className="nb-note">Computing policies…</div>}
        {sel && !table && (
          <div className="naive">
            <div className="nb-head"><span>{POLICY_LABELS[sel.policy] ?? sel.policy}</span></div>
            <div className="nb-note">{sel.description}</div>
            <div className="nb-row"><span className="nb-k">Reads</span><span>{sel.reads.toLocaleString()} queryable</span><span /></div>
            <div className="nb-row"><span className="nb-k">Home</span><span>engine estimates {Math.round(sel.engine_home.estimated * 100)}%
              {sel.engine_home.median_km != null && <>, median off {sel.engine_home.median_km.toFixed(1)} km</>}</span><span /></div>
            <div className="nb-row"><span className="nb-k">Work</span><span>engine estimates {Math.round(sel.engine_work.estimated * 100)}%
              {sel.engine_work.median_km != null && <>, median off {sel.engine_work.median_km.toFixed(1)} km</>}</span><span /></div>
            <div className="nb-row"><span className="nb-k">Unique</span><span>{Math.round(sel.unicity_p2 * 100)}% with 2 sightings, {Math.round(sel.unicity_p4 * 100)}% with 4
              ({sel.unicity_resolution_min}-min points)</span><span /></div>
          </div>
        )}
      </section>
    </div>
  );
}
