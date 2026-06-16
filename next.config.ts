import type { NextConfig } from "next";
import os from "os";

const basePath = process.env.NEXT_PUBLIC_BASE_PATH || "";
const devPort = process.env.PORT || "3020";

/** LAN IPv4 — иначе Next.js блокирует /_next/* при открытии с телефона/другого ПК. */
function getLanDevOrigins(): string[] {
  try {
    const origins = new Set<string>();
    for (const addrs of Object.values(os.networkInterfaces())) {
      if (!addrs) continue;
      for (const addr of addrs) {
        if (addr.family !== "IPv4" || addr.internal) continue;
        origins.add(addr.address);
        origins.add(`${addr.address}:${devPort}`);
      }
    }
    return [...origins];
  } catch {
    return [];
  }
}

const allowedDevOrigins = [
  "127.0.0.1",
  "localhost",
  ...(process.env.DEV_ALLOWED_ORIGINS?.split(",").map((s) => s.trim()).filter(Boolean) ?? []),
  ...(process.env.NODE_ENV !== "production" ? getLanDevOrigins() : []),
];

const nextConfig: NextConfig = {
  ...(process.env.NODE_ENV === "production" ? { output: "export" as const } : {}),
  trailingSlash: true,
  basePath,
  assetPrefix: basePath ? `${basePath}/` : undefined,
  images: { unoptimized: true },
  reactStrictMode: true,
  allowedDevOrigins,
};

export default nextConfig;
