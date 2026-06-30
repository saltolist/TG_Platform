import { describe, expect, it } from "vitest";

import {
  detachWebCitationMarkers,
  injectWebCitationPlaceholders,
  prepareWebCitationsForDisplay,
  resolveWebCitationHref,
} from "./webCitation";

const cites = [
  { url: "https://a.example/1", title: "A", domain: "a.example" },
  { url: "https://b.example/2", title: "B", domain: "b.example" },
];

describe("webCitation", () => {
  it("moves markers from before period to after it", () => {
    expect(detachWebCitationMarkers("Текст[1][2].")).toBe("Текст. [1][2]");
    expect(detachWebCitationMarkers("Текст[1][2]. Далее")).toBe("Текст. [1][2] Далее");
    expect(detachWebCitationMarkers("Первое[1]. Второе[2].")).toBe("Первое. [1] Второе. [2]");
  });

  it("injects placeholder links for numeric markers", () => {
    const text = "Текст. [1] и ещё. [2][3]";
    expect(injectWebCitationPlaceholders(text, cites)).toBe(
      "Текст. [](webcite:1) и ещё. [](webcite:2)[3]",
    );
  });

  it("detaches markers then injects placeholders", () => {
    expect(prepareWebCitationsForDisplay("Ответ[2].", cites)).toBe("Ответ. [](webcite:2)");
  });

  it("keeps markers when web cites are not available yet", () => {
    expect(prepareWebCitationsForDisplay("Ответ[2].", undefined)).toBe("Ответ. [2]");
    expect(prepareWebCitationsForDisplay("Ответ[2].", [])).toBe("Ответ. [2]");
  });

  it("resolves webcite href index", () => {
    expect(resolveWebCitationHref("webcite:2")).toBe(2);
    expect(resolveWebCitationHref("https://x")).toBeNull();
  });
});
