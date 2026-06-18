import { ChevronDown, Cpu } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import type { Provider } from "../lib/api";
import { cn } from "../lib/utils";
import { PROVIDER_COLORS, PROVIDER_ICONS } from "../lib/providerIcons";

type Props = {
  providers: Provider[];
  value: number | null;
  onChange: (id: number | null) => void;
  disabled?: boolean;
  placeholder?: string;
  className?: string;
  /** Use a smaller layout (for per-role cards) */
  small?: boolean;
};

export default function ProviderSelect({
  providers,
  value,
  onChange,
  disabled,
  placeholder = "— provider —",
  className,
  small,
}: Props) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    function handleClick(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        setOpen(false);
      }
    }
    document.addEventListener("mousedown", handleClick);
    return () => document.removeEventListener("mousedown", handleClick);
  }, [open]);

  const selected = value != null ? providers.find((p) => p.id === value) : null;
  const Icon = selected
    ? (PROVIDER_ICONS[selected.provider_type] ?? Cpu)
    : Cpu;
  const iconBg = selected
    ? (PROVIDER_COLORS[selected.provider_type] ?? "")
    : "";

  const sz = small ? "text-xs py-1.5" : "text-sm py-2";

  return (
    <div ref={ref} className={cn("relative", className)}>
      <button
        type="button"
        disabled={disabled}
        className={cn(
          "input flex w-full items-center gap-2 pr-8 text-left",
          sz,
          disabled && "opacity-50 cursor-not-allowed",
        )}
        onClick={() => !disabled && setOpen((o) => !o)}
      >
        {selected ? (
          <>
            <span
              className={cn(
                "flex h-5 w-5 shrink-0 items-center justify-center rounded",
                iconBg,
              )}
            >
              <Icon size={small ? 11 : 13} />
            </span>
            <span className="truncate">{selected.name}</span>
          </>
        ) : (
          <span className="text-ink-400">{placeholder}</span>
        )}
        <ChevronDown
          size={small ? 13 : 15}
          className={cn(
            "absolute right-2 top-1/2 -translate-y-1/2 text-ink-400 transition-transform",
            open && "rotate-180",
          )}
        />
      </button>

      {open && (
        <div className="absolute z-20 mt-1 w-full rounded-xl border border-ink-200 bg-white py-1 shadow-lg dark:border-ink-700 dark:bg-ink-900">
          {value != null && (
            <button
              type="button"
              className={cn(
                "flex w-full items-center gap-2 px-3 py-2 text-left transition-colors hover:bg-ink-50 dark:hover:bg-ink-800",
                sz,
              )}
              onClick={() => {
                onChange(null);
                setOpen(false);
              }}
            >
              <span className="flex h-5 w-5 shrink-0 items-center justify-center rounded text-ink-400 bg-ink-100 dark:bg-ink-800">
                <Cpu size={small ? 11 : 13} />
              </span>
              <span className="text-ink-400">{placeholder}</span>
            </button>
          )}
          {providers.map((p) => {
            const PIcon = PROVIDER_ICONS[p.provider_type] ?? Cpu;
            const pBg = PROVIDER_COLORS[p.provider_type] ?? "";
            const active = p.id === value;
            return (
              <button
                key={p.id}
                type="button"
                className={cn(
                  "flex w-full items-center gap-2 px-3 py-2 text-left transition-colors hover:bg-ink-50 dark:hover:bg-ink-800",
                  sz,
                  active && "bg-ink-50 dark:bg-ink-800/60",
                )}
                onClick={() => {
                  onChange(p.id);
                  setOpen(false);
                }}
              >
                <span
                  className={cn(
                    "flex h-5 w-5 shrink-0 items-center justify-center rounded",
                    pBg,
                  )}
                >
                  <PIcon size={small ? 11 : 13} />
                </span>
                <span className="truncate font-medium">{p.name}</span>
                {active && (
                  <span className="ml-auto text-[10px] text-ink-400">active</span>
                )}
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}
