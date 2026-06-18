import { FileImage, FileText, FileUp, X } from "lucide-react";
import { useCallback, useRef, useState } from "react";
import { cn } from "../lib/utils";

interface Props {
  files: File[];
  onChange: (files: File[]) => void;
}

const ACCEPT = ".pdf,.txt,.md,.json,.csv,.xml,.yml,.yaml,.py,.js,.ts,.jsx,.tsx,.html,.css,.png,.jpg,.jpeg,.gif,.webp,.bmp,application/pdf,text/plain,image/png,image/jpeg";

function fileTypeIcon(f: File): { icon: typeof FileUp; label: string; color: string } {
  const ext = f.name.split(".").pop()?.toLowerCase() ?? "";
  if (ext === "pdf") return { icon: FileUp, label: "PDF", color: "bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-400" };
  if (["png", "jpg", "jpeg", "gif", "webp", "bmp"].includes(ext)) return { icon: FileImage, label: "IMG", color: "bg-purple-100 text-purple-700 dark:bg-purple-900/30 dark:text-purple-400" };
  return { icon: FileText, label: "TXT", color: "bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-400" };
}

export default function Dropzone({ files, onChange }: Props) {
  const [dragOver, setDragOver] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  const addFiles = useCallback(
    (incoming: FileList | null) => {
      if (!incoming) return;
      onChange([...files, ...Array.from(incoming)]);
    },
    [files, onChange],
  );

  return (
    <div className="space-y-3">
      <div
        onDragOver={(e) => {
          e.preventDefault();
          setDragOver(true);
        }}
        onDragLeave={() => setDragOver(false)}
        onDrop={(e) => {
          e.preventDefault();
          setDragOver(false);
          addFiles(e.dataTransfer.files);
        }}
        onClick={() => inputRef.current?.click()}
        className={cn(
          "flex cursor-pointer flex-col items-center justify-center gap-2 rounded-xl border-2 border-dashed px-6 py-12 text-center transition-colors",
          dragOver
            ? "border-ink-500 bg-ink-100 dark:bg-ink-900"
            : "border-ink-300 hover:border-ink-400 dark:border-ink-700",
        )}
      >
        <FileUp size={28} className="text-ink-400" />
        <p className="text-sm font-medium">
          Drag your files here or click to choose
        </p>
        <p className="text-xs text-ink-500">
          PDF, text (MD, JSON, CSV, code), images, URLs below
        </p>
        <input
          ref={inputRef}
          type="file"
          accept={ACCEPT}
          multiple
          className="hidden"
          onChange={(e) => addFiles(e.target.files)}
        />
      </div>

      {files.length > 0 && (
        <ul className="space-y-2">
          {files.map((f, i) => {
            const { icon: Icon, label, color } = fileTypeIcon(f);
            return (
              <li
                key={`${f.name}-${i}`}
                className="flex items-center justify-between rounded-lg border border-ink-200 px-3 py-2 text-sm dark:border-ink-800"
              >
                <span className="flex min-w-0 items-center gap-2">
                  <span className={cn("inline-flex shrink-0 items-center gap-1 rounded px-1.5 py-0.5 text-[10px] font-medium", color)}>
                    <Icon size={11} />
                    {label}
                  </span>
                  <span className="truncate">{f.name}</span>
                </span>
                <button
                  onClick={() => onChange(files.filter((_, idx) => idx !== i))}
                  className="shrink-0 text-ink-400 hover:text-ink-700 dark:hover:text-ink-200"
                  aria-label="Remove"
                >
                  <X size={15} />
                </button>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
