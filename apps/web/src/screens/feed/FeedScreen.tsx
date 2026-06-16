"use client";

import { useMemo } from "react";

import { useNavigationStore, useUiStore } from "@/app/model/store";
import { useMobile760 } from "@/shared/lib/hooks/useMobile760";
import { useScreenBack } from "@/widgets/app-shell/model/useScreenBack";
import { FeedComposer } from "@/screens/feed/ui/FeedComposer";
import { FeedPublishedSection } from "@/screens/feed/ui/FeedPublishedSection";
import { FeedScheduledSection } from "@/screens/feed/ui/FeedScheduledSection";
import { useFeedScreen } from "@/screens/feed/model/useFeedScreen";
import { useChannelConnected } from "@/entities/channel";
import { ConnectChannelEmptyState } from "@/features/connect-channel";
import { FeedDraftsSection } from "@/widgets/feed";
import {
  buildFeedPostWidthSelectProps,
  createFeedHeaderSearchRow,
} from "@/widgets/feed/ui/feed-header-toolbar";
import { PageHeader, PageHeaderSelect } from "@/widgets/page-header";

export function FeedScreen() {
  const onBack = useScreenBack();
  const isMobile = useMobile760();
  const search = useNavigationStore((s) => s.feedSearch);
  const setFeedSearch = useNavigationStore((s) => s.setFeedSearch);
  const feedPostWidth = useUiStore((s) => s.feedCardWidth);
  const setFeedPostWidth = useUiStore((s) => s.setFeedCardWidth);
  const { data, ui, actions } = useFeedScreen();
  const { isConnected: isChannelConnected, isLoading: isChannelLoading } = useChannelConnected();
  const {
    layoutClassName,
    layoutStyle,
    feedScrollRef,
    composerReady,
    taRef,
    draft,
    setDraft,
    pendingMedia,
  } = ui;
  const {
    openPost,
    openPostComments,
    submitDraft,
    removePendingMedia,
    handleDraftKeyDown,
    handleAttach,
  } = actions;

  const feedPostWidthSelectProps = useMemo(
    () => buildFeedPostWidthSelectProps(feedPostWidth, setFeedPostWidth),
    [feedPostWidth, setFeedPostWidth],
  );

  return (
    <div className={`feed-screen-wrap${layoutClassName}`} style={layoutStyle}>
      <PageHeader
        title="Лента"
        onBack={onBack}
        compactSearchAtWidth={804}
        mobileSelect={
          !isMobile ? <PageHeaderSelect {...feedPostWidthSelectProps} /> : undefined
        }
        search={createFeedHeaderSearchRow({
          value: search,
          onChange: setFeedSearch,
          feedPostWidth,
          onFeedPostWidthChange: setFeedPostWidth,
        })}
      />
      <div className="feed-layout">
        <div className="composer-scroll-wrap">
          <div className="feed-scroll" id="feed-scroll" ref={feedScrollRef}>
            <div className="composer-scroll-body">
              <div className="feed-inner">
                {data.isLoading || isChannelLoading ? (
                  <p className="screen-placeholder">Загрузка ленты…</p>
                ) : !isChannelConnected ? (
                  <ConnectChannelEmptyState feature="ленте" icon="📰" />
                ) : data.isEmpty && search.trim() ? (
                  <p className="screen-placeholder">Ничего не найдено по запросу «{search.trim()}»</p>
                ) : (
                  <>
                    <FeedPublishedSection
                      groups={data.publishedDayGroups}
                      onOpen={openPost}
                      onOpenComments={openPostComments}
                    />
                    <FeedScheduledSection posts={data.scheduled} onOpen={openPost} />
                    <FeedDraftsSection drafts={data.drafts} onOpen={openPost} />
                  </>
                )}
              </div>
            </div>
          </div>
        </div>
        {isChannelConnected ? (
          <FeedComposer
            ui={{ composerReady, taRef, draft, setDraft, pendingMedia }}
            actions={{ submitDraft, removePendingMedia, handleDraftKeyDown, handleAttach }}
          />
        ) : null}
      </div>
    </div>
  );
}
