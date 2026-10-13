// MapLibre GL 6 locates its web worker relative to its own module URL. Next.js
// renames and relocates bundled files, so the worker is never found and the map
// silently never finishes loading. Serve the worker as a static file instead and
// point maplibregl.setWorkerUrl at it (see components/MapView.tsx).
import { copyFileSync, mkdirSync } from "node:fs";

mkdirSync("public", { recursive: true });
copyFileSync("node_modules/maplibre-gl/dist/maplibre-gl-worker.mjs", "public/maplibre-gl-worker.mjs");
console.log("copied maplibre-gl-worker.mjs to public/");
