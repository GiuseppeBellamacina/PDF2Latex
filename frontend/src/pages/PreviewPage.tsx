import {
  Download,
  FileArchive,
  FileCode,
  FilePen,
  FileText,
  Gavel,
  Hammer,
  Loader2,
  RefreshCw,
  Save,
  Undo2,
  Wand2,
} from "lucide-react";
import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { api, type Project, type ProjectFile, type Section } from "../lib/api";
import { useAppStore } from "../stores/appStore";
import { cn } from "../lib/utils";
import { FileEditor } from "../components/FileEditor";

export default function PreviewPage() {
  const { projectId } = useParams();
  const id = projectId ?? "";
  const [project, setProject] = useState<Project | null>(null);
  const [latex, setLatex] = useState<string>("");
  const [tab, setTab] = useState<"pdf" | "files" | "latex" | "fix">("pdf");
  // Bump to force the PDF iframe to reload after a recompile.
  const [pdfVersion, setPdfVersion] = useState(0);

  useEffect(() => {
    api
      .getProject(id)
      .then(setProject)
      .catch(() => {});
    api
      .previewLatex(id)
      .then((r) => setLatex(r.latex))
      .catch(() => setLatex(""));
  }, [id]);

  const hasPdf = !!project?.output_pdf_path;

  async function refreshAfterFix() {
    const [p, lx] = await Promise.all([
      api.getProject(id),
      api.previewLatex(id).catch(() => ({ latex })),
    ]);
    setProject(p);
    setLatex(lx.latex);
    setPdfVersion((v) => v + 1);
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">
            {project?.name ?? "Preview"}
          </h1>
          <p className="mt-1 text-sm text-ink-500">
            Status: {project?.status} · {project?.total_sections ?? 0} sections
          </p>
        </div>
        <div className="flex gap-2">
          <a className="btn-ghost" href={api.downloadUrl(id, "tex")}>
            <FileArchive size={16} /> LaTeX (.zip)
          </a>
          {hasPdf && (
            <a className="btn-primary" href={api.downloadUrl(id, "pdf")}>
              <Download size={16} /> PDF
            </a>
          )}
        </div>
      </div>

      <div className="flex gap-1">
        {(["pdf", "files", "latex", "fix"] as const).map((t) => (
          <button
            key={t}
            onClick={() => setTab(t)}
            className={cn(
              "btn-ghost border-transparent",
              tab === t && "bg-ink-200 dark:bg-ink-800",
            )}
          >
            {t === "pdf" ? (
              <FileText size={15} />
            ) : t === "files" ? (
              <FilePen size={15} />
            ) : t === "latex" ? (
              <FileCode size={15} />
            ) : (
              <Wand2 size={15} />
            )}
            {t === "pdf"
              ? "PDF"
              : t === "files"
                ? "Files"
                : t === "latex"
                  ? "LaTeX source"
                  : "Quick fixes"}
          </button>
        ))}
      </div>

      {tab === "fix" ? (
        <QuickFixes
          projectId={id}
          sections={project?.sections ?? []}
          onApplied={refreshAfterFix}
        />
      ) : tab === "files" ? (
        <FilesPanel
          projectId={id}
          onSaved={async (ok) => {
            await refreshAfterFix();
            if (ok) setTab("pdf");
          }}
        />
      ) : (
        <div className="card overflow-hidden p-0">
          {tab === "pdf" ? (
            hasPdf ? (
              <iframe
                title="PDF"
                src={`${api.viewPdfUrl(id)}?v=${pdfVersion}`}
                className="h-[70vh] w-full"
              />
            ) : (
              <div className="p-10 text-center text-sm text-ink-500">
                PDF not available. {project?.error_message}
              </div>
            )
          ) : (
            <pre className="max-h-[70vh] overflow-auto p-4 font-mono text-xs leading-relaxed">
              {latex || "No source available."}
            </pre>
          )}
        </div>
      )}
    </div>
  );
}

