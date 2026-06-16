"use client";

import { Image as ImageIcon, Paperclip } from "lucide-react";

export function AttachMenuIconAttach() {
  return (
    <span className="attach-item-icon" aria-hidden>
      <Paperclip className="size-[18px]" strokeWidth={2} />
    </span>
  );
}

export function AttachMenuIconImage() {
  return (
    <span className="attach-item-icon" aria-hidden>
      <ImageIcon className="size-[18px]" strokeWidth={2} />
    </span>
  );
}
