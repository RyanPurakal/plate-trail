// Overlapping requests for the same slot of the page (such as the explored area): each start takes a
// ticket, and only the most recently issued ticket may write its result, so a slow earlier answer
// can't replace a newer one.

export type Latest = { start: () => number; isCurrent: (ticket: number) => boolean };

export function latestOnly(): Latest {
  let last = 0;
  return {
    start: () => ++last,
    isCurrent: (ticket) => ticket === last,
  };
}
