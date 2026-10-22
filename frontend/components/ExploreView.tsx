"use client";

import { useState } from "react";
import type { AreaResult } from "@/lib/api";
import { shortDate } from "@/lib/area";

type Props = {
  area: AreaResult | null;
  loading: boolean;
  error: string | null;
  shrunk: boolean; // the last request was cut down to the API's maximum box size
  onExplore: () => void; // explore the current map view
};

const plural = (n: number, word: string) => `${n} ${word}${n === 1 ? "" : "s"}`;

/** Sidebar for the Explore view: action button plus a plain-language summary of the area. */
export default function ExploreView({ area, loading, error, shrunk, onExplore }: Props) {
  const [copied, setCopied] = useState(false);
  const s = area?.summary;

  function share() {
    navigator.clipboard?.writeText(window.location.href).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    }).catch(() => {});
  }

  return (
    <div className="explore">
      <section className="picker">
        <p className="ex-lede">
          Move the map to any area, then load the fixed sensors (such as license-plate readers) recorded there in
          public map data.
        </p>
        <button className="ex-go" onClick={onExplore} disabled={loading}>
          {loading ? "Loading public map data…" : area ? "Explore the current view" : "Explore this view"}
        </button>
        {shrunk && !loading && (
          <div className="nb-note">The view was larger than the 0.5° limit, so its centre was used. Zoom in to choose the exact area.</div>
        )}
      </section>

      {error && <div className="error" role="alert">{error}</div>}

      {!area && !loading && !error && (
        <section className="naive">
          <div className="nb-note">
            No area loaded yet. The box you explore is saved in the page address, so you can bookmark or share it.
            It contains only map coordinates.
          </div>
        </section>
      )}

      {area && s && (
        <section className="naive area-card" aria-live="polite">
          <div className="nb-head">
            <span>Area summary</span>
            <span className="nb-badge">public data</span>
          </div>
          <div className="ex-count">
            {s.sensor_count}<small> fixed sensor{s.sensor_count === 1 ? "" : "s"} mapped</small>
          </div>
          {s.sensor_count === 0 ? (
            <div className="nb-note">
              None are recorded in the sources below for this box. Public map data can be incomplete, so this means
              none have been mapped, not necessarily that none exist.
            </div>
          ) : (
            <>
              <div className="ex-row"><span>Area</span><span>{s.area_km2.toLocaleString()} km²</span></div>
              <div className="ex-row"><span>Density</span><span>{s.sensors_per_100km2 ?? "–"} per 100 km²</span></div>
              <div className="ex-row">
                <span>Direction known</span><span>{s.with_direction} of {s.sensor_count}</span>
              </div>
              <div className="nb-note">
                A sensor with a known direction records vehicles travelling one way past it. Click a sensor on the map
                for details.
              </div>
            </>
          )}

          <div className="ex-sources">
            <div className="ex-k">Data sources</div>
            {s.sources.map((src) => {
              const fetched = shortDate(src.fetched_at);
              const edit = shortDate(src.latest_edit);
              return (
                <div key={src.id} className="ex-src">
                  <div>
                    {src.url ? <a href={src.url} target="_blank" rel="noreferrer">{src.name}</a> : src.name}
                    {src.license && <span className="dim"> · {src.license}</span>}
                    <span className="dim"> · {plural(src.count, "sensor")}</span>
                  </div>
                  <div className="dim">
                    {src.id === "osm"
                      ? <>{fetched ? `fetched ${fetched}` : "not fetched yet"}{edit && ` · latest edit here ${edit}`}</>
                      : fetched && `file updated ${fetched}`}
                  </div>
                </div>
              );
            })}
          </div>

          <div className="ex-foot">
            <span className="dim">Box {area.bbox.map((v) => v.toFixed(2)).join(", ")}</span>
            <button className="ex-share" onClick={share}>{copied ? "Link copied" : "Copy link to this area"}</button>
          </div>
        </section>
      )}
    </div>
  );
}
