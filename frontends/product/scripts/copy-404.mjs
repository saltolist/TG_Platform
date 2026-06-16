import { copyFileSync, existsSync } from "node:fs";
import { join } from "node:path";

const outDir = join(process.cwd(), "out");
const index = join(outDir, "index.html");
const dest = join(outDir, "404.html");

if (!existsSync(index)) {
  console.warn("[copy-404] skip: out/index.html not found (run next build first)");
  process.exit(0);
}

copyFileSync(index, dest);
console.log("[copy-404] out/404.html ← index.html (GitHub Pages SPA fallback)");
