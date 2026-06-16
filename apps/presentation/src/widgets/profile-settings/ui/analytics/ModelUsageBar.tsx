"use client";

import { createPortal } from "react-dom";
import type { CSSProperties } from "react";
import ModelUsageTooltipBody from "@/widgets/profile-settings/ui/analytics/ModelUsageTooltipBody";
import { useAnchoredBarRowTooltip } from "@/shared/lib/hooks/useAnchoredBarRowTooltip";
import { useDesktopBarTooltipPortal } from "@/shared/lib/hooks/useDesktopBarTooltipPortal";
import { useMobile760 } from "@/shared/lib/hooks/useMobile760";
import type {
  PlatformModelUsage,
  PlatformModelUsageTotals,
} from "@/shared/lib/profile/platformAnalytics";
import { formatCompact, formatNumber } from "@/shared/lib/trendChart/math";

type Props = {
  model: PlatformModelUsage;
  totals: PlatformModelUsageTotals;
};

export default function ModelUsageBar({ model, totals }: Props) {
  const isMobile = useMobile760();
  const { rowRef, open, mobileHandlers } = useAnchoredBarRowTooltip(isMobile);
  const { desktopTooltipPos, desktopTooltipHandlers } = useDesktopBarTooltipPortal(!isMobile);
  const callsShare = totals.calls > 0 ? Math.round((model.calls / totals.calls) * 100) : 0;
  const tokensShare = totals.tokens > 0 ? Math.round((model.tokens / totals.tokens) * 100) : 0;
  const costShare = totals.cost > 0 ? Math.round((model.cost / totals.cost) * 100) : 0;
  const fillShare = Math.round((callsShare + tokensShare + costShare) / 3);

  return (
    <div
      ref={rowRef}
      className={`bar-row model-usage-bar${open && isMobile ? " bar-row--tooltip-open" : ""}`}
      style={{ "--bar-row-color": model.color } as CSSProperties}
      tabIndex={isMobile ? 0 : undefined}
      aria-expanded={isMobile ? open : undefined}
      {...(isMobile ? mobileHandlers : {})}
    >
      <div className="bar-label">
        <span className="bar-label-text-clip">{model.label}</span>
        {isMobile && open ? (
          <div className="model-usage-tooltip model-usage-tooltip--anchored-row">
            <ModelUsageTooltipBody
              model={model}
              callsShare={callsShare}
              tokensShare={tokensShare}
              costShare={costShare}
            />
          </div>
        ) : null}
      </div>
      <div
        className="bar-track model-usage-track"
        tabIndex={isMobile ? undefined : 0}
        style={{ "--fill-width": `${Math.max(fillShare, 4)}%` } as CSSProperties}
        {...(isMobile ? {} : desktopTooltipHandlers)}
      >
        <div
          className={`bar-fill ${model.type}`}
          style={{ "--bar-color": model.color, backgroundColor: model.color } as CSSProperties}
        />
      </div>
      <div className="model-row-metric model-row-metric--calls">{formatNumber(model.calls)}</div>
      <div className="model-row-metric model-row-metric--tokens">{formatCompact(model.tokens)}</div>
      <div className="model-row-metric model-row-metric--cost">${model.cost.toFixed(2)}</div>
      {!isMobile && desktopTooltipPos && typeof document !== "undefined"
        ? createPortal(
            <div
              className="model-usage-tooltip"
              style={{ left: desktopTooltipPos.x, top: desktopTooltipPos.y }}
            >
              <ModelUsageTooltipBody
                model={model}
                callsShare={callsShare}
                tokensShare={tokensShare}
                costShare={costShare}
              />
            </div>,
            document.body,
          )
        : null}
    </div>
  );
}
