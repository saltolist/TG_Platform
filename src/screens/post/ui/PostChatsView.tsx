"use client";

import { useMobile760 } from "@/shared/lib/hooks/useMobile760";
import { FilterToolbar, FilterToolbarAction } from "@/widgets/filter-toolbar";
import { type PostWorkspace } from "@/widgets/post-workspace";
import PostChatsList from "@/screens/post/ui/PostChatsList";
import type { Post } from "@/shared/types";

type Props = {
  post: Post;
  ui: Pick<PostWorkspace["ui"], "listSearch">;
  actions: Pick<PostWorkspace["actions"], "startNewChat" | "openLocalChat">;
};

export default function PostChatsView({ post, ui, actions }: Props) {
  const isMobile = useMobile760();
  const { listSearch } = ui;
  const { startNewChat, openLocalChat } = actions;

  return (
    <div className="post-subpage-scroll">
      <FilterToolbar
        className="post-subpage-toolbar"
        width="composer"
        action={
          <FilterToolbarAction
            label="Новый чат"
            onClick={startNewChat}
            className={`chats-new-chat-btn${isMobile ? " filter-tab--dropdown" : ""}`}
            iconClassName="chats-new-chat-btn-icon"
          />
        }
      />
      <PostChatsList post={post} search={listSearch} onOpenChat={openLocalChat} />
    </div>
  );
}
