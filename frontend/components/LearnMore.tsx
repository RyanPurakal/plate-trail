"use client";

export type Topic = "sensors" | "retention" | "unicity";

// Short, neutral explainers linked from where each one is relevant. Figures come from docs/findings.md.
const TOPICS: Record<Topic, { title: string; body: string[] }> = {
  sensors: {
    title: "What fixed sensors record",
    body: [
      "A fixed license-plate reader is a camera mounted at one spot, often on a pole or traffic signal. When a vehicle passes in view, it typically stores the plate text, the time, the sensor's location and a photo.",
      "One read says a vehicle was at that spot at that moment. It does not by itself say where the trip started or ended.",
      "Many sensors face one direction of travel, so they may record a trip one way but not the way back. Public map data records where some sensors are; it can be incomplete or out of date.",
    ],
  },
  retention: {
    title: "How retention length changes what can be inferred",
    body: [
      "Retention is how long reads are kept before they are deleted. A few reads from one day show where a car was at those times.",
      "Over weeks, the same sensors at similar times become a pattern: which roads are used regularly, around when, and roughly where trips tend to begin and end each day.",
      "Longer retention makes those patterns clearer and more confident. Shorter retention leaves fewer reads to draw on, so less can be suggested. The results here come from a simulation with stated assumptions, not real records.",
    ],
  },
  unicity: {
    title: "Why a few reads can be distinctive",
    body: [
      "Unicity asks how many points it takes to tell one trace apart from everyone else's, even with names or plates removed (after de Montjoye et al., 2013).",
      "In the example study of simulated drivers in Edison and New Brunswick, NJ, two sightings (a sensor and an hour each) were enough to single out about 80% of drivers in a crowd of 1,000, and four sightings singled out nearly everyone who had four.",
      "Real crowds are larger, so these simulated shares are upper bounds. The point is that a short list of places and times is often unique to one person.",
    ],
  },
};

/** "Learn more" link that opens a short explainer in place. */
export default function LearnMore({ topic }: { topic: Topic }) {
  const t = TOPICS[topic];
  return (
    <details className="learn">
      <summary>Learn more: {t.title.charAt(0).toLowerCase() + t.title.slice(1)}</summary>
      <div className="learn-body">
        {t.body.map((p, i) => <p key={i}>{p}</p>)}
      </div>
    </details>
  );
}
