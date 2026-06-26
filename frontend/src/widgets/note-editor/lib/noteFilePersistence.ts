/** Blob URLs are session-only and break after reload; data URLs survive localStorage/API round-trips. */

export function isBlobUrl(url: string | undefined): boolean {
  return typeof url === "string" && url.startsWith("blob:");
}

export function readNoteFileAsDataUrl(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => {
      resolve(typeof reader.result === "string" ? reader.result : "");
    };
    reader.onerror = () => reject(reader.error);
    reader.readAsDataURL(file);
  });
}
