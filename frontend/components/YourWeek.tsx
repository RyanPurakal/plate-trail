"use client";

import { useState } from "react";
import { API_URL, type RunDetail } from "@/lib/api";

type Props = {
  pins: { home: [number, number] | null; work: [number, number] | null };
  pickMode: "home" | "work" | null;
  setPickMode: (m: "home" | "work" | null) => void;
  onResult: (d: RunDetail) => void;
};

const DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

export default function YourWeek({ pins, pickMode, setPickMode, onResult }: Props) {
  const [workdays, setWorkdays] = useState([0, 1, 2, 3, 4]);
  const [leaveHome, setLeaveHome] = useState("07:45");
  const [leaveWork, setLeaveWork] = useState("17:15");
  const [errands, setErrands] = useState(3);
  const [weekend, setWeekend] = useState(2);
  const [weeks, setWeeks] = useState(2);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function run() {
    if (!pins.home) return;
    setBusy(true);
    setError(null);
    try {
      const resp = await fetch(`${API_URL}/yourweek`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          home: { lon: pins.home[0], lat: pins.home[1] },
          work: pins.work ? { lon: pins.work[0], lat: pins.work[1] } : null,
          workdays, leave_home: leaveHome, leave_work: leaveWork,
          errands_per_week: errands, weekend_outings: weekend, weeks,
        }),
      });
      if (!resp.ok) throw new Error((await resp.json()).detail ?? `error ${resp.status}`);
      onResult(await resp.json());
    } catch (e) {
      setError(String((e as Error).message));
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="yourweek">
      <p className="lede">
        Describe a typical week and see what these cameras could read and infer. <b>Nothing you enter is stored</b>:
        the simulation runs only for this reply. Pick points near, not at, your real places if you prefer.
      </p>
      <div className="yw-pick">
        <button className={pickMode === "home" ? "on" : ""} onClick={() => setPickMode(pickMode === "home" ? null : "home")}>
          {pins.home ? "move home" : "set home"} on map
        </button>
        <button className={pickMode === "work" ? "on" : ""} onClick={() => setPickMode(pickMode === "work" ? null : "work")}>
          {pins.work ? "move work" : "set work (optional)"}
        </button>
      </div>
      {pickMode && <div className="nb-note">Click the map to place your {pickMode}.</div>}
      <div className="yw-days">
        {DAYS.map((d, i) => (
          <label key={d} className={workdays.includes(i) ? "on" : ""}>
            <input type="checkbox" checked={workdays.includes(i)}
                   onChange={() => setWorkdays(workdays.includes(i) ? workdays.filter((x) => x !== i) : [...workdays, i].sort())} />
            {d}
          </label>
        ))}
      </div>
      <div className="yw-grid">
        <label>leave home <input type="time" value={leaveHome} onChange={(e) => setLeaveHome(e.target.value)} /></label>
        <label>leave work <input type="time" value={leaveWork} onChange={(e) => setLeaveWork(e.target.value)} /></label>
        <label>weekday errands <input type="number" min={0} max={5} value={errands} onChange={(e) => setErrands(Number(e.target.value))} /></label>
        <label>weekend outings <input type="number" min={0} max={6} value={weekend} onChange={(e) => setWeekend(Number(e.target.value))} /></label>
        <label>weeks <input type="number" min={1} max={4} value={weeks} onChange={(e) => setWeeks(Number(e.target.value))} /></label>
      </div>
      <button className="yw-run" disabled={!pins.home || busy} onClick={run}>
        {busy ? "simulating…" : "What would the cameras learn?"}
      </button>
      {error && <div className="error">{error}</div>}
    </section>
  );
}