function FilesPanel({
  projectId,
  onSaved,
}: {
  projectId: string;
  onSaved: (success: boolean) => Promise<void> | void;
}) {
  const [files, setFiles] = useState<ProjectFile[]>([]);
  const [active, setActive] = useState(0);
  const [draft, setDraft] = useState("");
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);

  async function load(keepActive = false) {
    setLoading(true);
    try {
      const fs = await api.getFiles(projectId);
      setFiles(fs);
      const idx = keepActive ? Math.min(active, fs.length - 1) : 0;
      setActive(Math.max(0, idx));
      setDraft(fs[Math.max(0, idx)]?.content ?? "");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectId]);

  function select(idx: number) {
    setActive(idx);
    setDraft(files[idx]?.content ?? "");
    setMsg(null);
  }

  const current = files[active];
  const dirty = current ? draft !== current.content : false;

  async function save() {
    if (!current) return;
    setBusy(true);
    setMsg(null);
    try {
      const r = await api.saveFile(projectId, {
        kind: current.kind,
        section_id: current.section_id,
        content: draft,
      });
      setMsg({
        ok: r.success,
        text: r.success
          ? "Saved and recompiled."
          : `Saved, but compilation failed: ${r.log_excerpt || "see logs"}`,
      });
      // Refresh files (main.tex/parts may have changed) and the PDF.
      const fs = await api.getFiles(projectId);
      setFiles(fs);
      setDraft(fs[active]?.content ?? draft);
      await onSaved(r.success);
    } catch (e) {
      setMsg({ ok: false, text: e instanceof Error ? e.message : "Failed" });
    } finally {
      setBusy(false);
    }
  }

  if (loading) {
    return (
      <div className="card flex items-center gap-2 text-sm text-ink-500">
        <Loader2 size={16} className="animate-spin" /> Loading files…
      </div>
    );
  }

  if (files.length === 0) {
    return (
      <div className="card text-sm text-ink-500">
        No files yet. Generate the document first.
      </div>
    );
  }

  return (
    <div className="grid grid-cols-[220px_1fr] gap-4">
      <div className="card h-fit space-y-1 p-2">
        {files.map((f, i) => (
          <button
            key={f.name}
            onClick={() => select(i)}
            className={cn(
              "flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-sm",
              i === active
                ? "bg-ink-200 dark:bg-ink-800"
                : "hover:bg-ink-100 dark:hover:bg-ink-900",
            )}
            title={f.name}
          >
            {f.kind === "bib" ? (
              <FileText size={14} className="shrink-0 text-ink-500" />
            ) : (
              <FileCode size={14} className="shrink-0 text-ink-500" />
            )}
            <span className="truncate">{f.name}</span>
          </button>
        ))}
      </div>

      <div className="space-y-3">
        <div className="flex items-center justify-between">
          <div className="text-sm">
            <span className="font-medium">{current?.name}</span>
            {dirty && (
              <span className="ml-2 text-xs text-amber-600 dark:text-amber-400">
                unsaved changes
              </span>
            )}
          </div>
          <button
            className="btn-primary"
            onClick={save}
            disabled={busy || !dirty}
          >
            {busy ? (
              <Loader2 size={16} className="animate-spin" />
            ) : (
              <Save size={16} />
            )}
            Save &amp; compile
          </button>
        </div>
        <div className="card overflow-hidden p-0">
          <FileEditor
            key={current?.name}
            value={draft}
            language={current?.language ?? "latex"}
            onChange={setDraft}
          />
        </div>
        {msg && (
          <p
            className={cn(
              "text-xs",
              msg.ok
                ? "text-emerald-600 dark:text-emerald-400"
                : "text-amber-600 dark:text-amber-400",
            )}
          >
            {msg.text}
          </p>
        )}
      </div>
    </div>
  );
}

