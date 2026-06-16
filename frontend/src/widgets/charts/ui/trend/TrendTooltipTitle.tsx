type Props = {
  label: string;
  growth?: string;
};

export default function TrendTooltipTitle({ label, growth }: Props) {
  return (
    <div className="trend-tooltip-head">
      <b>{label}</b>
      {growth ? <span className="trend-tooltip-growth">{growth}</span> : null}
    </div>
  );
}
