"use client";

import { useEffect, useRef } from "react";
import type { AreaResult } from "@/lib/api";
import { compassWord, osmUrl, parseDirections, shortDate } from "@/lib/area";
import LearnMore from "./LearnMore";

type Props = {
  area: AreaResult;
  selectedId: string;
  onSelect: (id: string | null) => void; // another sensor in the area, or null to close
};

/** Sidebar card for one sensor picked on the map: what the public data says about it, credited by source. */
export default function SensorDetail({ area, selectedId, onSelect }: Props) {
  const card = useRef<HTMLElement>(null);
  const features = area.sensors.features;
  const index = features.findIndex((f) => f.properties.id === selectedId);

  // A sensor picked on the map (or with "Step through sensors", which then disappears) moves focus to this card
  // so keyboard and screen-reader users land on its details; Previous/Next keep focus where it is.
  useEffect(() => {
    const el = card.current;
    if (!el) return;
    el.scrollIntoView({ block: "nearest", behavior: "smooth" });
    if (!el.contains(document.activeElement)) el.focus({ preventScroll: true });
  }, [selectedId]);

  if (index < 0) return null;
  const f = features[index];
  const p = f.properties;
  const src = area.summary.sources.find((s) => s.id === p.source);
  const dirs = parseDirections(p.directions_deg);
  const [lon, lat] = f.geometry.coordinates;
  const edited = shortDate(p.last_edited);
  const fetched = shortDate(src?.fetched_at ?? null);
  const link = osmUrl(p.id);
  const step = (d: number) => onSelect(features[(index + d + features.length) % features.length].properties.id);

  return (
    <section ref={card} className="naive sensor-card" tabIndex={-1} aria-label={`Selected sensor, ${index + 1} of ${features.length}`}>
      <div className="nb-head">
        <span>Sensor {index + 1} of {features.length}</span>
        <button className="ex-share" onClick={() => onSelect(null)} aria-label="Close sensor details">Close</button>
      </div>
      <div className="ex-row">
        <span>Direction</span>
        <span>
          {dirs.length
            ? dirs.map((d) => `${compassWord(d)} (${Math.round(d)}°)`).join(", ")
            : p.direction_raw ? `"${p.direction_raw}"` : "not recorded"}
        </span>
      </div>
      <div className="ex-row"><span>Location</span><span>{lat.toFixed(5)}, {lon.toFixed(5)}</span></div>
      <div className="ex-row">
        <span>Source</span>
        <span>{src?.name ?? p.source}{src?.license && <span className="dim"> · {src.license}</span>}</span>
      </div>
      {edited && <div className="ex-row"><span>Last edited in OSM</span><span>{edited}</span></div>}
      {fetched && (
        <div className="ex-row"><span>{p.source === "osm" ? "Data fetched" : "File updated"}</span><span>{fetched}</span></div>
      )}
      <div className="nb-note">
        {dirs.length
          ? "The direction is the way the sensor faces as recorded in the data. It suggests which direction of travel it records, but the data does not say which lanes it covers."
          : p.direction_raw
            ? "The direction is recorded as text rather than a compass bearing, so which way it faces is unclear."
            : "No direction is recorded, so this sensor may record traffic in either direction."}
        {p.source === "osm" && " Positions in OpenStreetMap are added by volunteers and may be approximate or out of date."}
      </div>
      <LearnMore topic="sensors" />
      <div className="ex-foot">
        <span className="sensor-nav">
          <button className="ex-share" onClick={() => step(-1)} disabled={features.length < 2}>Previous</button>
          <button className="ex-share" onClick={() => step(1)} disabled={features.length < 2}>Next</button>
        </span>
        {link && <a href={link} target="_blank" rel="noreferrer">View in OpenStreetMap</a>}
      </div>
    </section>
  );
}