function QuickFixes({
  projectId,
  sections,
  onApplied,
}: {
  projectId: string;
  sections: Section[];
  onApplied: () => Promise<void> | void;
}) {
  const { providers, selectedProviderId, loadProviders, setSelectedProvider } =
    useAppStore();

  useEffect(() => {
    if (providers.length === 0) loadProviders();
  }, [providers.length, loadProviders]);

  if (sections.length === 0) {
    return (
      <div className="card text-sm text-ink-500">
        No sections yet. Generate the document first, then come back to apply
        quick fixes.
      </div>
    );
  }

  const ordered = [...sections].sort((a, b) => a.order_index - b.order_index);

  return (
    <div className="space-y-4">
      <div className="card space-y-3">
        <div>
          <h2 className="text-sm font-semibold">Quick fixes</h2>
          <p className="mt-1 text-sm text-ink-500">
            Type a short instruction for a section (e.g. “shorten the
            introduction”, “add a bulleted summary”, “fix the table”). The
            section is rewritten and the PDF recompiled.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <label className="text-sm font-medium">Model provider</label>
          <select
            className="input max-w-xs"
            value={selectedProviderId ?? ""}
            onChange={(e) => setSelectedProvider(Number(e.target.value))}
          >
            <option value="" disabled>
              Select a provider
            </option>
            {providers.map((p) => (
              <option key={p.id} value={p.id}>
                {p.name} ({p.provider_type})
              </option>
            ))}
          </select>
        </div>
        <DocumentActions
          projectId={projectId}
          providerId={selectedProviderId}
          onApplied={onApplied}
        />
      </div>

      {ordered.map((s) => (
        <SectionFix
          key={s.id}
          projectId={projectId}
          section={s}
          providerId={selectedProviderId}
          onApplied={onApplied}
        />
      ))}
    </div>
  );
}

function DocumentActions({
  projectId,
  providerId,
  onApplied,
}: {
  projectId: string;
  providerId: number | null;
  onApplied: () => Promise<void> | void;
}) {
  const [busy, setBusy] = useState<"recompile" | "rejudge" | null>(null);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);

  async function recompile() {
    if (providerId == null) return;
    setBusy("recompile");
    setMsg(null);
    try {
      const r = await api.recompile(projectId, { provider_id: providerId });
      setMsg({
        ok: r.success,
        text: r.success
          ? "Recompiled successfully."
          : `Still failing: ${r.log_excerpt || "see logs"}`,
      });
      await onApplied();
    } catch (e) {
      setMsg({ ok: false, text: e instanceof Error ? e.message : "Failed" });
    } finally {
      setBusy(null);
    }
  }

  async function rejudge() {
    if (providerId == null) return;
    setBusy("rejudge");
    setMsg(null);
    try {
      const r = await api.rejudge(projectId, { provider_id: providerId });
      const text = r.applied
        ? `Revision applied (${r.issues.length} issue(s), score ${r.score}). ${
            r.success ? "Recompiled." : "Recompile failed."
          }`
        : `Approved (score ${r.score}). No changes needed.`;
      setMsg({ ok: r.success, text });
      await onApplied();
    } catch (e) {
      setMsg({ ok: false, text: e instanceof Error ? e.message : "Failed" });
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="space-y-2 border-t border-ink-200 pt-3 dark:border-ink-800">
      <p className="text-xs text-ink-500">
        Recover a failed run or push the document one more round, without
        redoing analysis &amp; writing.
      </p>
      <div className="flex flex-wrap gap-2">
        <button
          className="btn-ghost"
          onClick={recompile}
          disabled={busy !== null || providerId == null}
          title="Reassemble the sections and compile again (with auto-fix retries)"
        >
          {busy === "recompile" ? (
            <Loader2 size={16} className="animate-spin" />
          ) : (
            <Hammer size={16} />
          )}
          Retry compilation
        </button>
        <button
          className="btn-ghost"
          onClick={rejudge}
          disabled={busy !== null || providerId == null}
          title="Run the structural judge again and apply its revision if needed"
        >
          {busy === "rejudge" ? (
            <Loader2 size={16} className="animate-spin" />
          ) : (
            <Gavel size={16} />
          )}
          Run judge
        </button>
      </div>
      {msg && (
        <p
          className={cn(
            "text-xs",
            msg.ok
              ? "text-emerald-600 dark:text-emerald-400"
              : "text-amber-600 dark:text-amber-400",
          )}
        >
          {msg.text}
        </p>
      )}
    </div>
  );
}

