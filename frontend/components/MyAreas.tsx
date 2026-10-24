"use client";

import { useEffect, useMemo, useState } from "react";
import { shortDate, type BBox } from "@/lib/area";
import { findArea, MAX_AREAS, nextAreaName, type SavedArea } from "@/lib/areas";
import { MAX_NAME } from "@/lib/routes";
import { areaKey, loadSnapshots } from "@/lib/snapshots";

type Props = {
  areas: SavedArea[];
  storageOk: boolean; // false when the browser refused to save (private mode, blocked storage)
  current: BBox | null; // box of the loaded area, if any
  loading: boolean;
  onOpen: (bbox: BBox) => void;
  onSave: (name: string) => void; // save the loaded area
  onRename: (id: string, name: string) => void;
  onDelete: (id: string) => void;
  onClearAll: () => void;
};

/** Sidebar list of areas saved in this browser: open one again, save the loaded area, rename or delete. */
export default function MyAreas({ areas, storageOk, current, loading, onOpen, onSave, onRename, onDelete, onClearAll }: Props) {
  const [naming, setNaming] = useState<string | null>(null); // name being typed for the loaded area
  const [editing, setEditing] = useState<{ id: string; name: string } | null>(null);
  const [confirm, setConfirm] = useState<string | null>(null); // area id, or "all"

  const saved = current ? findArea(areas, current) : undefined;
  useEffect(() => setNaming(null), [current]);
  // When each saved area was last looked at from this browser; re-read whenever the list or loaded area changes.
  const lastSeen = useMemo(() => {
    const snaps = loadSnapshots();
    return Object.fromEntries(areas.map((a) => [a.id, shortDate(snaps[areaKey(a.bbox)]?.seen ?? null)]));
  }, [areas, current]);

  function save(e: React.FormEvent) {
    e.preventDefault();
    if (naming !== null) onSave(naming);
    setNaming(null);
  }

  function rename(e: React.FormEvent) {
    e.preventDefault();
    if (editing) onRename(editing.id, editing.name);
    setEditing(null);
  }

  const full = areas.length >= MAX_AREAS;

  return (
    <section className="naive my-routes" aria-labelledby="ma-title">
      <div className="nb-head">
        <span id="ma-title">My areas</span>
        <span className="nb-badge">on this device</span>
      </div>
      <div className="nb-note">
        Saved areas are kept only in this browser&apos;s local storage, as a map box and a name. Open one again later to
        see what changed since your last look.
      </div>
      {!storageOk && (
        <div className="error" role="alert">This browser is not allowing local storage, so areas last only until the page is closed.</div>
      )}

      {areas.length === 0 && (
        <div className="nb-note">No saved areas yet. Explore an area you care about, such as where you live or work, then save it.</div>
      )}

      {areas.length > 0 && (
        <ul className="mr-list">
          {areas.map((a) => (
            <li key={a.id} className={saved?.id === a.id ? "on" : ""}>
              {editing?.id === a.id ? (
                <form className="mr-edit" onSubmit={rename}>
                  <label className="sr-only" htmlFor={`ma-name-${a.id}`}>New name for {a.name}</label>
                  <input id={`ma-name-${a.id}`} value={editing.name} maxLength={MAX_NAME} autoFocus
                    onChange={(e) => setEditing({ id: a.id, name: e.target.value })}
                    onKeyDown={(e) => { if (e.key === "Escape") setEditing(null); }} />
                  <button type="submit" className="ex-share" disabled={!editing.name.trim()}>Save</button>
                  <button type="button" className="ex-share" onClick={() => setEditing(null)}>Cancel</button>
                </form>
              ) : (
                <>
                  <button className="mr-name" aria-current={saved?.id === a.id ? "true" : undefined} disabled={loading}
                    onClick={() => onOpen(a.bbox)}>
                    {a.name}
                    <span className="dim"> · {lastSeen[a.id] ? `last look ${lastSeen[a.id]}` : "not looked at yet"}</span>
                  </button>
                  {confirm === a.id ? (
                    <span className="mr-tools">
                      <button className="ex-share" onClick={() => { onDelete(a.id); setConfirm(null); }}>Delete</button>
                      <button className="ex-share" onClick={() => setConfirm(null)}>Keep</button>
                    </span>
                  ) : (
                    <span className="mr-tools">
                      <button className="ex-share" aria-label={`Rename ${a.name}`} onClick={() => setEditing({ id: a.id, name: a.name })}>Rename</button>
                      <button className="ex-share" aria-label={`Delete ${a.name}`} onClick={() => setConfirm(a.id)}>Delete</button>
                    </span>
                  )}
                </>
              )}
            </li>
          ))}
        </ul>
      )}

      {current && !saved && naming !== null && (
        <form className="mr-edit" onSubmit={save}>
          <label htmlFor="ma-new">Name this area</label>
          <input id="ma-new" value={naming} maxLength={MAX_NAME} autoFocus placeholder="e.g. Home area"
            onChange={(e) => setNaming(e.target.value)} onKeyDown={(e) => { if (e.key === "Escape") setNaming(null); }} />
          <button type="submit" className="ex-share">Save area</button>
          <button type="button" className="ex-share" onClick={() => setNaming(null)}>Cancel</button>
        </form>
      )}

      <div className="ex-actions">
        {current && !saved && naming === null && (
          <button className="ex-share" onClick={() => setNaming(nextAreaName(areas))} disabled={full || loading}>Save this area</button>
        )}
        {saved && <span className="dim">The loaded area is saved as {saved.name}.</span>}
        {areas.length > 0 && (confirm === "all" ? (
          <>
            <button className="ex-share" onClick={() => { onClearAll(); setConfirm(null); }}>Remove all</button>
            <button className="ex-share" onClick={() => setConfirm(null)}>Keep</button>
          </>
        ) : (
          <button className="ex-share" onClick={() => setConfirm("all")}>Remove all from this device</button>
        ))}
      </div>
      {full && current && !saved && <div className="nb-note">Up to {MAX_AREAS} areas can be saved. Delete one to add another.</div>}
    </section>
  );
}
