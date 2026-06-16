/**
 * Export MSW seed stores to backend JSON fixtures (single source of truth).
 * Run from repo root: npm run export-seed-fixtures -w tg-platform-frontend
 */
import { mkdirSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import { createInitialMswStore } from "../src/shared/api/msw/store";
import { createPresentationMswStore } from "../src/shared/data/presentation-seed";

const scriptDir = dirname(fileURLToPath(import.meta.url));
const fixturesDir = join(scriptDir, "../../backend/fixtures");

type MswStore = ReturnType<typeof createInitialMswStore>;

function exportStore(name: string, store: MswStore): void {
  const payload = {
    posts: store.posts,
    globalChats: store.globalChats,
    globalNotes: store.globalNotes,
    profile: {
      channel: store.channelProfile,
      ai: store.aiProfile,
      telegram: store.telegramProfile,
    },
  };
  writeFileSync(join(fixturesDir, `${name}.json`), `${JSON.stringify(payload, null, 2)}\n`);
}

mkdirSync(fixturesDir, { recursive: true });
exportStore("presentation", createPresentationMswStore());
exportStore("demo-full", createInitialMswStore());
console.log(`Exported seed fixtures to ${fixturesDir}`);