function SectionFix({
  projectId,
  section,
  providerId,
  onApplied,
}: {
  projectId: string;
  section: Section;
  providerId: number | null;
  onApplied: () => Promise<void> | void;
}) {
  const [prompt, setPrompt] = useState("");
  const [busy, setBusy] = useState<"apply" | "regenerate" | "undo" | null>(
    null,
  );
  const [result, setResult] = useState<string | null>(null);
  const [ok, setOk] = useState(false);

  async function apply() {
    if (!prompt.trim() || providerId == null) return;
    setBusy("apply");
    setResult(null);
    try {
      const r = await api.refineSection(projectId, section.id, {
        provider_id: providerId,
        extra_prompt: prompt,
      });
      setOk(r.success);
      setResult(
        r.success
          ? "Applied and recompiled."
          : `Recompiled with errors: ${r.log_excerpt || "see logs"}`,
      );
      setPrompt("");
      await onApplied();
    } catch (e) {
      setOk(false);
      setResult(e instanceof Error ? e.message : "Request failed");
    } finally {
      setBusy(null);
    }
  }

  async function regenerate() {
    if (providerId == null) return;
    setBusy("regenerate");
    setResult(null);
    try {
      const r = await api.regenerateSection(projectId, section.id, {
        provider_id: providerId,
      });
      setOk(r.success);
      setResult(
        r.success
          ? "Regenerated from source and recompiled."
          : `Recompiled with errors: ${r.log_excerpt || "see logs"}`,
      );
      await onApplied();
    } catch (e) {
      setOk(false);
      setResult(e instanceof Error ? e.message : "Request failed");
    } finally {
      setBusy(null);
    }
  }

  async function undo() {
    setBusy("undo");
    setResult(null);
    try {
      const r = await api.undoSection(projectId, section.id);
      setOk(r.success);
      setResult(
        r.success ? "Reverted and recompiled." : "Reverted (recompile errors).",
      );
      await onApplied();
    } catch (e) {
      setOk(false);
      setResult(e instanceof Error ? e.message : "Request failed");
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="card space-y-2">
      <div className="flex items-baseline justify-between gap-2">
        <p className="text-sm font-medium">{section.title}</p>
        {section.part_title && (
          <span className="text-xs text-ink-500">{section.part_title}</span>
        )}
      </div>
      <div className="flex gap-2">
        <input
          className="input flex-1"
          placeholder="Instruction for this section…"
          value={prompt}
          onChange={(e) => setPrompt(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") apply();
          }}
          disabled={busy !== null}
        />
        <button
          className="btn-primary"
          onClick={apply}
          disabled={busy !== null || !prompt.trim() || providerId == null}
        >
          {busy === "apply" ? (
            <Loader2 size={16} className="animate-spin" />
          ) : (
            <Wand2 size={16} />
          )}
          Apply
        </button>
      </div>
      <div className="flex flex-wrap gap-2">
        <button
          className="btn-ghost text-xs"
          onClick={regenerate}
          disabled={busy !== null || providerId == null || !section.has_source}
          title={
            section.has_source
              ? "Re-author this section from its source PDFs"
              : "Source data unavailable (regenerate the whole document to enable)"
          }
        >
          {busy === "regenerate" ? (
            <Loader2 size={14} className="animate-spin" />
          ) : (
            <RefreshCw size={14} />
          )}
          Regenerate from source
        </button>
        <button
          className="btn-ghost text-xs"
          onClick={undo}
          disabled={busy !== null || !section.has_undo}
          title={
            section.has_undo
              ? "Revert the last change to this section"
              : "Nothing to undo"
          }
        >
          {busy === "undo" ? (
            <Loader2 size={14} className="animate-spin" />
          ) : (
            <Undo2 size={14} />
          )}
          Undo
        </button>
      </div>
      {result && (
        <p
          className={cn(
            "text-xs",
            ok
              ? "text-emerald-600 dark:text-emerald-400"
              : "text-amber-600 dark:text-amber-400",
          )}
        >
          {result}
        </p>
      )}
    </div>
  );
}
