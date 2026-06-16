type FlushFn = () => void | Promise<void>;

let flushFn: FlushFn | null = null;

export function registerAiModelsAutosaveFlush(fn: FlushFn | null): void {
  flushFn = fn;
}

export async function flushAiModelsAutosave(): Promise<void> {
  await flushFn?.();
}
