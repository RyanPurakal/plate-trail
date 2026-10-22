"use client";

import { useEffect, useState } from "react";
import { MAX_NAME, MAX_ROUTES, nextRouteName, straightKm, type Pt, type SavedRoute } from "@/lib/routes";

export type RouteDraft = { start: Pt | null; end: Pt | null };

type Props = {
  routes: SavedRoute[];
  storageOk: boolean; // false when the browser refused to save (private mode, blocked storage)
  draft: RouteDraft | null; // non-null while a new route's points are being placed on the map
  onAdd: () => void;
  onCancel: () => void;
  onSave: (name: string) => void;
  shownId: string | null; // route drawn on the map
  onShow: (id: string | null) => void;
  onRename: (id: string, name: string) => void;
  onDelete: (id: string) => void;
  onClearAll: () => void;
};

const km = (r: { start: Pt; end: Pt }) => `${straightKm(r.start, r.end).toFixed(1)} km apart`;

/** Sidebar list of the routes saved in this browser, with add / rename / delete. */
export default function MyRoutes({ routes, storageOk, draft, onAdd, onCancel, onSave, shownId, onShow, onRename, onDelete, onClearAll }: Props) {
  const [name, setName] = useState("");
  const [editing, setEditing] = useState<{ id: string; name: string } | null>(null);
  const [confirm, setConfirm] = useState<string | null>(null); // route id, or "all"

  useEffect(() => {
    if (draft?.end) setName(nextRouteName(routes));
  }, [draft?.end, routes]);

  function save(e: React.FormEvent) {
    e.preventDefault();
    onSave(name);
  }

  function rename(e: React.FormEvent) {
    e.preventDefault();
    if (editing) onRename(editing.id, editing.name);
    setEditing(null);
  }

  const full = routes.length >= MAX_ROUTES;

  return (
    <section className="naive my-routes" aria-labelledby="mr-title">
      <div className="nb-head">
        <span id="mr-title">My routes</span>
        <span className="nb-badge">on this device</span>
      </div>
      <div className="nb-note">
        Routes are saved only in this browser&apos;s local storage. They are not sent to or stored on the server, and
        clearing site data removes them.
      </div>
      {!storageOk && (
        <div className="error" role="alert">This browser is not allowing local storage, so routes last only until the page is closed.</div>
      )}

      {routes.length === 0 && !draft && (
        <div className="nb-note">No routes yet. Add one you drive often, such as a commute or a school run.</div>
      )}

      {routes.length > 0 && (
        <ul className="mr-list">
          {routes.map((r) => (
            <li key={r.id} className={shownId === r.id ? "on" : ""}>
              {editing?.id === r.id ? (
                <form className="mr-edit" onSubmit={rename}>
                  <label className="sr-only" htmlFor={`mr-name-${r.id}`}>New name for {r.name}</label>
                  <input id={`mr-name-${r.id}`} value={editing.name} maxLength={MAX_NAME} autoFocus
                    onChange={(e) => setEditing({ id: r.id, name: e.target.value })}
                    onKeyDown={(e) => { if (e.key === "Escape") setEditing(null); }} />
                  <button type="submit" className="ex-share" disabled={!editing.name.trim()}>Save</button>
                  <button type="button" className="ex-share" onClick={() => setEditing(null)}>Cancel</button>
                </form>
              ) : (
                <>
                  <button className="mr-name" aria-pressed={shownId === r.id} onClick={() => onShow(shownId === r.id ? null : r.id)}>
                    {r.name}<span className="dim"> · {km(r)}</span>
                  </button>
                  {confirm === r.id ? (
                    <span className="mr-tools">
                      <button className="ex-share" onClick={() => { onDelete(r.id); setConfirm(null); }}>Delete</button>
                      <button className="ex-share" onClick={() => setConfirm(null)}>Keep</button>
                    </span>
                  ) : (
                    <span className="mr-tools">
                      <button className="ex-share" aria-label={`Rename ${r.name}`} onClick={() => setEditing({ id: r.id, name: r.name })}>Rename</button>
                      <button className="ex-share" aria-label={`Delete ${r.name}`} onClick={() => setConfirm(r.id)}>Delete</button>
                    </span>
                  )}
                </>
              )}
            </li>
          ))}
        </ul>
      )}

      {draft ? (
        <div className="mr-draft" aria-live="polite">
          {!draft.start && <div className="nb-note">Click the map where the route starts. Esc cancels.</div>}
          {draft.start && !draft.end && <div className="nb-note">Now click where the route ends.</div>}
          {draft.start && draft.end && (
            <form className="mr-edit" onSubmit={save}>
              <label htmlFor="mr-new">Name this route</label>
              <input id="mr-new" value={name} maxLength={MAX_NAME} autoFocus placeholder="e.g. Commute"
                onChange={(e) => setName(e.target.value)} />
              <button type="submit" className="ex-share">Save route</button>
            </form>
          )}
          {draft.start && draft.end && (
            <div className="nb-note">The line on the map joins the two points; the roads the route takes are worked out in a later step.</div>
          )}
          <button className="ex-share" onClick={onCancel}>Cancel</button>
        </div>
      ) : (
        <div className="ex-actions">
          <button className="ex-share" onClick={onAdd} disabled={full}>Add a route</button>
          {routes.length > 0 && (confirm === "all" ? (
            <>
              <button className="ex-share" onClick={() => { onClearAll(); setConfirm(null); }}>Remove all</button>
              <button className="ex-share" onClick={() => setConfirm(null)}>Keep</button>
            </>
          ) : (
            <button className="ex-share" onClick={() => setConfirm("all")}>Remove all from this device</button>
          ))}
        </div>
      )}
      {full && !draft && <div className="nb-note">Up to {MAX_ROUTES} routes can be saved. Delete one to add another.</div>}
    </section>
  );
}
