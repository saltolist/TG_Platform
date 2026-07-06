import type { RichTextFormat } from "@/shared/lib/telegram/richTextFormat";

export const FORMAT_MENU_PAGE_SIZE = 3;

export type RichTextFormatMenuItem = {
  format: RichTextFormat;
  label: string;
};

export const RICH_TEXT_FORMAT_MENU_ITEMS: RichTextFormatMenuItem[] = [
  { format: "bold", label: "Жирный" },
  { format: "italic", label: "Курсив" },
  { format: "underline", label: "Подчёркнутый" },
  { format: "strike", label: "Зачёркнутый" },
  { format: "spoiler", label: "Спойлер" },
  { format: "code", label: "Код" },
  { format: "link", label: "Ссылка" },
];

export type RichTextFormatMenuPage = {
  items: RichTextFormatMenuItem[];
  page: number;
  totalPages: number;
  canGoPrev: boolean;
  canGoNext: boolean;
};

export function getRichTextFormatMenuPage(
  page: number,
  items: RichTextFormatMenuItem[] = RICH_TEXT_FORMAT_MENU_ITEMS,
  pageSize = FORMAT_MENU_PAGE_SIZE,
): RichTextFormatMenuPage {
  const totalPages = Math.max(1, Math.ceil(items.length / pageSize));
  const safePage = Math.max(0, Math.min(page, totalPages - 1));
  const start = safePage * pageSize;

  return {
    items: items.slice(start, start + pageSize),
    page: safePage,
    totalPages,
    canGoPrev: safePage > 0,
    canGoNext: safePage < totalPages - 1,
  };
}
