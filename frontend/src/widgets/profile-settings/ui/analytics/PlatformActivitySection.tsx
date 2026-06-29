import type { PlatformActivityDto } from "@/shared/api/schemas/platformAnalytics";

type Props = {
  activity?: PlatformActivityDto;
};

export default function PlatformActivitySection({ activity }: Props) {
  const chats = activity?.chats ?? 0;
  const notes = activity?.notes ?? 0;
  const posts = activity?.posts ?? 0;

  return (
    <div className="profile-section platform-analytics-section">
      <div className="profile-section-title platform-section-title-spaced">Активность платформы</div>
      <div className="profile-val" style={{ fontSize: 13, color: "var(--text2)" }}>
        Чатов создано: {chats} &nbsp;•&nbsp; Заметок: {notes} &nbsp;•&nbsp; Постов: {posts}
      </div>
    </div>
  );
}
