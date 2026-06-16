"use client";

import type { ReactNode } from "react";

export type LocalChatRow = {
  postId: string;
  postTitle: string;
  chatId: string;
  title: string;
  preview: string;
  date: string;
  history: import("@/shared/types").GlobalChat["history"];
};

type ChatCardLayoutProps = {
  userLine: string;
  assistantLine: string;
  date: string;
  onOpen: () => void;
  iconRail: ReactNode;
  menu: ReactNode;
  titleAttr?: string;
};

function ChatCardLayout({
  userLine,
  assistantLine,
  date,
  onOpen,
  iconRail,
  menu,
  titleAttr,
}: ChatCardLayoutProps) {
  return (
    <div className="chat-card" onClick={onOpen} title={titleAttr}>
      <div className="chat-card-icon-rail" aria-hidden>
        {iconRail}
      </div>
      <div className="chat-card-body-row">
        <div className="chat-card-main">
          <div className="chat-card-row1">
            <div className="chat-card-title">{userLine}</div>
            <div className="chat-card-menu-slot" onClick={(e) => e.stopPropagation()}>
              {menu}
            </div>
          </div>
          <div className="chat-card-row2">
            <div className="chat-card-preview">{assistantLine || "—"}</div>
            <div className="chat-card-date">{date}</div>
          </div>
        </div>
      </div>
    </div>
  );
}

export function GlobalChatCard(props: ChatCardLayoutProps) {
  return <ChatCardLayout {...props} />;
}

export function LocalChatCard(props: ChatCardLayoutProps) {
  return <ChatCardLayout {...props} />;
}
