"use client";

type Props = {
  onReply?: () => void;
  onDelete?: () => void;
  className?: string;
  disabled?: boolean;
};

export function PostCommentActions({
  onReply,
  onDelete,
  className = "",
  disabled = false,
}: Props) {
  if (!onReply && !onDelete) return null;

  return (
    <div className={`post-comment-actions${className ? ` ${className}` : ""}`}>
      {onReply ? (
        <button
          className="post-comment-reply-btn"
          onClick={onReply}
          type="button"
          disabled={disabled}
        >
          Ответить
        </button>
      ) : null}
      {onDelete ? (
        <button
          className="post-comment-delete-btn"
          onClick={onDelete}
          type="button"
          disabled={disabled}
        >
          Удалить
        </button>
      ) : null}
    </div>
  );
}
