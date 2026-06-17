import {
  ArrowRight,
  BookOpen,
  ImageIcon,
  Layers,
  ListTree,
  Loader2,
  Palette,
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { api, type Figure, type LatexTemplate, type Project, type Source } from "../lib/api";
import InformationPanel from "../components/configure/InformationPanel";
import StructurePanel from "../components/configure/StructurePanel";
import PipelinePanel from "../components/configure/PipelinePanel";
import StylePanel from "../components/configure/StylePanel";
import FiguresPanel from "../components/configure/FiguresPanel";
import { cn, parseUserSources, type ParsedSource } from "../lib/utils";

const DEFAULT_PIPELINE: Record<string, string> = {
  text: "pymupdf", structure: "docling", ocr: "tesseract",
  math: "none", figures: "pymupdf", figure_scoring: "heuristic",
};

type SectionKey = "info" | "structure" | "pipeline" | "style" | "figures";

const SIDEBAR: { key: SectionKey; label: string; icon: typeof BookOpen }[] = [
  { key: "info", label: "Cover & Metadata", icon: BookOpen },
  { key: "structure", label: "Structure & Outline", icon: ListTree },
  { key: "pipeline", label: "Extraction Pipeline", icon: Layers },
  { key: "style", label: "Language & Style", icon: Palette },
  { key: "figures", label: "Figures", icon: ImageIcon },
];

export default function ConfigurePage() {
  const { projectId } = useParams();
  const id = projectId ?? "";
  const navigate = useNavigate();

  const [project, setProject] = useState<Project | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [activeSection, setActiveSection] = useState<SectionKey>("info");

  // Editable state
  const [name, setName] = useState("");
  const [author, setAuthor] = useState("");
  const [subtitle, setSubtitle] = useState("");
  const [coverDate, setCoverDate] = useState("");
  const [abstract, setAbstract] = useState("");
  const [prompt, setPrompt] = useState("");
  const [structureHint, setStructureHint] = useState("");
  const [language, setLanguage] = useState("english");
  const [ocrLang, setOcrLang] = useState("");
  const [ocrLangTouched, setOcrLangTouched] = useState(false);
  const [writerUseKnowledge, setWriterUseKnowledge] = useState(false);
  const [userSourcesRaw, setUserSourcesRaw] = useState("");
  const [pipelineConfig, setPipelineConfig] = useState<Record<string, string>>(DEFAULT_PIPELINE);
  const [latexTemplate, setLatexTemplate] = useState("default");
  const [availableTemplates, setAvailableTemplates] = useState<LatexTemplate[]>([]);
  const [orderedSources, setOrderedSources] = useState<Source[]>([]);
  const [mandatoryIds, setMandatoryIds] = useState<Set<number>>(new Set());
  const [showSummary, setShowSummary] = useState(false);
  const [refreshKey, setRefreshKey] = useState(0);

  useEffect(() => {
    api.getProject(id).then((p) => {
      // No figure edit state needed — user can delete + re-upload to change captions/targets.
      setProject(p);
      setName(p.name ?? "");
      setAuthor(p.author ?? "");
      setSubtitle(p.subtitle ?? "");
      setCoverDate(p.cover_date ?? "");
      setAbstract(p.abstract ?? "");
      setPrompt(p.user_prompt ?? "");
      setStructureHint(p.structure_hint ?? "");
      setLanguage(p.language ?? "english");
      setOcrLang(p.ocr_lang ?? "");
      setLatexTemplate(p.latex_template ?? "default");
      setWriterUseKnowledge(p.writer_use_knowledge ?? false);
      if (p.user_sources?.length) {
        setUserSourcesRaw(
          p.user_sources.map((s) =>
            [s.authors, s.title, s.year, s.venue || ""].map((x) => x.trim()).join(" | ").replace(/\s+\|\s*$/, "")
          ).join("\n"),
        );
      }
      if (p.pipeline_config && Object.keys(p.pipeline_config).length > 0) {
        setPipelineConfig(p.pipeline_config);
      }
      setOrderedSources([...p.sources].sort((a, b) => a.order_index - b.order_index));
      setMandatoryIds(new Set(p.figures.filter((f) => f.mandatory).map((f) => f.id)));
    }).catch((e) => setError(e instanceof Error ? e.message : "Project not found"))
      .finally(() => setLoading(false));

    api.listTemplates().then(setAvailableTemplates).catch(() => {});
  }, [id, refreshKey]);

  const figuresBySource = useMemo(() => {
    const map = new Map<string, Figure[]>();
    for (const f of project?.figures ?? []) {
      const key = f.source_filename ?? "—";
      if (!map.has(key)) map.set(key, []);
      map.get(key)!.push(f);
    }
    for (const list of map.values()) list.sort((a, b) => a.order_index - b.order_index);
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
        ocr_lang: ocrLang || null,
        writer_use_knowledge: writerUseKnowledge,
        user_sources: parseUserSources(userSourcesRaw),
        author, subtitle, abstract,
        cover_date: coverDate,
        structure_hint: structureHint,
        pipeline_config: pipelineConfig,
        latex_template: latexTemplate || null,
        source_order: orderedSources.map((s) => s.id),
        mandatory_figure_ids: [...mandatoryIds],
      });
      if (thenGenerate) { setShowSummary(true); } else { setProject(await api.getProject(id)); }
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error while saving");
    } finally { setSaving(false); }
  }

  if (loading) return <div className="flex items-center gap-2 text-ink-500"><Loader2 size={18} className="animate-spin" /> Loading…</div>;
  if (!project) return <p className="text-sm text-red-500">{error ?? "Project not found"}</p>;

  const totalFigures = project.figures.filter((f) => !f.user_uploaded).length;
  const userUploadedFigures = project.figures.filter((f) => f.user_uploaded);
  const parsedUserSources: ParsedSource[] = parseUserSources(userSourcesRaw);

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Configure {project.name}</h1>
        <p className="mt-1 text-sm text-ink-500">
          {project.total_sources} documents · {totalFigures} figures extracted
        </p>
      </div>

      <div className="flex gap-6">
        {/* Sidebar */}
        <nav className="hidden w-52 shrink-0 flex-col gap-1 sm:flex">
          {SIDEBAR.map(({ key, label, icon: Icon }) => (
            <button
              key={key}
              onClick={() => setActiveSection(key)}
              className={cn(
                "flex items-center gap-2.5 rounded-lg px-3 py-2 text-left text-sm font-medium transition-colors",
                activeSection === key
                  ? "bg-ink-900 text-ink-50 dark:bg-ink-100 dark:text-ink-950"
                  : "text-ink-500 hover:bg-ink-100 hover:text-ink-700 dark:hover:bg-ink-800 dark:hover:text-ink-300",
              )}
            >
              <Icon size={15} />
              {label}
            </button>
          ))}
        </nav>

        {/* Mobile: horizontal tabs */}
        <div className="flex gap-1 overflow-x-auto pb-2 sm:hidden">
          {SIDEBAR.map(({ key, label, icon: Icon }) => (
            <button
              key={key}
              onClick={() => setActiveSection(key)}
              className={cn(
                "flex shrink-0 items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs font-medium transition-colors",
                activeSection === key
                  ? "bg-ink-900 text-ink-50 dark:bg-ink-100 dark:text-ink-950"
                  : "text-ink-500 border border-ink-200 dark:border-ink-700",
              )}
            >
              <Icon size={13} />
              {label}
            </button>
          ))}
        </div>

        {/* Content panel */}
        <div className="min-w-0 flex-1">
          <div className="card">
            {activeSection === "info" && (
              <InformationPanel
                name={name} setName={setName}
                author={author} setAuthor={setAuthor}
                subtitle={subtitle} setSubtitle={setSubtitle}
                coverDate={coverDate} setCoverDate={setCoverDate}
                abstract={abstract} setAbstract={setAbstract}
              />
            )}
            {activeSection === "structure" && (
              <StructurePanel
                structureHint={structureHint} setStructureHint={setStructureHint}
                prompt={prompt} setPrompt={setPrompt}
                userSourcesRaw={userSourcesRaw} setUserSourcesRaw={setUserSourcesRaw}
              />
            )}
            {activeSection === "pipeline" && (
              <PipelinePanel
                projectId={id}
                pipelineConfig={pipelineConfig}
                setPipelineConfig={setPipelineConfig}
                orderedSources={orderedSources}
                setOrderedSources={setOrderedSources}
              />
            )}
            {activeSection === "style" && (
              <StylePanel
                language={language} setLanguage={setLanguage}
                ocrLang={ocrLang} setOcrLang={setOcrLang}
                ocrLangTouched={ocrLangTouched} setOcrLangTouched={setOcrLangTouched}
                writerUseKnowledge={writerUseKnowledge} setWriterUseKnowledge={setWriterUseKnowledge}
                latexTemplate={latexTemplate} setLatexTemplate={setLatexTemplate}
                availableTemplates={availableTemplates}
              />
            )}
            {activeSection === "figures" && (
              <FiguresPanel
                projectId={id}
                orderedSources={orderedSources}
                figuresBySource={figuresBySource}
                mandatoryIds={mandatoryIds}
                toggleMandatory={toggleMandatory}
                selectFigures={selectFigures}
                totalFigures={totalFigures}
                userUploadedFigures={userUploadedFigures}
                onUploaded={() => setRefreshKey((k) => k + 1)}
              />
            )}
          </div>
        </div>
      </div>

      {error && <p className="text-sm text-red-500">{error}</p>}

      {/* Sticky bottom bar */}
      <div className="sticky bottom-0 -mx-4 border-t border-ink-200 bg-ink-50/90 px-4 py-3 backdrop-blur dark:border-ink-800 dark:bg-ink-950/90">
        <div className="flex items-center justify-end gap-3">
          <button className="btn-ghost" disabled={saving} onClick={() => save(false)}>
            {saving ? <Loader2 size={16} className="animate-spin" /> : null}
            Save
          </button>
          <button className="btn-primary" disabled={saving} onClick={() => save(true)}>
            {saving ? <Loader2 size={16} className="animate-spin" /> : null}
            Save &amp; continue
            <ArrowRight size={16} />
          </button>
        </div>
      </div>

      {/* Summary modal (unchanged) */}
      {showSummary && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-ink-950/60 p-4 backdrop-blur-sm" onClick={() => setShowSummary(false)}>
          <div className="animate-modal-up w-full max-w-lg rounded-xl border border-ink-200 bg-white shadow-2xl dark:border-ink-700 dark:bg-ink-900" onClick={(e) => e.stopPropagation()}>
            <div className="flex items-center justify-between border-b border-ink-200 px-5 py-4 dark:border-ink-700">
              <h2 className="text-lg font-semibold">Ready to generate</h2>
              <button className="rounded-md p-1 text-ink-400 hover:text-ink-700" onClick={() => setShowSummary(false)}>✕</button>
            </div>
            <div className="space-y-4 px-5 py-4">
              <div className="grid grid-cols-2 gap-3 text-sm">
                <div><span className="text-xs font-medium uppercase text-ink-400">Title</span><p className="mt-0.5 font-medium">{name || "—"}</p></div>
                <div><span className="text-xs font-medium uppercase text-ink-400">Language</span><p className="mt-0.5 capitalize">{language}</p></div>
                {author && <div><span className="text-xs font-medium uppercase text-ink-400">Author</span><p className="mt-0.5">{author}</p></div>}
                {coverDate && <div><span className="text-xs font-medium uppercase text-ink-400">Date</span><p className="mt-0.5">{coverDate}</p></div>}
              </div>
              <div className="rounded-lg border border-ink-200 bg-ink-50/50 p-3 dark:border-ink-700 dark:bg-ink-950/50">
                <span className="text-xs font-medium uppercase text-ink-400">Template — {latexTemplate}</span>
                <div className="mt-1 flex flex-wrap gap-1">
                  {Object.entries(pipelineConfig).filter(([,v]) => v !== "none").map(([k,v]) => (
                    <span key={k} className="rounded-full bg-emerald-100 px-2 py-0.5 text-[11px] text-emerald-800 dark:bg-emerald-900/30 dark:text-emerald-300">{k}:{v}</span>
                  ))}
                </div>
              </div>
              <div><span className="text-xs font-medium uppercase text-ink-400">Figures</span><p className="mt-0.5 text-sm">{mandatoryIds.size} / {totalFigures}</p></div>
              {parsedUserSources.length > 0 && (
                <div>
                  <span className="text-xs font-medium uppercase text-ink-400">Bibliography ({parsedUserSources.length})</span>
                  <ul className="mt-0.5 max-h-24 space-y-0.5 overflow-y-auto text-xs text-ink-500">
                    {parsedUserSources.map((s, i) => (<li key={i} className="truncate">{s.authors} ({s.year}) — {s.title}</li>))}
                  </ul>
                </div>
              )}
            </div>
            <div className="flex items-center justify-end gap-3 border-t border-ink-200 px-5 py-4 dark:border-ink-700">
              <button className="btn-ghost" onClick={() => setShowSummary(false)}>Cancel</button>
              <button className="btn-primary" onClick={() => { setShowSummary(false); navigate(`/generate/${id}`); }}>Confirm &amp; generate<ArrowRight size={16} /></button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
