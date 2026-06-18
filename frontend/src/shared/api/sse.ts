export function parseSseChunkLines(buffer: string): { events: string[]; rest: string } {
  const parts = buffer.split("\n\n");
  const rest = parts.pop() ?? "";
  return { events: parts.filter(Boolean), rest };
}

export function extractSseText(eventBlock: string): string | null {
  for (const line of eventBlock.split("\n")) {
    if (!line.startsWith("data: ")) continue;
    try {
      const data = JSON.parse(line.slice(6)) as { text?: string };
      if (typeof data.text !== "string") return null;
      return data.text;
    } catch {
      return null;
    }
  }
  return null;
}

export function extractSseMeta(eventBlock: string): Record<string, unknown> | null {
  for (const line of eventBlock.split("\n")) {
    if (!line.startsWith("data: ")) continue;
    try {
      const data = JSON.parse(line.slice(6)) as { meta?: Record<string, unknown> };
      if (!data.meta || typeof data.meta !== "object") return null;
      return data.meta;
    } catch {
      return null;
    }
  }
  return null;
}

/** Дать React отрисовать кадр между чанками (иначе React 18 батчит все setState в один кадр). */
export function yieldToRenderer(): Promise<void> {
  return new Promise((resolve) => {
    if (typeof requestAnimationFrame === "function") {
      requestAnimationFrame(() => resolve());
      return;
    }
    setTimeout(resolve, 0);
  });
}

export type ConsumeSseOptions = {
  paintBetweenChunks?: boolean;
  onMeta?: (meta: Record<string, unknown>) => void;
};

export type ConsumeSseResult = {
  text: string;
  meta: Record<string, unknown> | null;
};

export async function consumeSseTextStream(
  body: ReadableStream<Uint8Array>,
  onChunk: (text: string) => void,
  options: ConsumeSseOptions = {},
): Promise<ConsumeSseResult> {
  const paintBetweenChunks = options.paintBetweenChunks ?? true;
  const reader = body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let full = "";
  let meta: Record<string, unknown> | null = null;

  const flushEvents = async (events: string[]) => {
    for (const event of events) {
      const metaChunk = extractSseMeta(event);
      if (metaChunk) {
        meta = metaChunk;
        options.onMeta?.(metaChunk);
        continue;
      }
      const chunk = extractSseText(event);
      if (chunk == null || chunk === "") continue;
      full += chunk;
      onChunk(chunk);
      if (paintBetweenChunks) {
        await yieldToRenderer();
      }
    }
  };

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const { events, rest } = parseSseChunkLines(buffer);
    buffer = rest;
    await flushEvents(events);
  }

  buffer += decoder.decode();
  if (buffer.trim()) {
    await flushEvents([buffer]);
  }

  return { text: full, meta };
}

export function* chunkTextForStream(text: string, size = 24): Generator<string> {
  for (let offset = 0; offset < text.length; offset += size) {
    yield text.slice(offset, offset + size);
  }
}

export function formatSseData(text: string): string {
  return `data: ${JSON.stringify({ text })}\n\n`;
}

export async function simulateStreamedText(
  text: string,
  onChunk: (text: string) => void,
  options?: { chunkSize?: number; delayMs?: number; paintBetweenChunks?: boolean },
): Promise<string> {
  const chunkSize = options?.chunkSize ?? 16;
  const delayMs = options?.delayMs ?? 32;
  const paintBetweenChunks = options?.paintBetweenChunks ?? true;
  let full = "";
  for (const chunk of chunkTextForStream(text, chunkSize)) {
    await new Promise((resolve) => setTimeout(resolve, delayMs));
    full += chunk;
    onChunk(chunk);
    if (paintBetweenChunks) {
      await yieldToRenderer();
    }
  }
  return full;
}
