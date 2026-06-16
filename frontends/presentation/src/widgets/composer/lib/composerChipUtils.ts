import { truncate } from "@/shared/lib/helpers";
import type { ComposerAttachment } from "@/shared/types";

let attachCounter = 0;

export function nextAttachId(): string {
  attachCounter += 1;
  return `att-${Date.now()}-${attachCounter}`;
}

export function chipIcon(att: ComposerAttachment): string {
  if (att.kind === "file") return "📎";
  return "🖼";
}

export function chipLabel(att: ComposerAttachment): string {
  if (att.kind === "post") return att.title;
  if (att.kind === "file") return att.name;
  return `${att.postTitle} · ${att.media}`;
}

export function serializeChip(att: ComposerAttachment): string {
  if (att.kind === "post") return `Пост «${att.title}»`;
  if (att.kind === "file") return `Прикрепил файл: ${att.name}`;
  return `Прикрепил медиа из поста «${att.postTitle}»: ${att.media}`;
}

export function createChipElement(
  att: ComposerAttachment,
  onRemove: (id: string) => void,
): HTMLSpanElement {
  const el = document.createElement("span");
  el.className = "inline-chip";
  el.contentEditable = "false";
  el.setAttribute("data-attach-id", att.id);
  el.setAttribute("data-attach-kind", att.kind);
  el.title = chipLabel(att);

  const icon = document.createElement("span");
  icon.className = "inline-chip-icon";
  icon.textContent = att.kind === "post" ? "📄" : chipIcon(att);
  el.appendChild(icon);

  const label = document.createElement("span");
  label.className = "inline-chip-label";
  label.textContent = truncate(chipLabel(att), 36);
  el.appendChild(label);

  const remove = document.createElement("button");
  remove.type = "button";
  remove.className = "inline-chip-remove";
  remove.setAttribute("aria-label", "Удалить вложение");
  remove.contentEditable = "false";
  remove.textContent = "×";
  remove.addEventListener("mousedown", (e) => e.preventDefault());
  remove.addEventListener("click", (e) => {
    e.preventDefault();
    e.stopPropagation();
    onRemove(att.id);
  });
  el.appendChild(remove);

  return el;
}
