"use client";

import ChatBranchNav from "./ChatBranchNav";
import {
  IcUserCopied,
  IcUserCopy,
  IcUserEdit,
  type ChatMessageCtx,
} from "@/entities/message";

type Props = {
  ctx?: ChatMessageCtx;
  textHtml: string;
  editing: boolean;
  draft: string;
  editSession: number;
  copied: boolean;
  userActionsOpen: boolean;
  userHoverZoneRef: React.RefObject<HTMLDivElement | null>;
  taRef: React.RefObject<HTMLTextAreaElement | null>;
  userBranchCount: number;
  userBranchIdx: number;
  onDraftChange: (value: string) => void;
  onEditKeyDown: (e: React.KeyboardEvent<HTMLTextAreaElement>) => void;
  onSave: () => void;
  onCancel: () => void;
  onStartEdit: () => void;
  onCopy: () => void;
  onOpenMobileActions: () => void;
  onBumpBranch: (delta: number) => void;
};

export default function ChatUserMessage({
  ctx,
  textHtml,
  editing,
  draft,
  editSession,
  copied,
  userActionsOpen,
  userHoverZoneRef,
  taRef,
  userBranchCount,
  userBranchIdx,
  onDraftChange,
  onEditKeyDown,
  onSave,
  onCancel,
  onStartEdit,
  onCopy,
  onOpenMobileActions,
  onBumpBranch,
}: Props) {
  return (
    <div className="msg-row user">
      <div
        ref={userHoverZoneRef}
        className={`msg-user-hover-zone${editing ? " msg-user-hover-zone--editing" : ""}${
          userActionsOpen ? " msg-user-hover-zone--actions-open" : ""
        }`}
      >
        <div className="msg-user-stack">
          <div className="msg-user-bubble-row" onClick={onOpenMobileActions}>
            <div className={`msg-body${ctx && !editing ? " msg-body--user-actions" : ""}`}>
              {ctx && !editing ? (
                <div className="msg-user-side-actions">
                  <button
                    type="button"
                    className="ai-msg-action-btn"
                    aria-label="Редактировать"
                    title="Редактировать"
                    onClick={onStartEdit}
                  >
                    <IcUserEdit />
                  </button>
                  <button
                    type="button"
                    className={`ai-msg-action-btn${copied ? " on" : ""}`}
                    aria-label={copied ? "Скопировано" : "Скопировать"}
                    title={copied ? "Скопировано" : "Скопировать"}
                    onClick={() => void onCopy()}
                  >
                    {copied ? <IcUserCopied /> : <IcUserCopy />}
                  </button>
                </div>
              ) : null}
              {editing ? (
                <div className="msg-user-edit-wrap" key={editSession}>
                  <textarea
                    ref={taRef}
                    className="msg-user-edit"
                    value={draft}
                    onChange={(e) => onDraftChange(e.target.value)}
                    onKeyDown={onEditKeyDown}
                    rows={1}
                    spellCheck={false}
                    aria-label="Текст сообщения"
                  />
                  <div className="msg-user-edit-bar">
                    <button type="button" className="btn btn-primary post-edit-btn" onClick={onSave}>
                      Сохранить
                    </button>
                    <button type="button" className="btn btn-ghost post-edit-btn" onClick={onCancel}>
                      Отмена
                    </button>
                  </div>
                </div>
              ) : (
                <div className="msg-text" dangerouslySetInnerHTML={{ __html: textHtml }} />
              )}
            </div>
          </div>
          {ctx && userBranchCount > 1 && !editing ? (
            <ChatBranchNav
              index={userBranchIdx}
              count={userBranchCount}
              canGoPrev={userBranchIdx > 0}
              canGoNext={userBranchIdx < userBranchCount - 1}
              onPrev={() => onBumpBranch(-1)}
              onNext={() => onBumpBranch(1)}
              prevLabel="Предыдущая версия"
              nextLabel="Следующая версия"
            />
          ) : null}
        </div>
      </div>
    </div>
  );
}
