/** Normalize a note body for stable snapshot/dirty comparison. */
export function canonicalNoteBody(body: string): string {
  return (body ?? "")
    .replace(/\r\n/g, "\n")
    .replace(/\n{3,}/g, "\n\n")
    .trimEnd();
}
