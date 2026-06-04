import { FileUp, X } from "lucide-react";
import { useCallback, useRef, useState } from "react";
import { cn } from "../lib/utils";

interface Props {
  files: File[];
  onChange: (files: File[]) => void;
}

export default function Dropzone({ files, onChange }: Props) {
  const [dragOver, setDragOver] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  const addFiles = useCallback(
    (incoming: FileList | null) => {
      if (!incoming) return;
      const pdfs = Array.from(incoming).filter((f) =>
        f.name.toLowerCase().endsWith(".pdf"),
      );
      onChange([...files, ...pdfs]);
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
          Trascina qui i PDF o clicca per scegliere
        </p>
        <p className="text-xs text-ink-500">
          Puoi caricare più documenti insieme
        </p>
        <input
          ref={inputRef}
          type="file"
          accept="application/pdf"
          multiple
          className="hidden"
          onChange={(e) => addFiles(e.target.files)}
        />
      </div>

      {files.length > 0 && (
        <ul className="space-y-2">
          {files.map((f, i) => (
            <li
              key={`${f.name}-${i}`}
              className="flex items-center justify-between rounded-lg border border-ink-200 px-3 py-2 text-sm dark:border-ink-800"
            >
              <span className="truncate">{f.name}</span>
              <button
                onClick={() => onChange(files.filter((_, idx) => idx !== i))}
                className="text-ink-400 hover:text-ink-700 dark:hover:text-ink-200"
                aria-label="Rimuovi"
              >
                <X size={15} />
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
