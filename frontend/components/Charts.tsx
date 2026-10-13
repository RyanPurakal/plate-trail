"use client";

import { useState } from "react";

// Dark-mode categorical slots 1-3 from the dataviz reference palette, validated (all pairs) against the
// panel surface #121517: blue, orange, aqua. More than three series should fold or facet instead.
export const SERIES = ["#3987e5", "#d95926", "#199e70"] as const;

type Point = { x: number; y: number };
type Series = { name: string; points: Point[] };

const pct = (v: number) => `${Math.round(v * 100)}%`;

/** Line chart for a share (0-1) against a small integer x. Legend + end labels; crosshair tooltip. */
export function LineChart({ series, xLabel, title }: { series: Series[]; xLabel: string; title: string }) {
  const [hover, setHover] = useState<number | null>(null);
  const W = 400, H = 210, L = 38, R = 64, T = 12, B = 30;
  const xs = [...new Set(series.flatMap((s) => s.points.map((p) => p.x)))].sort((a, b) => a - b);
  if (!xs.length) return null;
  const x = (v: number) => L + ((v - xs[0]) / Math.max(1, xs[xs.length - 1] - xs[0])) * (W - L - R);
  const y = (v: number) => T + (1 - v) * (H - T - B);
  const hx = hover == null ? null : xs[hover];
  // End labels sit right of the plot, pushed apart so converging lines don't overprint.
  const endLabels = series.filter((s) => s.points.length)
    .map((s) => ({ name: s.name, y: y(s.points[s.points.length - 1].y) }))
    .sort((a, b) => a.y - b.y);
  for (let i = 1; i < endLabels.length; i++) endLabels[i].y = Math.max(endLabels[i].y, endLabels[i - 1].y + 11);
  return (
    <figure className="chart">
      <figcaption>{title}</figcaption>
      <div className="legend-row">
        {series.map((s, i) => (
          <span key={s.name}><i style={{ background: SERIES[i] }} />{s.name}</span>
        ))}
      </div>
      <div className="chart-wrap">
        <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label={title}
             onMouseLeave={() => setHover(null)}
             onMouseMove={(e) => {
               const r = (e.currentTarget as SVGSVGElement).getBoundingClientRect();
               const px = ((e.clientX - r.left) / r.width) * W;
               let best = 0;
               xs.forEach((v, i) => { if (Math.abs(x(v) - px) < Math.abs(x(xs[best]) - px)) best = i; });
               setHover(best);
             }}>
          {[0, 0.25, 0.5, 0.75, 1].map((g) => (
            <g key={g}>
              <line x1={L} x2={W - R} y1={y(g)} y2={y(g)} className="grid" />
              <text x={L - 6} y={y(g) + 3} className="tick" textAnchor="end">{pct(g)}</text>
            </g>
          ))}
          {xs.map((v) => <text key={v} x={x(v)} y={H - B + 14} className="tick" textAnchor="middle">{v}</text>)}
          <text x={(L + W - R) / 2} y={H - 3} className="axis-label" textAnchor="middle">{xLabel}</text>
          {hx != null && <line x1={x(hx)} x2={x(hx)} y1={T} y2={H - B} className="crosshair" />}
          {series.map((s, i) => (
            <g key={s.name}>
              <polyline fill="none" stroke={SERIES[i]} strokeWidth={2} strokeLinejoin="round"
                        points={s.points.map((p) => `${x(p.x)},${y(p.y)}`).join(" ")} />
              {s.points.map((p) => (
                <circle key={p.x} cx={x(p.x)} cy={y(p.y)} r={hx === p.x ? 5 : 4} fill={SERIES[i]}
                        stroke="#121517" strokeWidth={2} />
              ))}
            </g>
          ))}
          {endLabels.map((l) => (
            <text key={l.name} x={W - R + 6} y={l.y + 3} className="end-label">{l.name}</text>
          ))}
        </svg>
        {hx != null && (
          <div className="tooltip" style={{ left: `${(x(hx) / W) * 100}%` }}>
            <div className="tt-title">{xLabel}: {hx}</div>
            {series.map((s, i) => {
              const p = s.points.find((q) => q.x === hx);
              return p ? <div key={s.name}><i style={{ background: SERIES[i] }} />{s.name} <b>{pct(p.y)}</b></div> : null;
            })}
          </div>
        )}
      </div>
    </figure>
  );
}

/** Horizontal bars for a share (0-1) per category. One series, so no legend; value at the bar end. */
export function BarChart({ rows, title, selected, onSelect }: {
  rows: { key: string; label: string; value: number }[];
  title: string;
  selected?: string | null;
  onSelect?: (key: string) => void;
}) {
  const [hover, setHover] = useState<string | null>(null);
  return (
    <figure className="chart">
      <figcaption>{title}</figcaption>
      <div className="bars" role="list">
        {rows.map((r) => (
          <button key={r.key} role="listitem" className={`bar-row ${selected === r.key ? "sel" : ""} ${hover === r.key ? "hov" : ""}`}
                  onMouseEnter={() => setHover(r.key)} onMouseLeave={() => setHover(null)}
                  onClick={() => onSelect?.(r.key)} title={`${r.label}: ${pct(r.value)}`}>
            <span className="bar-label">{r.label}</span>
            <span className="bar-track">
              <span className="bar-fill" style={{ width: `${Math.max(r.value * 100, 0.5)}%` }} />
            </span>
            <span className="bar-value">{pct(r.value)}</span>
          </button>
        ))}
      </div>
    </figure>
  );
}
