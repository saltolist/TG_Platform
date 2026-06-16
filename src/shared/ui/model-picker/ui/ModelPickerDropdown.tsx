import type { ModelOption, ModelPickerSection } from "../model/types";

type Props = {
  value: string;
  options: ModelOption[];
  sections?: ModelPickerSection[];
  emptyValue?: string;
  emptyLabel?: string;
  onSelect: (id: string) => void;
};

export default function ModelPickerDropdown({
  value,
  options,
  sections,
  emptyValue,
  emptyLabel,
  onSelect,
}: Props) {
  return (
    <>
      {emptyValue !== undefined && emptyLabel ? (
        <div
          role="option"
          aria-selected={value === emptyValue}
          className={`model-picker-item${value === emptyValue ? " active" : ""}`}
          onClick={() => onSelect(emptyValue)}
        >
          <span className="model-picker-item-label">{emptyLabel}</span>
        </div>
      ) : null}
      {sections
        ? sections.map((section) => (
            <div key={section.title}>
              <div className="model-picker-section-title">{section.title}</div>
              {section.options.map((opt) => (
                <ModelPickerOption
                  key={opt.id}
                  opt={opt}
                  selected={value === opt.id}
                  onSelect={onSelect}
                />
              ))}
            </div>
          ))
        : options.map((opt) => (
            <ModelPickerOption
              key={opt.id}
              opt={opt}
              selected={value === opt.id}
              onSelect={onSelect}
            />
          ))}
    </>
  );
}

function ModelPickerOption({
  opt,
  selected,
  onSelect,
}: {
  opt: ModelOption;
  selected: boolean;
  onSelect: (id: string) => void;
}) {
  return (
    <div
      role="option"
      aria-selected={selected}
      className={`model-picker-item${selected ? " active" : ""}`}
      onClick={() => onSelect(opt.id)}
    >
      <span className="model-picker-item-label">{opt.label}</span>
    </div>
  );
}
