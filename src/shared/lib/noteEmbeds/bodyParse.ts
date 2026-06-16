import { EMBED_RE } from "@/shared/lib/noteEmbeds/types";
import type { NoteBodySegment } from "@/shared/lib/noteEmbeds/types";

export function embedToken(name: string) {
  return `[${name}]`;
}

export function parseNoteBody(body: string): NoteBodySegment[] {
  if (!body) return [{ type: "text", content: "" }];
  const segments: NoteBodySegment[] = [];
  let last = 0;
  for (const m of body.matchAll(EMBED_RE)) {
    const index = m.index ?? 0;
    if (index > last) {
      segments.push({ type: "text", content: body.slice(last, index) });
    }
    segments.push({ type: "embed", name: m[1] });
    last = index + m[0].length;
  }
  if (last < body.length) {
    segments.push({ type: "text", content: body.slice(last) });
  }
  return segments.length > 0 ? segments : [{ type: "text", content: "" }];
}

export function serializeNoteBody(segments: NoteBodySegment[]): string {
  return segments.map((s) => (s.type === "text" ? s.content : embedToken(s.name))).join("");
}
