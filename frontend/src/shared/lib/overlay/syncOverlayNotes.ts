import { apiV1Path } from "@/shared/config/basePath";
import { apiRequest } from "@/shared/api/httpClient";
import { shouldSyncOverlayToBackend } from "@/shared/lib/overlay/isOverlayAccount";
import { readOverlay } from "@/shared/lib/overlay/overlayStorage";

let syncTimer: ReturnType<typeof setTimeout> | null = null;
let syncInFlight: Promise<void> | null = null;

export function scheduleOverlayNotesSync(): void {
  if (!shouldSyncOverlayToBackend()) return;
  if (syncTimer) clearTimeout(syncTimer);
  syncTimer = setTimeout(() => {
    syncTimer = null;
    void syncOverlayNotesNow();
  }, 800);
}

export async function syncOverlayNotesNow(): Promise<void> {
  if (!shouldSyncOverlayToBackend()) return;
  if (syncInFlight) {
    await syncInFlight;
    return;
  }

  syncInFlight = (async () => {
    const overlay = readOverlay();
    const postSnapshots = Object.values(overlay.posts.upserts).map((post) => ({
      post_id: post.id,
      notes: post.notes ?? [],
    }));

    await apiRequest<void>(apiV1Path("overlay/notes"), {
      method: "PUT",
      body: {
        global_notes: Object.values(overlay.globalNotes.upserts),
        global_removed_ids: overlay.globalNotes.removedIds,
        post_snapshots: postSnapshots,
      },
    });
  })();

  try {
    await syncInFlight;
  } finally {
    syncInFlight = null;
  }
}
