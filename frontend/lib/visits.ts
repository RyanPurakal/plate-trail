// Results of the "since your last visit" area checks, kept per saved area.

/** `prev` with each entry replaced by the one in `next` with the same id; order and other entries are kept. */
export function replaceById<T extends { id: string }>(prev: readonly T[], next: readonly T[]): T[] {
  const byId = new Map(next.map((v) => [v.id, v]));
  return prev.map((v) => byId.get(v.id) ?? v);
}
