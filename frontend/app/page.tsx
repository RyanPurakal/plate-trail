"use client";

import dynamic from "next/dynamic";
import { useEffect, useMemo, useState } from "react";
import LogTable from "@/components/LogTable";
import type { Layers, Mode } from "@/components/MapView";
import {
  getCameras,
  getRun,
  getRuns,
  simulate,
  type CameraCollection,
  type RunDetail,
  type RunListItem,
} from "@/lib/api";
import { dayKey, km, parts, templateName } from "@/lib/format";

const MapView = dynamic(() => import("@/components/MapView"), { ssr: false });

export default function Home() {
  const [cameras, setCameras] = useState<CameraCollection | null>(null);
  const [runs, setRuns] = useState<RunListItem[]>([]);
  const [runId, setRunId] = useState<number | null>(null);
  const [detail, setDetail] = useState<RunDetail | null>(null);
  const [mode, setMode] = useState<Mode>("saw");
  const [layers, setLayers] = useState<Layers>({ routes: true, cameras: true, skipped: true });
  const [day, setDay] = useState<string | null>(null);
  const [focus, setFocus] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [form, setForm] = useState({ template: "commuter", weeks: 1, seed: 1 });

  useEffect(() => {
    Promise.all([getCameras(), getRuns()])
      .then(([c, r]) => {
        setCameras(c);
        setRuns(r);
        const fresh = r.find((x) => !x.stale) ?? r[0];
        if (fresh) setRunId(fresh.id);
      })
      .catch((e: Error) => setError(`API unreachable: ${e.message}`));
  }, []);

  useEffect(() => {
    if (runId == null) return;
    setDetail(null);
    setDay(null);
    setFocus(null);
    getRun(runId).then(setDetail).catch((e: Error) => setError(e.message));
  }, [runId]);

  const days = useMemo(() => {
    const ds = new Set<string>();
    for (const t of detail?.trips.features ?? []) ds.add(dayKey(t.properties.depart));
    return [...ds].sort();
  }, [detail]);

  const view = useMemo(() => {
    const inDay = (iso: string) => !day || dayKey(iso) === day;
    return {
      trips: (detail?.trips.features ?? []).filter((t) => inDay(t.properties.depart)),
      passes: (detail?.passes ?? []).filter((p) => inDay(p.time)),
      reads: (detail?.reads ?? []).filter((r) => inDay(r.time)),
    };
  }, [detail, day]);

  const truth = useMemo(() => {
    const km_ = view.trips.reduce((s, t) => s + t.properties.length_m, 0);
    const captured = view.passes.filter((p) => p.captured).length;
    const lost = view.passes.filter((p) => p.captured && p.noise_outcome !== "read").length;
    return { trips: view.trips.length, km: km_, passes: view.passes.length, captured, lost };
  }, [view]);

  const cameraCount = new Set(view.reads.map((r) => r.camera_label)).size;
  const misreads = view.reads.filter((r) => r.misread).length;
  const run = detail?.run;

  async function onSimulate(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const { run_id } = await simulate({ template: form.template, weeks: form.weeks, seed: form.seed });
      setRuns(await getRuns());
      setRunId(run_id);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className={`shell mode-${mode}`}>
      <aside className="dossier">
        <header className="masthead">
          <div className="kicker">Plate Trail · ALPR privacy audit</div>
          <h1>What the cameras saw</h1>
          <p className="lede">
            One synthetic driver, real camera positions in Edison &amp; New Brunswick, NJ. Compare the read log an
            agency would hold with the week the driver actually drove.
          </p>
        </header>

        <section className="picker">
          <label htmlFor="run">Stored run</label>
          <select id="run" value={runId ?? ""} onChange={(e) => setRunId(Number(e.target.value))}>
            {runs.map((r) => (
              <option key={r.id} value={r.id}>
                #{r.id} · {templateName(r.generator)} · {r.weeks} wk · seed {r.seed} · {r.summary.reads} reads
                {r.stale ? " · stale" : ""}
              </option>
            ))}
          </select>
          <details className="simulate">
            <summary>Simulate a new driver</summary>
            <form onSubmit={onSimulate}>
              <select value={form.template} onChange={(e) => setForm({ ...form, template: e.target.value })}>
                <option value="commuter">commuter</option>
                <option value="student">student</option>
                <option value="shift_worker">shift worker</option>
              </select>
              <input type="number" min={1} max={8} value={form.weeks} aria-label="weeks"
                     onChange={(e) => setForm({ ...form, weeks: Number(e.target.value) })} />
              <span className="unit">wk</span>
              <input type="number" min={0} value={form.seed} aria-label="seed"
                     onChange={(e) => setForm({ ...form, seed: Number(e.target.value) })} />
              <span className="unit">seed</span>
              <button disabled={busy}>{busy ? "running…" : "run"}</button>
            </form>
          </details>
        </section>

        {error && <div className="error">{error}</div>}
        {run?.stale && (
          <div className="error stale">
            Stale run: cameras were reloaded after it was simulated, so camera references may not match.
            Simulate a new driver for current data.
          </div>
        )}

        {run && (
          <section className="tag">
            <div className="plate-tag">
              <span className="plate-state">{run.plate_state}</span>
              <span className="plate-num">{run.plate}</span>
            </div>
            <div className="tag-meta">
              {templateName(run.generator)} · {run.weeks} week{run.weeks > 1 ? "s" : ""} from {run.start_date} · seed{" "}
              {run.seed}
              <br />
              <span className="dim">synthetic plate; state ZZ does not exist</span>
            </div>
          </section>
        )}

        <section className="switch" role="tablist" aria-label="view">
          <button role="tab" aria-selected={mode === "saw"} className={mode === "saw" ? "on" : ""} onClick={() => setMode("saw")}>
            <span className="sw-k">What the cameras saw</span>
            <span className="sw-v">{view.reads.length}<small> reads · {cameraCount} cam{cameraCount === 1 ? "" : "s"}</small></span>
          </button>
          <button role="tab" aria-selected={mode === "happened"} className={mode === "happened" ? "on" : ""} onClick={() => setMode("happened")}>
            <span className="sw-k">What actually happened</span>
            <span className="sw-v">{truth.trips}<small> trips · {km(truth.km * 1)}</small></span>
          </button>
        </section>

        <section className="readout">
          {mode === "saw" ? (
            <p>
              The agency holds <b>{view.reads.length}</b> timestamped plate reads
              {misreads > 0 && <> (<b>{misreads}</b> misread, though nothing in the log says so)</>}. No routes,
              no stops, no purposes: only where the {cameraCount} camera{cameraCount === 1 ? "" : "s"} happened to be.
            </p>
          ) : (
            <p>
              The driver made <b>{truth.trips}</b> trips over <b>{km(truth.km)}</b> and passed <b>{truth.passes}</b>{" "}
              camera{truth.passes === 1 ? "" : "s"}. <b>{truth.captured}</b> faced the right way; <b>{truth.lost}</b> of
              those reads were lost to misses or downtime.
            </p>
          )}
        </section>

        <section className="controls">
          <div className="days">
            <button className={!day ? "on" : ""} onClick={() => setDay(null)}>all</button>
            {days.map((d) => (
              <button key={d} className={day === d ? "on" : ""} onClick={() => setDay(d)} title={d}>
                {parts(d).weekday.slice(0, 2)}<small>{d.slice(8)}</small>
              </button>
            ))}
          </div>
          <div className="layers">
            <label className={mode === "saw" ? "disabled" : ""} title={mode === "saw" ? "The cameras never saw the routes" : ""}>
              <input type="checkbox" checked={layers.routes} disabled={mode === "saw"}
                     onChange={(e) => setLayers({ ...layers, routes: e.target.checked })} /> true routes
            </label>
            <label className={mode === "saw" ? "disabled" : ""}>
              <input type="checkbox" checked={layers.skipped} disabled={mode === "saw"}
                     onChange={(e) => setLayers({ ...layers, skipped: e.target.checked })} /> uncaptured passes
            </label>
            <label>
              <input type="checkbox" checked={layers.cameras} onChange={(e) => setLayers({ ...layers, cameras: e.target.checked })} /> cameras
            </label>
          </div>
        </section>

        <LogTable mode={mode} reads={view.reads} passes={view.passes} focusLabel={focus} onFocus={setFocus} />
      </aside>

      <main className="stage">
        <MapView
          cameras={cameras}
          trips={view.trips}
          passes={view.passes}
          reads={view.reads}
          mode={mode}
          layers={layers}
          focusLabel={focus}
          fitKey={detail ? `${detail.run.id}:${day ?? "all"}` : ""}
        />
        <div className="legend">
          {mode === "saw" ? (
            <>
              <span><i className="lg-read" />read (size = count)</span>
              <span><i className="lg-trail" />implied sequence</span>
            </>
          ) : (
            <>
              <span><i className="lg-truth" />true route</span>
              <span><i className="lg-ring lg-ring-read" />read</span>
              <span><i className="lg-ring lg-ring-lost" />captured, lost</span>
              <span><i className="lg-ring lg-ring-skip" />wrong direction</span>
            </>
          )}
          <span><i className="lg-arrow" />camera (arrow = facing)</span>
          <span><i className="lg-arrow lg-lot" />lot</span>
          <span><i className="lg-arrow lg-svc" />service street</span>
          <span><i className="lg-undir" />no direction</span>
        </div>
        <div className="mode-stamp">{mode === "saw" ? "RECORDED" : "GROUND TRUTH"}</div>
      </main>
    </div>
  );
}
