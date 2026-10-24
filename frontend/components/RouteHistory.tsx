"use client";

import { useState } from "react";
import { routeHistory, type HistoryPeriod, type HistoryPlace, type RouteHistory as History } from "@/lib/api";
import type { Pt } from "@/lib/routes";

const DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
const DAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"];

const periodName = (days: number) => (days === 365 ? "1 year" : days === 1 ? "1 day" : `${days} days`);
const dist = (m: number) => (m >= 1000 ? `${(m / 1000).toFixed(1)} km` : `${Math.round(m / 50) * 50} m`);

function PlaceRow({ label, place }: { label: string; place?: HistoryPlace }) {
  return (
    <div className="ex-row">
      <span>{label}</span>
      <span>
        {place
          ? `within ~${dist(place.radius_m)}, ${place.confidence} confidence, ${dist(place.distance_m)} from the ${place.nearer_end}`
          : "not suggested"}
      </span>
    </div>
  );
}

function Period({ p }: { p: HistoryPeriod }) {
  return (
    <div className="rh-period">
      <ul className="rh-summary">
        {p.summary.map((line, i) => <li key={i}>{line}</li>)}
      </ul>
      <div className="ex-row"><span>Trips driven</span><span>{p.trips}</span></div>
      <div className="ex-row"><span>Reads kept</span><span>{p.reads}</span></div>
      <div className="ex-row"><span>Days with reads</span><span>{p.days_with_reads}</span></div>
      <div className="ex-row"><span>Sensors with reads</span><span>{p.sensors_read}</span></div>
      <div className="ex-row"><span>Regular passes</span><span>{p.regular.length || "none seen"}</span></div>
      <PlaceRow label="Overnight stay" place={p.places.overnight} />
      <PlaceRow label="Daytime stay" place={p.places.daytime} />
    </div>
  );
}

type State = { loading: boolean; result: History | null; error: string | null };

/** "What a read history could suggest" for one checked route. Schedule and results live in page memory only. */
export default function RouteHistory({ start, end }: { start: Pt; end: Pt }) {
  const [weekdays, setWeekdays] = useState<number[]>([0, 1, 2, 3, 4]);
  const [leave, setLeave] = useState("08:00");
  const [back, setBack] = useState("17:30");
  const [state, setState] = useState<State | null>(null);
  const [shown, setShown] = useState<number | null>(null); // days of the period on screen

  const toggle = (d: number) =>
    setWeekdays((w) => (w.includes(d) ? w.filter((x) => x !== d) : [...w, d].sort((a, b) => a - b)));

  async function run(e: React.FormEvent) {
    e.preventDefault();
    setState({ loading: true, result: null, error: null });
    try {
      const result = await routeHistory(start, end, { weekdays, leave, return: back });
      setState({ loading: false, result, error: null });
      setShown((s) => (s != null && result.periods.some((p) => p.days === s) ? s : result.periods[0]?.days ?? null));
    } catch (err) {
      setState({ loading: false, result: null, error: err instanceof Error ? err.message : String(err) });
    }
  }

  const r = state?.result;
  const period = r?.periods.find((p) => p.days === shown) ?? r?.periods[0];

  return (
    <div className="rh">
      <div className="mr-leg-head">What a read history could suggest</div>
      <div className="nb-note">
        If this route were driven regularly, sensors that record it would build up a history of reads. Pick a usual
        schedule to see what 7 days, 30 days or a year of those reads could suggest.
      </div>
      <form className="rh-form" onSubmit={run}>
        <fieldset className="rh-days">
          <legend>Days driven</legend>
          {DAYS.map((d, i) => (
            <label key={d} title={DAY_NAMES[i]}>
              <input type="checkbox" checked={weekdays.includes(i)} onChange={() => toggle(i)} aria-label={DAY_NAMES[i]} />
              <span aria-hidden="true">{d}</span>
            </label>
          ))}
        </fieldset>
        <div className="rh-times">
          <label>Leave <input type="time" value={leave} required onChange={(e) => setLeave(e.target.value)} /></label>
          <label>Back <input type="time" value={back} required onChange={(e) => setBack(e.target.value)} /></label>
        </div>
        <button type="submit" className="ex-share" disabled={state?.loading || weekdays.length === 0 || !leave || !back}>
          {r || state?.error ? "Update" : "Show what it could suggest"}
        </button>
        {weekdays.length === 0 && <div className="nb-note">Pick at least one day.</div>}
      </form>

      {state?.loading && <div className="nb-note" role="status">Simulating a year of this drive…</div>}
      {state?.error && <div className="error" role="alert">{state.error}</div>}
      {r && period && (
        <div aria-live="polite">
          <div className="rh-tabs" role="group" aria-label="How long reads are kept">
            {r.periods.map((p) => (
              <button key={p.days} className={p.days === period.days ? "on" : ""} aria-pressed={p.days === period.days}
                onClick={() => setShown(p.days)}>
                {periodName(p.days)}
              </button>
            ))}
          </div>
          <Period p={period} />
          <details className="rh-assume">
            <summary>Assumptions</summary>
            <ul>{r.assumptions.map((a, i) => <li key={i}>{a}</li>)}</ul>
          </details>
          <div className="nb-note">
            Each period is the most recent part of one simulated year, so a longer period includes the shorter ones.
            Distances are from the saved start or end point. This was worked out on the server and not stored there.
          </div>
        </div>
      )}
    </div>
  );
}
