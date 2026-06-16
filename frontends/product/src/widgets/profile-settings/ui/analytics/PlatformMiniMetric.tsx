type Props = {
  label: string;
  value: string;
};

export default function PlatformMiniMetric({ label, value }: Props) {
  return (
    <div className="mini-metric">
      <div className="mini-metric-label">{label}</div>
      <div className="mini-metric-value">{value}</div>
    </div>
  );
}
