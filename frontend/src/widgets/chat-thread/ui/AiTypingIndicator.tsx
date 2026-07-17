type Props = {
  /** Короткая фраза текущего шага агента (напр. «Изучаю пост…»). */
  label?: string;
};

export default function AiTypingIndicator({ label }: Props) {
  return (
    <div className="ai-typing-indicator" aria-label={label ?? "Формируется ответ"} role="status">
      {label ? <span className="ai-typing-label">{label}</span> : null}
      <span className="ai-typing-dots" aria-hidden="true">
        <span className="ai-typing-dot" />
        <span className="ai-typing-dot" />
        <span className="ai-typing-dot" />
      </span>
    </div>
  );
}
