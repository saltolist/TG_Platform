import { PostScreen } from "@/screens/post";
import { STATIC_POST_IDS } from "@/shared/lib/staticParams";

export function generateStaticParams() {
  return STATIC_POST_IDS.map((id) => ({ id }));
}

export default function PostPage() {
  return <PostScreen />;
}
