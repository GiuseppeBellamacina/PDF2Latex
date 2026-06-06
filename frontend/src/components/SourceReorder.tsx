import { GripVertical } from "lucide-react";
import { useLayoutEffect, useRef, useState } from "react";
import type { Source } from "../lib/api";
import { cn } from "../lib/utils";

interface Props {
  sources: Source[];
  onReorder: (next: Source[]) => void;
}

/**
 * Drag-and-drop reorderable list of PDFs with a smooth swap animation.
 *
 * Reordering happens live while dragging over another row, and the rows slide
 * into their new position using the FLIP technique (measure -> invert ->
 * play) so no animation library is needed.
 */
export default function SourceReorder({ sources, onReorder }: Props) {
  const [dragId, setDragId] = useState<number | null>(null);
  const [overId, setOverId] = useState<number | null>(null);
  const rowRefs = useRef<Map<number, HTMLLIElement>>(new Map());
  const prevRects = useRef<Map<number, DOMRect>>(new Map());

  // FLIP: after every reorder, animate each row from its previous position to
  // the new one.
  useLayoutEffect(() => {
    const rows = rowRefs.current;
    rows.forEach((el, id) => {
      const prev = prevRects.current.get(id);
      const next = el.getBoundingClientRect();
      if (prev) {
        const dy = prev.top - next.top;
        if (dy) {
          el.style.transition = "none";
          el.style.transform = `translateY(${dy}px)`;
          // Force reflow then play to the resting position.
          void el.offsetHeight;
          el.style.transition = "transform 220ms cubic-bezier(0.2, 0, 0, 1)";
          el.style.transform = "";
        }
      }
      prevRects.current.set(id, next);
    });
  }, [sources]);

  function move(fromId: number, toId: number) {
    if (fromId === toId) return;
    const from = sources.findIndex((s) => s.id === fromId);
    const to = sources.findIndex((s) => s.id === toId);
    if (from < 0 || to < 0) return;
    const next = [...sources];
    const [moved] = next.splice(from, 1);
    next.splice(to, 0, moved);
    onReorder(next);
  }

  return (
    <ul className="space-y-2">
      {sources.map((s, i) => {
        const dragging = dragId === s.id;
        return (
          <li
            key={s.id}
            ref={(el) => {
              if (el) rowRefs.current.set(s.id, el);
              else rowRefs.current.delete(s.id);
            }}
            draggable
            onDragStart={(e) => {
              setDragId(s.id);
              e.dataTransfer.effectAllowed = "move";
              e.dataTransfer.setData("text/plain", String(s.id));
            }}
            onDragEnter={() => {
              setOverId(s.id);
              if (dragId !== null) move(dragId, s.id);
            }}
            onDragOver={(e) => e.preventDefault()}
            onDragEnd={() => {
              setDragId(null);
              setOverId(null);
            }}
            className={cn(
              "flex items-center gap-3 rounded-lg border bg-ink-900/40 px-3 py-2",
              "will-change-transform",
              dragging
                ? "border-emerald-500/70 opacity-60 shadow-lg ring-2 ring-emerald-500/30"
                : overId === s.id
                  ? "border-emerald-500/50"
                  : "border-ink-800/60",
            )}
          >
            <span
              className="cursor-grab text-ink-500 hover:text-ink-300 active:cursor-grabbing"
              aria-hidden
            >
              <GripVertical size={16} />
            </span>
            <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-ink-800 text-xs font-medium">
              {i + 1}
            </span>
            <div className="min-w-0 flex-1">
              <p className="truncate text-sm font-medium">{s.filename}</p>
              <p className="text-xs text-ink-500">{s.n_pages} pages</p>
            </div>
          </li>
        );
      })}
    </ul>
  );
}
