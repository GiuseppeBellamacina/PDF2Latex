import { Check } from "lucide-react";
import type { ReactNode } from "react";
import { cn } from "../lib/utils";

interface Props {
  checked: boolean;
  onChange: (checked: boolean) => void;
  label?: ReactNode;
  hint?: ReactNode;
  disabled?: boolean;
  className?: string;
}

/** A custom-styled checkbox that matches the ink/emerald theme. */
export default function Checkbox({
  checked,
  onChange,
  label,
  hint,
  disabled,
  className,
}: Props) {
  return (
    <label
      className={cn(
        "flex cursor-pointer select-none items-start gap-3",
        disabled && "cursor-not-allowed opacity-50",
        className,
      )}
    >
      <span className="relative mt-0.5 inline-flex h-5 w-5 shrink-0">
        <input
          type="checkbox"
          checked={checked}
          disabled={disabled}
          onChange={(e) => onChange(e.target.checked)}
          className="peer absolute inset-0 cursor-pointer opacity-0 disabled:cursor-not-allowed"
        />
        <span
          className={cn(
            "pointer-events-none flex h-5 w-5 items-center justify-center rounded-md border transition-all duration-150",
            "border-ink-300 bg-white dark:border-ink-600 dark:bg-ink-900",
            "peer-checked:border-emerald-500 peer-checked:bg-emerald-500",
            "peer-focus-visible:ring-2 peer-focus-visible:ring-emerald-500/40 peer-focus-visible:ring-offset-0",
          )}
        >
          <Check
            size={14}
            strokeWidth={3}
            className={cn(
              "text-white transition-opacity duration-150",
              checked ? "opacity-100" : "opacity-0",
            )}
          />
        </span>
      </span>
      {(label || hint) && (
        <span className="space-y-0.5 text-sm">
          {label && <span className="block font-medium">{label}</span>}
          {hint && <span className="block text-xs text-ink-500">{hint}</span>}
        </span>
      )}
    </label>
  );
}
