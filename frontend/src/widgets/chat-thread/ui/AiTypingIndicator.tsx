export default function AiTypingIndicator() {
  return (
    <div className="ai-typing-indicator" aria-label="Формируется ответ" role="status">
      <span className="ai-typing-dot" />
      <span className="ai-typing-dot" />
      <span className="ai-typing-dot" />
    </div>
  );
}
