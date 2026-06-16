import { createElement } from "react";
import { describe, expect, it } from "vitest";

import { createFeedHeaderSearchRow } from "@/widgets/feed/ui/feed-header-toolbar";
import {
  buildExpandableSearchContent,
  findPageHeaderSearchInput,
} from "@/widgets/page-header/lib/pageHeaderSearchUtils";
import { PageHeaderSearchInput } from "@/widgets/page-header/ui/PageHeaderSearchInput";

describe("pageHeaderSearchUtils", () => {
  it("finds PageHeaderSearchInput in static search tree", () => {
    const search = createElement(
      "div",
      null,
      createElement(PageHeaderSearchInput, { value: "", onChange: () => {} }),
    );

    expect(findPageHeaderSearchInput(search)).not.toBeNull();
  });

  it("builds expandable feed search with dismissAlways on input", () => {
    const search = createFeedHeaderSearchRow({
      value: "",
      onChange: () => {},
      feedPostWidth: 500,
      onFeedPostWidthChange: () => {},
    });
    const onClose = () => {};
    const expanded = buildExpandableSearchContent(search, onClose);

    expect(expanded).not.toBeNull();
    expect(findPageHeaderSearchInput(expanded)).not.toBeNull();
  });
});
