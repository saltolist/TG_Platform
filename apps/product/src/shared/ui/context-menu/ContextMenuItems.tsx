import type { CtxMenuItem } from "./contextMenuTypes";

type Props = {
  items: CtxMenuItem[];
  onSelect: (item: CtxMenuItem) => void;
};

export function ContextMenuItems({ items, onSelect }: Props) {
  return (
    <>
      {items.map((it, i) => (
        <div
          key={i}
          className={`ctx-item${it.active ? " active" : ""}${it.danger ? " danger" : ""}${
            it.disabled ? " disabled" : ""
          }`}
          onClick={() => {
            if (it.disabled) return;
            onSelect(it);
          }}
        >
          {it.icon != null ? <span className="ctx-item-icon">{it.icon}</span> : null}
          <span className="ctx-item-label">{it.label}</span>
        </div>
      ))}
    </>
  );
}
