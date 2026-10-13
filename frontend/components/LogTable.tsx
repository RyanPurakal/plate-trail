"use client";

import type { Pass, Read } from "@/lib/api";
import { stamp } from "@/lib/format";
import type { Mode } from "./MapView";

type Props = {
  mode: Mode;
  reads: Read[];
  passes: Pass[];
  focusLabel: string | null;
  onFocus: (label: string | null) => void;
};

function passFate(p: Pass): { text: string; cls: string } {
  if (!p.captured) {
    if (p.match_reason === "missed_undirected_worst") return { text: "not captured (undirected)", cls: "fate-skip" };
    return { text: "wrong direction", cls: "fate-skip" };
  }
  if (p.noise_outcome === "read") return { text: "read", cls: "fate-read" };
  if (p.noise_outcome === "downtime") return { text: "camera down", cls: "fate-lost" };
  return { text: "missed read", cls: "fate-lost" };
}

const eventLabel = (p: Pass) => (p.event === "road" ? p.road_name || "unnamed road" : `lot ${p.event}`);

export default function LogTable({ mode, reads, passes, focusLabel, onFocus }: Props) {
  const readByPass = new Map(reads.map((r) => [r.pass_id, r]));
  const toggle = (label: string) => onFocus(focusLabel === label ? null : label);

  if (mode === "saw") {
    return (
      <div className="log">
        <div className="log-caption">
          Read log as recorded: {reads.length} read{reads.length === 1 ? "" : "s"}. Times and plates exactly as
          the cameras reported them.
        </div>
        <table>
          <thead>
            <tr><th>#</th><th>Recorded</th><th>Camera</th><th>Plate</th></tr>
          </thead>
          <tbody>
            {reads.map((r, i) => (
              <tr key={r.id} className={focusLabel === r.camera_label ? "focused" : ""} onClick={() => toggle(r.camera_label)}
                  style={{ animationDelay: `${Math.min(i, 30) * 18}ms` }}>
                <td className="num">{r.read_seq + 1}</td>
                <td>{stamp(r.time)}</td>
                <td className="cam">{r.camera_label.replace("node/", "")}</td>
                <td className="plate"><span className="state">{r.plate_state}</span> {r.plate}</td>
              </tr>
            ))}
            {!reads.length && <tr><td colSpan={4} className="empty">No camera recorded this driver.</td></tr>}
          </tbody>
        </table>
      </div>
    );
  }

  return (
    <div className="log">
      <div className="log-caption">
        Every camera the routes passed: {passes.length} pass{passes.length === 1 ? "" : "es"}, and what became of each.
      </div>
      <table>
        <thead>
          <tr><th>Trip</th><th>True time</th><th>Where</th><th>Outcome</th></tr>
        </thead>
        <tbody>
          {passes.map((p, i) => {
            const fate = passFate(p);
            const r = readByPass.get(p.id);
            return (
              <tr key={p.id} className={focusLabel === p.camera_label ? "focused" : ""} onClick={() => toggle(p.camera_label)}
                  style={{ animationDelay: `${Math.min(i, 30) * 18}ms` }}>
                <td className="num">{p.trip_seq + 1}</td>
                <td>{stamp(p.time)}</td>
                <td className="where">
                  {eventLabel(p)}
                  {p.travel_bearing_deg != null && <span className="dim"> · {Math.round(p.travel_bearing_deg)}°</span>}
                </td>
                <td>
                  <span className={`fate ${fate.cls}`}>{fate.text}</span>
                  {r?.misread && <span className="fate fate-mis" title={`recorded as ${r.plate_state} ${r.plate}`}>misread → {r.plate_state} {r.plate}</span>}
                </td>
              </tr>
            );
          })}
          {!passes.length && <tr><td colSpan={4} className="empty">The routes passed no cameras.</td></tr>}
        </tbody>
      </table>
    </div>
  );
}
