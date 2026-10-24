"use client";

import { shortDate } from "@/lib/area";
import type { SnapshotChange } from "@/lib/snapshots";

type Props = {
  change: SnapshotChange | null; // null on a first look
  what: string; // "in this area" / "along this route"
  sourceName?: (id: string) => string;
  onPickAdded?: (id: string) => void; // show a newly listed sensor
};

const plural = (n: number, word: string) => `${n} ${word}${n === 1 ? "" : "s"}`;

/** "Since your last look": sensors newly listed or no longer listed, compared with this browser's last look. */
export default function ChangeNote({ change, what, sourceName = (s) => s, onPickAdded }: Props) {
  if (!change) {
    return (
      <div className="nb-note">
        First look {what} from this browser. The sensor list is kept on this device so a later look can show what changed.
      </div>
    );
  }
  const when = shortDate(change.since) ?? "an earlier visit";
  const same = !change.added.length && !change.removed.length;
  return (
    <div className="ex-change" aria-live="polite">
      <div className="ex-k">Since your last look ({when})</div>
      {same ? (
        <div>No sensors added or removed {what}.</div>
      ) : (
        <ul>
          {change.added.length > 0 && <li>{plural(change.added.length, "sensor")} newly listed</li>}
          {change.removed.length > 0 && <li>{plural(change.removed.length, "sensor")} no longer listed</li>}
        </ul>
      )}
      {change.updated.length > 0 && (
        <div className="dim">Updated data: {change.updated.map(sourceName).join(", ")}.</div>
      )}
      {onPickAdded && change.added.length > 0 && (
        <div className="ex-change-new">
          {change.added.slice(0, 5).map((id, i) => (
            <button key={id} className="ex-share" onClick={() => onPickAdded(id)}>Show new sensor {i + 1}</button>
          ))}
        </div>
      )}
      <div className="dim">
        Changes reflect edits to the data sources, which can mean a sensor was installed, removed, or only now mapped.
      </div>
    </div>
  );
}
