import { CheckCircle2, ImageIcon, ImageOff, ImagePlus, Pencil, Trash2, Upload, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import type { Figure, Source } from "../../lib/api";
import { api } from "../../lib/api";

interface Props {
  projectId: string;
  orderedSources: Source[];
  figuresBySource: Map<string, Figure[]>;
  mandatoryIds: Set<number>;
  toggleMandatory: (figId: number) => void;
  selectFigures: (mode: "suggested" | "all" | "none") => void;
  totalFigures: number;
  // User-uploaded figures
  userUploadedFigures: Figure[];
  onUploaded: () => void;
}

export default function FiguresPanel({
  projectId,
  orderedSources,
  figuresBySource,
  mandatoryIds,
  toggleMandatory,
  selectFigures,
  totalFigures,
  userUploadedFigures,
  onUploaded,
}: Props) {
  const [uploadOpen, setUploadOpen] = useState(false);
  const [uploadFile, setUploadFile] = useState<File | null>(null);
  const [uploadCaption, setUploadCaption] = useState("");
  const [uploadTarget, setUploadTarget] = useState("");
  const [uploading, setUploading] = useState(false);
  const [deletingId, setDeletingId] = useState<number | null>(null);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [deleteError, setDeleteError] = useState<string | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  // ── Inline editing state ────────────────────────────────────
  const [editingId, setEditingId] = useState<number | null>(null);
  const [editCaption, setEditCaption] = useState("");
  const [editTarget, setEditTarget] = useState("");
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const captionRef = useRef<HTMLInputElement>(null);
  const targetRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (editingId !== null) {
      captionRef.current?.focus();
    }
  }, [editingId]);

  function startEditing(fig: Figure) {
    setEditingId(fig.id);
    setEditCaption(fig.custom_caption ?? fig.caption ?? "");
    setEditTarget(fig.target_section_title ?? "");
    setSaveError(null);
  }

  function cancelEditing() {
    setEditingId(null);
    setSaveError(null);
  }

  async function saveEditing(figureId: number) {
    const captionChanged = editCaption !== (userUploadedFigures.find(f => f.id === figureId)?.custom_caption ?? userUploadedFigures.find(f => f.id === figureId)?.caption ?? "");
    const targetChanged = editTarget !== (userUploadedFigures.find(f => f.id === figureId)?.target_section_title ?? "");
    if (!captionChanged && !targetChanged) {
      setEditingId(null);
      return;
    }
    setSaving(true);
    setSaveError(null);
    try {
      await api.updateUserFigure(projectId, figureId, {
        custom_caption: captionChanged ? editCaption.trim() : undefined,
        target_section_title: targetChanged ? editTarget.trim() : undefined,
      });
      setEditingId(null);
      onUploaded();
    } catch (e) {
      setSaveError(e instanceof Error ? e.message : "Save failed");
    } finally {
      setSaving(false);
    }
  }

  async function handleUpload() {
    if (!uploadFile) return;
    setUploading(true);
    setUploadError(null);
    try {
      await api.uploadUserFigure(projectId, uploadFile, uploadCaption.trim(), uploadTarget.trim());
      setUploadFile(null);
      setUploadCaption("");
      setUploadTarget("");
      setUploadOpen(false);
      if (fileRef.current) fileRef.current.value = "";
      onUploaded();
    } catch (e) {
      setUploadError(e instanceof Error ? e.message : "Upload failed");
    } finally {
      setUploading(false);
    }
  }

  async function handleDelete(figureId: number) {
    setDeletingId(figureId);
    setDeleteError(null);
    try {
      await api.deleteUserFigure(projectId, figureId);
      onUploaded();
    } catch (e) {
      setDeleteError(e instanceof Error ? e.message : "Delete failed");
    } finally {
      setDeletingId(null);
    }
  }

  return (
    <div className="space-y-7">
      {/* ── Extracted figures ──────────────────────────────── */}
      <div className="space-y-5">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div className="flex items-center gap-2.5">
            <span className="rounded-lg bg-ink-100 p-1.5 text-ink-500 dark:bg-ink-800 dark:text-ink-400">
              <ImageIcon size={16} />
            </span>
            <h2 className="text-sm font-semibold uppercase tracking-wide text-ink-400">
              Extracted figures
            </h2>
          </div>
          <span className="text-xs tabular-nums text-ink-500">
            {mandatoryIds.size} / {totalFigures} selected
          </span>
        </div>

        {totalFigures > 0 && (
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-xs text-ink-500">Quick:</span>
            {(["suggested", "all", "none"] as const).map((mode) => (
              <button
                key={mode}
                type="button"
                className="btn-ghost px-2 py-1 text-xs"
                onClick={() => selectFigures(mode)}
              >
                {mode === "suggested" ? "Recommended" : mode === "all" ? "All" : "None"}
              </button>
            ))}
          </div>
        )}

        {totalFigures === 0 ? (
          <div className="flex flex-col items-center gap-3 rounded-xl border border-dashed border-ink-200 py-8 dark:border-ink-700">
            <ImageOff size={24} className="text-ink-300" />
            <p className="text-sm text-ink-500">No figures extracted from the PDFs.</p>
          </div>
        ) : (
          <div className="space-y-6">
            {orderedSources.map((s) => {
              const figs = figuresBySource.get(s.filename) ?? [];
              if (figs.length === 0) return null;
              return (
                <div key={s.id} className="space-y-2">
                  <p className="text-sm font-medium text-ink-400">{s.filename}</p>
                  <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 md:grid-cols-4">
                    {figs.map((f) => {
                      const active = mandatoryIds.has(f.id);
                      return (
                        <button
                          key={f.id}
                          type="button"
                          onClick={() => toggleMandatory(f.id)}
                          title={f.caption ?? undefined}
                          className={`group relative overflow-hidden rounded-lg border text-left transition hover:scale-[1.03] ${
                            active
                              ? "border-emerald-500 ring-2 ring-emerald-500/40 shadow-md"
                              : "border-ink-800/60 shadow-sm hover:border-ink-600 hover:shadow-md"
                          }`}
                        >
                          <img
                            src={api.figureUrl(projectId, f.rel_path)}
                            alt={`p.${f.page}`}
                            loading="lazy"
                            className="h-28 w-full bg-ink-950 object-contain"
                          />
                          <span className="absolute left-1 top-1 rounded bg-ink-950/80 px-1.5 py-0.5 text-[10px] text-ink-300">
                            p.{f.page}
                          </span>
                          {f.suggested && (
                            <span className="absolute bottom-1 left-1 rounded bg-emerald-500/90 px-1.5 py-0.5 text-[10px] font-medium text-ink-950">
                              Recommended
                            </span>
                          )}
                          {active && (
                            <span className="absolute right-1 top-1 text-emerald-400">
                              <CheckCircle2 size={18} />
                            </span>
                          )}
                          {f.caption && (
                            <span className="block truncate px-1.5 py-1 text-[10px] text-ink-500">
                              {f.caption}
                            </span>
                          )}
                        </button>
                      );
                    })}
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>

      {/* ── User-uploaded figures ──────────────────────────── */}
      <div className="space-y-4 border-t border-ink-200 pt-6 dark:border-ink-800">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2.5">
            <span className="rounded-lg bg-violet-100 p-1.5 text-violet-600 dark:bg-violet-900/30 dark:text-violet-400">
              <ImagePlus size={16} />
            </span>
            <h2 className="text-sm font-semibold uppercase tracking-wide text-ink-400">
              Your images
            </h2>
          </div>
          <button
            type="button"
            className="btn-ghost flex items-center gap-1.5 px-2 py-1 text-xs"
            onClick={() => setUploadOpen((o) => !o)}
          >
            {uploadOpen ? <X size={14} /> : <Upload size={14} />}
            {uploadOpen ? "Cancel" : "Upload image"}
          </button>
        </div>

        <p className="text-xs text-ink-500">
          Upload your own images and specify where they should appear. Each
          image is always included in the document.
        </p>

        {deleteError && (
          <p className="text-xs text-red-500">{deleteError}</p>
        )}

        {/* Upload form */}
        {uploadOpen && (
          <div className="space-y-3 rounded-lg border border-dashed border-violet-300 bg-violet-50/40 p-4 dark:border-violet-800 dark:bg-violet-950/20">
            <div>
              <label className="mb-1 block text-xs font-medium text-ink-500">Image file</label>
              <input
                ref={fileRef}
                type="file"
                accept="image/png,image/jpeg,image/gif,image/webp,image/bmp"
                onChange={(e) => setUploadFile(e.target.files?.[0] ?? null)}
                className="block w-full text-xs text-ink-500 file:mr-3 file:rounded-md file:border-0 file:bg-violet-100 file:px-3 file:py-1.5 file:text-xs file:font-medium file:text-violet-700 hover:file:bg-violet-200 dark:file:bg-violet-900/40 dark:file:text-violet-300"
              />
            </div>
            <div>
              <label className="mb-1 block text-xs font-medium text-ink-500">
                Caption <span className="font-normal text-ink-400">(optional)</span>
              </label>
              <input
                type="text"
                value={uploadCaption}
                onChange={(e) => setUploadCaption(e.target.value)}
                placeholder="Figure caption in LaTeX…"
                className="input w-full text-sm"
              />
            </div>
            <div>
              <label className="mb-1 block text-xs font-medium text-ink-500">
                Target section <span className="font-normal text-ink-400">(title or &ldquo;Part — Section&rdquo;)</span>
              </label>
              <input
                type="text"
                value={uploadTarget}
                onChange={(e) => setUploadTarget(e.target.value)}
                placeholder='e.g. "Introduction" or "Part I — Background"'
                className="input w-full text-sm"
              />
            </div>
            {uploadError && (
              <p className="text-xs text-red-500">{uploadError}</p>
            )}
            <button
              type="button"
              disabled={!uploadFile || uploading}
              className="btn-primary flex items-center gap-2 px-4 py-2 text-sm"
              onClick={handleUpload}
            >
              {uploading ? (
                <>
                  <span className="h-4 w-4 animate-spin rounded-full border-2 border-white/30 border-t-white" />
                  Uploading…
                </>
              ) : (
                <>
                  <Upload size={15} />
                  Upload image
                </>
              )}
            </button>
          </div>
        )}

        {/* User-uploaded figures grid */}
        {saveError && (
          <p className="text-xs text-red-500">{saveError}</p>
        )}
        {userUploadedFigures.length === 0 ? (
          !uploadOpen && (
            <div className="flex flex-col items-center gap-2 rounded-xl border border-dashed border-ink-200 py-6 dark:border-ink-700">
              <ImagePlus size={22} className="text-ink-300" />
              <p className="text-xs text-ink-500">No custom images uploaded yet.</p>
            </div>
          )
        ) : (
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 md:grid-cols-4">
            {userUploadedFigures.map((f) => (
              <div
                key={f.id}
                className="group relative overflow-hidden rounded-lg border border-violet-500/40 bg-violet-50/30 shadow-sm dark:border-violet-700/40 dark:bg-violet-950/15"
              >
                {editingId === f.id ? (
                  /* ── Inline edit card ─────────────────────── */
                  <div className="space-y-2 p-2">
                    <img
                      src={api.figureUrl(projectId, f.rel_path)}
                      alt={f.custom_caption ?? f.caption ?? "User image"}
                      loading="lazy"
                      className="h-20 w-full rounded bg-ink-950 object-contain"
                    />
                    <input
                      ref={captionRef}
                      type="text"
                      value={editCaption}
                      onChange={(e) => setEditCaption(e.target.value)}
                      placeholder="Caption…"
                      className="input w-full px-2 py-1 text-xs"
                      onKeyDown={(e) => {
                        if (e.key === "Enter") saveEditing(f.id);
                        if (e.key === "Escape") cancelEditing();
                      }}
                    />
                    <input
                      ref={targetRef}
                      type="text"
                      value={editTarget}
                      onChange={(e) => setEditTarget(e.target.value)}
                      placeholder="Target section…"
                      className="input w-full px-2 py-1 text-xs"
                      onKeyDown={(e) => {
                        if (e.key === "Enter") saveEditing(f.id);
                        if (e.key === "Escape") cancelEditing();
                      }}
                    />
                    <div className="flex gap-1.5">
                      <button
                        type="button"
                        disabled={saving}
                        onClick={() => saveEditing(f.id)}
                        className="btn-primary flex-1 px-2 py-1 text-xs"
                      >
                        {saving ? "Saving…" : "Save"}
                      </button>
                      <button
                        type="button"
                        disabled={saving}
                        onClick={cancelEditing}
                        className="btn-ghost px-2 py-1 text-xs"
                      >
                        Cancel
                      </button>
                    </div>
                  </div>
                ) : (
                  /* ── Normal card ──────────────────────────── */
                  <>
                    <img
                      src={api.figureUrl(projectId, f.rel_path)}
                      alt={f.custom_caption ?? f.caption ?? "User image"}
                      loading="lazy"
                      className="h-28 w-full bg-ink-950 object-contain"
                    />
                    <span className="absolute left-1 top-1 rounded bg-violet-500/90 px-1.5 py-0.5 text-[10px] font-medium text-white">
                      You
                    </span>
                    <button
                      type="button"
                      disabled={deletingId === f.id}
                      onClick={() => handleDelete(f.id)}
                      className="absolute right-1 top-1 rounded bg-ink-950/70 p-1 text-red-400 opacity-0 transition hover:bg-red-500/20 hover:text-red-300 group-hover:opacity-100"
                      title="Delete image"
                    >
                      <Trash2 size={14} />
                    </button>
                    {/* Click-to-edit pencil */}
                    <button
                      type="button"
                      onClick={() => startEditing(f)}
                      className="absolute right-8 top-1 rounded bg-ink-950/70 p-1 text-violet-400 opacity-0 transition hover:bg-violet-500/20 hover:text-violet-300 group-hover:opacity-100"
                      title="Edit caption & target"
                    >
                      <Pencil size={13} />
                    </button>
                    {/* Editable caption */}
                    <button
                      type="button"
                      onClick={() => startEditing(f)}
                      className="block w-full truncate px-1.5 py-1 text-left text-[10px] text-violet-600 hover:underline hover:decoration-dotted dark:text-violet-400"
                      title="Click to edit caption"
                    >
                      {f.custom_caption || "+ add caption"}
                    </button>
                    {/* Editable target section */}
                    <button
                      type="button"
                      onClick={() => startEditing(f)}
                      className="block w-full truncate px-1.5 pb-1 text-left text-[9px] text-ink-400 hover:underline hover:decoration-dotted"
                      title="Click to edit target section"
                    >
                      → {f.target_section_title || "unassigned"}
                    </button>
                  </>
                )}
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
