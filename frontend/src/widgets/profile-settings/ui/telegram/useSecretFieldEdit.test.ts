/**
 * @vitest-environment jsdom
 */
import { act, renderHook } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { useSecretFieldEdit } from "@/widgets/profile-settings/ui/telegram/useSecretFieldEdit";

describe("useSecretFieldEdit", () => {
  it("shows preview until focus, then empty draft", () => {
    const preview = "abc**********xyz";
    const onChange = vi.fn();
    const { result, rerender } = renderHook(
      ({ value }) => useSecretFieldEdit(value, onChange),
      { initialProps: { value: preview } },
    );

    expect(result.current.displayValue).toBe(preview);

    act(() => {
      result.current.inputProps.onFocus();
    });
    rerender({ value: preview });
    expect(result.current.displayValue).toBe("");
    expect(onChange).not.toHaveBeenCalled();
  });

  it("restores preview on blur when nothing was typed", () => {
    const preview = "abc**********xyz";
    const onChange = vi.fn();
    const { result, rerender } = renderHook(
      ({ value }) => useSecretFieldEdit(value, onChange),
      { initialProps: { value: preview } },
    );

    act(() => {
      result.current.inputProps.onFocus();
    });
    rerender({ value: preview });

    act(() => {
      result.current.inputProps.onBlur();
    });
    rerender({ value: preview });

    expect(result.current.displayValue).toBe(preview);
    expect(onChange).toHaveBeenCalledWith(preview);
  });
});
