let notePersistFn: (() => void) | null = null;

export function registerNotePersist(fn: (() => void) | null): void {
  notePersistFn = fn;
}

export function runNotePersist(): void {
  notePersistFn?.();
}
