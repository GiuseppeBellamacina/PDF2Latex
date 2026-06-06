import { ArrowRight, CheckCircle2, ImageIcon, Loader2 } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import Checkbox from "../components/Checkbox";
import SourceReorder from "../components/SourceReorder";
import {
  api,
  type Backends,
  type Figure,
  type Project,
  type Source,
} from "../lib/api";
import { LANGUAGES } from "../lib/languages";

export default function ConfigurePage() {
  const { projectId } = useParams();
  const id = projectId ?? "";
  const navigate = useNavigate();

  const [project, setProject] = useState<Project | null>(null);
  const [backends, setBackends] = useState<Backends | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Editable state
  const [name, setName] = useState("");
  const [author, setAuthor] = useState("");
  const [subtitle, setSubtitle] = useState("");
  const [coverDate, setCoverDate] = useState("");
  const [abstract, setAbstract] = useState("");
  const [prompt, setPrompt] = useState("");
  const [structureHint, setStructureHint] = useState("");
  const [language, setLanguage] = useState("english");
  const [backend, setBackend] = useState("pymupdf");
  const [enableOcr, setEnableOcr] = useState(false);
  const [judgeVision, setJudgeVision] = useState(false);
  const [orderedSources, setOrderedSources] = useState<Source[]>([]);
  const [mandatoryIds, setMandatoryIds] = useState<Set<number>>(new Set());

  useEffect(() => {
    Promise.all([api.getProject(id), api.backends().catch(() => null)])
      .then(([p, b]) => {
        setProject(p);
        setBackends(b);
        setName(p.name ?? "");
        setAuthor(p.author ?? "");
        setSubtitle(p.subtitle ?? "");
        setCoverDate(p.cover_date ?? "");
        setAbstract(p.abstract ?? "");
        setPrompt(p.user_prompt ?? "");
        setStructureHint(p.structure_hint ?? "");
        setLanguage(p.language ?? "english");
        setBackend(p.extractor_backend ?? "pymupdf");
        setEnableOcr(!!p.enable_ocr);
        setJudgeVision(!!p.judge_vision);
        setOrderedSources(
          [...p.sources].sort((a, b) => a.order_index - b.order_index),
        );
        setMandatoryIds(
          new Set(p.figures.filter((f) => f.mandatory).map((f) => f.id)),
        );
      })
      .catch((e) =>
        setError(e instanceof Error ? e.message : "Project not found"),
      )
      .finally(() => setLoading(false));
  }, [id]);

  const figuresBySource = useMemo(() => {
    const map = new Map<string, Figure[]>();
    for (const f of project?.figures ?? []) {
      const key = f.source_filename ?? "—";
      if (!map.has(key)) map.set(key, []);
      map.get(key)!.push(f);
    }
    for (const list of map.values())
      list.sort((a, b) => a.order_index - b.order_index);
    return map;
  }, [project]);

  function toggleMandatory(figId: number) {
    setMandatoryIds((prev) => {
      const next = new Set(prev);
      if (next.has(figId)) next.delete(figId);
      else next.add(figId);
      return next;
    });
  }

  function selectFigures(mode: "suggested" | "all" | "none") {
    const figs = project?.figures ?? [];
    if (mode === "none") return setMandatoryIds(new Set());
    if (mode === "all") return setMandatoryIds(new Set(figs.map((f) => f.id)));
    setMandatoryIds(new Set(figs.filter((f) => f.suggested).map((f) => f.id)));
  }

  async function save(thenGenerate: boolean) {
    setSaving(true);
    setError(null);
    try {
      await api.updateProject(id, {
        name: name.trim() || undefined,
        user_prompt: prompt,
        language,
        author,
        subtitle,
        abstract,
        cover_date: coverDate,
        structure_hint: structureHint,
        extractor_backend: backend,
        enable_ocr: enableOcr,
        judge_vision: judgeVision,
        source_order: orderedSources.map((s) => s.id),
        mandatory_figure_ids: [...mandatoryIds],
      });
      if (thenGenerate) navigate(`/generate/${id}`);
      else {
        const fresh = await api.getProject(id);
        setProject(fresh);
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error while saving");
    } finally {
      setSaving(false);
    }
  }

  if (loading) {
    return (
      <div className="flex items-center gap-2 text-ink-500">
        <Loader2 size={18} className="animate-spin" /> Loading…
      </div>
    );
  }

  if (!project) {
    return (
      <p className="text-sm text-red-500">{error ?? "Project not found"}</p>
    );
  }

  const totalFigures = project.figures.length;

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">
          Configure the document
        </h1>
        <p className="mt-1 text-sm text-ink-500">
          Define cover page, structure, extraction order and mandatory figures
          before generating.
        </p>
      </div>

      {/* Cover / metadata */}
      <section className="card space-y-4">
        <h2 className="text-sm font-semibold uppercase tracking-wide text-ink-400">
          Cover and first page
        </h2>
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <div>
            <label className="mb-1 block text-sm font-medium">Title</label>
            <input
              className="input"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="Document title"
            />
          </div>
          <div>
            <label className="mb-1 block text-sm font-medium">
              Subtitle <span className="text-ink-400">(optional)</span>
            </label>
            <input
              className="input"
              value={subtitle}
              onChange={(e) => setSubtitle(e.target.value)}
              placeholder="e.g. A complete overview"
            />
          </div>
          <div>
            <label className="mb-1 block text-sm font-medium">
              Author <span className="text-ink-400">(optional)</span>
            </label>
            <input
              className="input"
              value={author}
              onChange={(e) => setAuthor(e.target.value)}
              placeholder="First and last name"
            />
          </div>
          <div>
            <label className="mb-1 block text-sm font-medium">
              Date <span className="text-ink-400">(optional)</span>
            </label>
            <input
              className="input"
              value={coverDate}
              onChange={(e) => setCoverDate(e.target.value)}
              placeholder="e.g. January 2025"
            />
          </div>
        </div>
        <div>
          <label className="mb-1 block text-sm font-medium">
            Abstract <span className="text-ink-400">(optional)</span>
          </label>
          <textarea
            className="input min-h-20 resize-y"
            value={abstract}
            onChange={(e) => setAbstract(e.target.value)}
            placeholder="Short summary of the document, shown after the cover page…"
          />
        </div>
      </section>

      {/* Structure / outline */}
      <section className="card space-y-4">
        <h2 className="text-sm font-semibold uppercase tracking-wide text-ink-400">
          Structure, outline and instructions
        </h2>
        <div>
          <label className="mb-1 block text-sm font-medium">
            Desired structure / outline{" "}
            <span className="text-ink-400">(optional)</span>
          </label>
          <textarea
            className="input min-h-24 resize-y"
            value={structureHint}
            onChange={(e) => setStructureHint(e.target.value)}
            placeholder={
              "List chapters, sections, order. e.g.\n1. Introduction\n2. Theoretical foundations\n3. Architectures\n4. Conclusions"
            }
          />
          <p className="mt-1 text-xs text-ink-500">
            If left empty, the structure follows the extraction order of the
            documents.
          </p>
        </div>
        <div>
          <label className="mb-1 block text-sm font-medium">
            Custom instructions <span className="text-ink-400">(optional)</span>
          </label>
          <textarea
            className="input min-h-20 resize-y"
            value={prompt}
            onChange={(e) => setPrompt(e.target.value)}
            placeholder="e.g. Accessible tone, include the key formulas…"
          />
        </div>
      </section>

      {/* Extraction order */}
      <section className="card space-y-4">
        <h2 className="text-sm font-semibold uppercase tracking-wide text-ink-400">
          PDF extraction order
        </h2>
        <p className="text-xs text-ink-500">
          Drag the rows to reorder. The order below determines the sequence in
          which contents are merged into the final document.
        </p>
        <SourceReorder sources={orderedSources} onReorder={setOrderedSources} />
      </section>

      {/* Extraction / OCR */}
      <section className="card space-y-4">
        <h2 className="text-sm font-semibold uppercase tracking-wide text-ink-400">
          Content extraction
        </h2>
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <div>
            <label className="mb-1 block text-sm font-medium">Language</label>
            <select
              className="input"
              value={language}
              onChange={(e) => setLanguage(e.target.value)}
            >
              {LANGUAGES.map((l) => (
                <option key={l.value} value={l.value}>
                  {l.label}
                </option>
              ))}
            </select>
          </div>
          <div>
            <label className="mb-1 block text-sm font-medium">
              Extraction backend
            </label>
            <select
              className="input"
              value={backend}
              onChange={(e) => setBackend(e.target.value)}
            >
              <option value="hybrid">
                Hybrid — recommended (text + figures + OCR)
              </option>
              <option value="pymupdf">PyMuPDF (fast)</option>
              <option
                value="docling"
                disabled={backends ? !backends.docling : false}
              >
                Docling (structured text only)
                {backends && !backends.docling ? " — not installed" : ""}
              </option>
            </select>
          </div>
        </div>
        <Checkbox
          checked={enableOcr}
          disabled={backends ? !backends.ocr : false}
          onChange={setEnableOcr}
          label={
            <>
              Enable OCR on pages (slower, useful for scanned PDFs)
              {backends && !backends.ocr ? (
                <span className="text-ink-500"> — Tesseract not installed</span>
              ) : null}
            </>
          }
        />
        <Checkbox
          checked={judgeVision}
          onChange={setJudgeVision}
          label={
            <>
              Visual judge — review the rendered PDF pages with a vision model
              <span className="text-ink-500">
                {" "}
                (requires a multimodal provider, e.g. GPT-4o; slower)
              </span>
            </>
          }
        />
        <p className="text-xs text-ink-500">
          Figures are already analyzed with OCR at upload time: those containing
          data (charts, diagrams) are marked as{" "}
          <span className="text-emerald-400">Recommended</span> and preselected
          below.
        </p>
      </section>

      {/* Mandatory figures */}
      <section className="card space-y-4">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h2 className="text-sm font-semibold uppercase tracking-wide text-ink-400">
            Figures to include
          </h2>
          <span className="text-xs text-ink-500">
            {mandatoryIds.size} / {totalFigures} selected
          </span>
        </div>
        {totalFigures > 0 && (
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-xs text-ink-500">Quick selection:</span>
            <button
              type="button"
              className="btn-ghost px-2 py-1 text-xs"
              onClick={() => selectFigures("suggested")}
            >
              Recommended
            </button>
            <button
              type="button"
              className="btn-ghost px-2 py-1 text-xs"
              onClick={() => selectFigures("all")}
            >
              All
            </button>
            <button
              type="button"
              className="btn-ghost px-2 py-1 text-xs"
              onClick={() => selectFigures("none")}
            >
              None
            </button>
          </div>
        )}
        {totalFigures === 0 ? (
          <p className="flex items-center gap-2 text-sm text-ink-500">
            <ImageIcon size={16} /> No figures extracted from the PDFs.
          </p>
        ) : (
          <div className="space-y-6">
            {orderedSources.map((s) => {
              const figs = figuresBySource.get(s.filename) ?? [];
              if (figs.length === 0) return null;
              return (
                <div key={s.id} className="space-y-2">
                  <p className="text-sm font-medium text-ink-300">
                    {s.filename}
                  </p>
                  <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 md:grid-cols-4">
                    {figs.map((f) => {
                      const active = mandatoryIds.has(f.id);
                      return (
                        <button
                          key={f.id}
                          type="button"
                          onClick={() => toggleMandatory(f.id)}
                          title={f.caption ?? undefined}
                          className={`group relative overflow-hidden rounded-lg border text-left transition ${
                            active
                              ? "border-emerald-500 ring-2 ring-emerald-500/40"
                              : "border-ink-800/60 hover:border-ink-600"
                          }`}
                        >
                          <img
                            src={api.figureUrl(id, f.rel_path)}
                            alt={`p.${f.page}`}
                            loading="lazy"
                            className="h-28 w-full bg-ink-950 object-contain"
                          />
                          <span className="absolute left-1 top-1 rounded bg-ink-950/80 px-1.5 py-0.5 text-[10px] text-ink-300">
                            p.{f.page}
                          </span>
                          {f.suggested && (
                            <span className="absolute left-1 bottom-1 rounded bg-emerald-500/90 px-1.5 py-0.5 text-[10px] font-medium text-ink-950">
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
      </section>

      {error && <p className="text-sm text-red-500">{error}</p>}

      <div className="flex flex-wrap items-center justify-end gap-3">
        <button
          className="btn-ghost"
          disabled={saving}
          onClick={() => save(false)}
        >
          {saving ? <Loader2 size={16} className="animate-spin" /> : null}
          Save
        </button>
        <button
          className="btn-primary"
          disabled={saving}
          onClick={() => save(true)}
        >
          Save and continue
          <ArrowRight size={16} />
        </button>
      </div>
    </div>
  );
}
