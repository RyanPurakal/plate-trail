"use client";

import { useEffect, useState } from "react";
import { getHealth, type Health } from "@/lib/api";

// Placeholder shell; the map, read log, and "seen vs. actual" toggle land in step 9.
export default function Home() {
  const [health, setHealth] = useState<Health | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getHealth().then(setHealth).catch((e: Error) => setError(e.message));
  }, []);

  return (
    <main style={{ padding: "2rem", maxWidth: 720 }}>
      <h1>Plate Trail</h1>
      <p style={{ color: "var(--muted)" }}>
        Synthetic drivers, public camera locations, no real plate data.
      </p>
      <p>
        API:{" "}
        {error ? `unreachable (${error})` : health ? `${health.status}, PostGIS ${health.postgis}` : "checking…"}
      </p>
    </main>
  );
}
