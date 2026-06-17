import { ArrowRight, Globe, Search, Sparkles } from "lucide-react";
import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import Checkbox from "../components/Checkbox";
import Dropzone from "../components/Dropzone";
import { cn } from "../lib/utils";
import { api } from "../lib/api";
import { LANGUAGE_SUGGESTIONS } from "../lib/languages";
import { useAppStore } from "../stores/appStore";

export default function UploadPage() {
  const navigate = useNavigate();
  const { webTools, loadWebTools } = useAppStore();

  const [files, setFiles] = useState<File[]>([]);
  const [name, setName] = useState("");
  const [language, setLanguage] = useState("english");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [researchMode, setResearchMode] = useState(false);
  const [webToolId, setWebToolId] = useState<number>(0);

  useEffect(() => {
    loadWebTools();
  }, [loadWebTools]);

  const canSubmit = (files.length > 0 || researchMode) && name.trim();
  const activeWebTools = webTools.filter((t) => t.is_active);

  async function handleSubmit() {
    if (!canSubmit) return;
    setSubmitting(true);
    setError(null);
    try {
      const form = new FormData();
      form.append("name", name.trim());
      form.append("language", language);
      form.append("ocr_lang", "");
      form.append("extractor_backend", "pipeline");
      form.append("research_mode", String(researchMode));
      form.append("web_tool_id", String(webToolId));
      files.forEach((f) => form.append("files", f));
      const project = await api.createProject(form);
      navigate(`/configure/${project.id}`);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">New document</h1>
        <p className="mt-1 text-sm text-ink-500">
          Upload PDFs or generate from web research — configure structure and
          style in the next step.
        </p>
      </div>

      <div className="card space-y-4">
        <div>
          <label className="mb-1 block text-sm font-medium">
            Project title / Topic
          </label>
          <input
            className="input"
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder={
              researchMode
                ? "e.g. Quantum Computing fundamentals"
                : "e.g. Deep Learning notes"
            }
          />
          {researchMode && (
            <p className="mt-1 text-xs text-ink-400">
              This is the topic the system will research on the web.
            </p>
          )}
        </div>

        {/* ── Research mode toggle ──────────────────────────────────────── */}
        <div
          role="button"
          tabIndex={0}
          onClick={() => {
            const next = !researchMode;
            setResearchMode(next);
            if (next) setFiles([]);
          }}
          onKeyDown={(e) => {
            if (e.key === " ") e.preventDefault();
          }}
          className={cn(
            "cursor-pointer rounded-xl border-2 p-5 transition-all duration-300",
            "hover:shadow-md focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-emerald-500/40",
            researchMode
              ? "border-emerald-400 bg-emerald-50/40 shadow-sm dark:border-emerald-600 dark:bg-emerald-950/20"
              : "border-ink-200/60 bg-ink-50/50 hover:border-ink-400 dark:border-ink-800/60 dark:bg-ink-950/50 dark:hover:border-ink-600",
          )}
        >
          <div className="flex items-start gap-4">
            {/* Decorative icon */}
            <div
              className={cn(
                "flex h-12 w-12 shrink-0 items-center justify-center rounded-xl transition-all duration-300",
                researchMode
                  ? "bg-emerald-500 text-white shadow-md shadow-emerald-500/30"
                  : "bg-ink-100 text-ink-400 dark:bg-ink-800 dark:text-ink-500",
              )}
            >
              {researchMode ? (
                <Sparkles size={22} strokeWidth={1.5} />
              ) : (
                <Globe size={22} strokeWidth={1.5} />
              )}
            </div>

            <div className="min-w-0 flex-1">
              <span onClick={(e) => e.stopPropagation()}>
                <Checkbox
                  checked={researchMode}
                  onChange={(checked) => {
                    setResearchMode(checked);
                    if (checked) setFiles([]);
                  }}
                  label={
                    <span className="flex items-center gap-1.5">
                      Research mode
                      {researchMode && (
                        <span className="inline-flex items-center gap-1 rounded-full bg-emerald-100 px-2 py-0.5 text-[10px] font-medium text-emerald-700 dark:bg-emerald-900/40 dark:text-emerald-300">
                          <Sparkles size={10} />
                          Active
                        </span>
                      )}
                    </span>
                  }
                  hint="No PDFs required. The system will search the web for information on your topic and build the document from online sources."
                />
              </span>
            </div>
          </div>

          {/* Sub-section: web tool selector / warning */}
          <div
            className={cn(
              "grid transition-all duration-300",
              researchMode
                ? "mt-4 grid-rows-[1fr]"
                : "mt-0 grid-rows-[0fr]",
            )}
          >
            <div className="overflow-hidden">
              <div className="ml-16 rounded-lg border border-dashed border-emerald-300/60 bg-white/50 p-4 dark:border-emerald-700/40 dark:bg-ink-900/40">
                {activeWebTools.length > 0 ? (
                  <>
                    <label className="mb-1.5 flex items-center gap-1.5 text-xs font-medium">
                      <Search size={12} className="text-emerald-500" />
                      Web search tool
                    </label>
                    <select
                      className="input w-full text-sm"
                      value={webToolId}
                      onClick={(e) => e.stopPropagation()}
                      onChange={(e) => setWebToolId(Number(e.target.value))}
                    >
                      <option value={0}>Select a web tool…</option>
                      {activeWebTools.map((t) => (
                        <option key={t.id} value={t.id}>
                          {t.name} &mdash; {t.tool_type}
                        </option>
                      ))}
                    </select>
                    <p className="mt-1.5 text-[10px] text-ink-400">
                      Choose the search engine to use for research. Configure
                      more tools in Settings.
                    </p>
                  </>
                ) : (
                  <p className="text-xs text-amber-700 dark:text-amber-300">
                    <span className="font-bold">!</span> No web tools configured.{" "}
                    <span className="font-medium">
                      Add one in Settings below
                    </span>{" "}
                    (Wikipedia is free, no API key needed).
                  </p>
                )}
              </div>
            </div>
          </div>
        </div>

        {/* ── PDF upload (hidden in research-only mode) ──────────────────── */}
        {!researchMode && <Dropzone files={files} onChange={setFiles} />}

        <div>
          <label className="mb-1 block text-sm font-medium">Language</label>
          <input
            className="input"
            value={language}
            onChange={(e) => setLanguage(e.target.value.toLowerCase())}
            list="language-suggestions"
            placeholder="english, italian, french…"
          />
          <datalist id="language-suggestions">
            {LANGUAGE_SUGGESTIONS.map((l) => (
              <option key={l.value} value={l.value}>
                {l.label}
              </option>
            ))}
          </datalist>
        </div>

        {error && <p className="text-sm text-red-500">{error}</p>}

        <button
          className="btn-primary w-full"
          disabled={!canSubmit || submitting || (researchMode && webToolId === 0)}
          onClick={handleSubmit}
        >
          {submitting
            ? "Creating…"
            : researchMode
              ? "Start research"
              : files.length > 0
                ? "Continue"
                : "Upload PDFs or enable research mode"}
          <ArrowRight size={16} />
        </button>
      </div>
    </div>
  );
}
