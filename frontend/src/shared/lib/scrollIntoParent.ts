/** Scroll only inside `scrollParent`, never the window. */
export function ensureVisibleInScrollParent(
  element: HTMLElement,
  scrollParent: HTMLElement,
  margin = 8,
): void {
  const elRect = element.getBoundingClientRect();
  const parentRect = scrollParent.getBoundingClientRect();

  if (elRect.bottom > parentRect.bottom - margin) {
    scrollParent.scrollTop += elRect.bottom - parentRect.bottom + margin;
  }
  if (elRect.top < parentRect.top + margin) {
    scrollParent.scrollTop -= parentRect.top + margin - elRect.top;
  }
}
