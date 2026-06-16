import type { RefObject } from "react";
import type { ComposerScope } from "@/shared/types";

export type MentionState = {
  textNode: Text;
  atOffset: number;
  caretOffset: number;
  query: string;
} | null;

export type ComposerEditorRefs = {
  editorRef: RefObject<HTMLDivElement | null>;
  inputBoxRef: RefObject<HTMLDivElement | null>;
  mentionRef: RefObject<HTMLDivElement | null>;
};

export type UseComposerEditorProps = {
  scope: ComposerScope;
  placeholder?: string;
  onSubmit: (text: string) => boolean;
};
