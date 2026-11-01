"use client";

import { useRef, useState } from "react";
import { MAX_BACKUP_BYTES, parseBackup, type Backup } from "@/lib/backup";

type Props = {
  hasSaved: boolean; // any saved route or area to put in a file
  onExport: () => string; // file text for what is saved here
  onImport: (file: Backup) => string; // adds the file's items; returns a sentence saying what happened
};

/** Sidebar card: save routes and areas to a file, and add them from one in another browser. */
export default function MoveData({ hasSaved, onExport, onImport }: Props) {
  const picker = useRef<HTMLInputElement>(null);
  const [note, setNote] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  function saveFile() {
    const url = URL.createObjectURL(new Blob([onExport()], { type: "application/json" }));
    const link = document.createElement("a");
    link.href = url;
    link.download = `plate-trail-my-data-${new Date().toLocaleDateString("en-CA")}.json`; // en-CA reads YYYY-MM-DD, local date
    link.click();
    URL.revokeObjectURL(url);
    setError(null);
    setNote("Your browser is saving the file. It holds your routes' start and end points, so keep it somewhere private.");
  }

  async function addFile(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    e.target.value = ""; // so picking the same file again still fires a change
    if (!file) return;
    setNote(null);
    setError(null);
    const backup = file.size <= MAX_BACKUP_BYTES ? parseBackup(await file.text().catch(() => "")) : null;
    if (backup) setNote(onImport(backup));
    else setError("That file could not be read as saved Plate Trail routes and areas.");
  }

  return (
    <section className="naive my-routes" aria-labelledby="md-title">
      <div className="nb-head">
        <span id="md-title">Move to another browser</span>
        <span className="nb-badge">on this device</span>
      </div>
      <div className="nb-note">
        Routes and areas live only in this browser, so clearing its data removes them. Save them to a file to keep a copy
        or to add them in another browser. The file is made and read on this device and is never uploaded.
      </div>
      <div className="ex-actions">
        <button className="ex-share" onClick={saveFile} disabled={!hasSaved}>Save to a file</button>
        <button className="ex-share" onClick={() => picker.current?.click()}>Add from a file</button>
        <input ref={picker} type="file" accept="application/json,.json" hidden onChange={addFile} />
      </div>
      {!hasSaved && <div className="nb-note">Nothing is saved here yet, so there is nothing to put in a file.</div>}
      <div role="status">{note && <div className="nb-note">{note}</div>}</div>
      {error && <div className="error" role="alert">{error}</div>}
    </section>
  );
}
