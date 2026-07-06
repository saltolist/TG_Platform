"use client";

import { EmojiPreviewError, fetchEmojiPreview } from "@/shared/lib/telegram/emojiPreviewClient";

type LottiePlayer = {
  loadAnimation: (options: {
    container: Element;
    renderer: "svg";
    loop: boolean;
    autoplay: boolean;
    animationData: object;
  }) => { destroy: () => void };
};

let lottiePlayerPromise: Promise<LottiePlayer> | null = null;

function loadLottiePlayer(): Promise<LottiePlayer> {
  if (!lottiePlayerPromise) {
    lottiePlayerPromise = import("lottie-web/build/player/lottie_light").then(
      (module) => module.default as LottiePlayer,
    );
  }
  return lottiePlayerPromise;
}

function altFromNode(node: HTMLElement): string {
  return node.getAttribute("data-alt") ?? node.getAttribute("alt") ?? "⭐";
}

async function mountPreview(node: HTMLElement, documentId: string, alt: string): Promise<void> {
  const preview = await fetchEmojiPreview(documentId);
  if (node.dataset.emojiHydrated !== "pending") return;

  if (preview.kind === "image") {
    const img = document.createElement("img");
    img.className = node.className.replace("tg-custom-emoji-placeholder", "").trim() || "tg-custom-emoji";
    img.src = preview.url;
    img.alt = alt;
    img.draggable = false;
    img.setAttribute("data-emoji-id", documentId);
    node.replaceWith(img);
    return;
  }

  if (preview.kind === "video") {
    const video = document.createElement("video");
    video.className = node.className.replace("tg-custom-emoji-placeholder", "").trim() || "tg-custom-emoji";
    video.src = preview.url;
    video.autoplay = true;
    video.loop = true;
    video.muted = true;
    video.playsInline = true;
    video.setAttribute("data-emoji-id", documentId);
    video.setAttribute("aria-label", alt);
    node.replaceWith(video);
    return;
  }

  const host = document.createElement("span");
  host.className = "tg-custom-emoji-host";
  host.setAttribute("data-emoji-id", documentId);
  node.replaceWith(host);

  const lottie = await loadLottiePlayer();
  const animation = lottie.loadAnimation({
    container: host,
    renderer: "svg",
    loop: true,
    autoplay: true,
    animationData: preview.data,
  });
  host.dataset.lottieMounted = "1";
  host.addEventListener(
    "DOMNodeRemoved",
    () => {
      animation.destroy();
    },
    { once: true },
  );
}

const MAX_HYDRATE_RETRIES = 3;
const HYDRATE_RETRY_DELAY_MS = 1500;

function hydrateNode(node: HTMLElement): void {
  const documentId = node.getAttribute("data-emoji-id");
  if (!documentId || node.dataset.emojiHydrated) return;

  node.dataset.emojiHydrated = "pending";
  const alt = altFromNode(node);
  const retries = Number(node.dataset.emojiRetries ?? "0");

  void mountPreview(node, documentId, alt).catch((error: unknown) => {
    if (!node.isConnected) return;

    const permanent = error instanceof EmojiPreviewError && error.permanent;
    if (!permanent && retries < MAX_HYDRATE_RETRIES) {
      node.dataset.emojiRetries = String(retries + 1);
      delete node.dataset.emojiHydrated;
      setTimeout(() => {
        if (node.isConnected && !node.dataset.emojiHydrated) {
          hydrateNode(node);
        }
      }, HYDRATE_RETRY_DELAY_MS * (retries + 1));
      return;
    }

    node.dataset.emojiHydrated = "failed";
    node.classList.add("tg-custom-emoji-fallback");
    if (!node.textContent?.trim()) {
      node.textContent = alt;
    }
  });
}

/** Lazy-hydrate custom emoji placeholders when they enter the viewport. */
export function hydrateCustomEmojiInDom(container: ParentNode): () => void {
  if (typeof window === "undefined" || typeof IntersectionObserver === "undefined") {
    return () => undefined;
  }

  const nodes = Array.from(
    container.querySelectorAll<HTMLElement>(
      ".tg-custom-emoji[data-emoji-id]:not([data-emoji-hydrated])",
    ),
  );
  if (nodes.length === 0) return () => undefined;

  const observer = new IntersectionObserver(
    (entries) => {
      for (const entry of entries) {
        if (!entry.isIntersecting) continue;
        const node = entry.target as HTMLElement;
        observer.unobserve(node);
        hydrateNode(node);
      }
    },
    { rootMargin: "120px" },
  );

  for (const node of nodes) {
    observer.observe(node);
  }

  return () => observer.disconnect();
}
