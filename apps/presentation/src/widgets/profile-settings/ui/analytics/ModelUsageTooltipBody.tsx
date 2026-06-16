import type { PlatformModelUsage } from "@/shared/lib/profile/platformAnalytics";

type Props = {
  model: PlatformModelUsage;
  callsShare: number;
  tokensShare: number;
  costShare: number;
};

export default function ModelUsageTooltipBody({
  model,
  callsShare,
  tokensShare,
  costShare,
}: Props) {
  return (
    <>
      <b>{model.label}</b>
      <span>Запросы: {callsShare}%</span>
      <span>Токены: {tokensShare}%</span>
      <span>Стоимость: {costShare}%</span>
    </>
  );
}
