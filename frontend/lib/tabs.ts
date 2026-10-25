import type { KeyboardEvent } from "react";

// Arrow-key movement for a role="tablist" (WAI-ARIA tabs pattern, automatic activation):
// Left/Right (and Up/Down) move to the previous/next tab with wrap-around, Home/End to the
// first/last. The new tab is focused and clicked, so its own onClick does the switching.
// Pair with tabIndex={selected ? 0 : -1} on each tab so Tab moves past the list in one stop.
export function onTabListKeyDown(e: KeyboardEvent<HTMLElement>) {
  const tabs = Array.from(e.currentTarget.querySelectorAll<HTMLElement>('[role="tab"]:not([disabled])'));
  const i = tabs.indexOf(document.activeElement as HTMLElement);
  if (i < 0 || tabs.length < 2) return;
  let next: number;
  switch (e.key) {
    case "ArrowRight": case "ArrowDown": next = (i + 1) % tabs.length; break;
    case "ArrowLeft": case "ArrowUp": next = (i - 1 + tabs.length) % tabs.length; break;
    case "Home": next = 0; break;
    case "End": next = tabs.length - 1; break;
    default: return;
  }
  e.preventDefault();
  tabs[next].focus();
  tabs[next].click();
}

// Roving tabindex for a tab: only the selected tab is in the page's Tab order.
export const tabStop = (selected: boolean) => (selected ? 0 : -1);
