import { ArrowRight, BookOpen, Globe, Key, Link as LinkIcon, Plus, Search, Sparkles, X } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import Checkbox from "../components/Checkbox";
import Dropzone from "../components/Dropzone";
import { cn, webToolRequiresKey } from "../lib/utils";
import { api } from "../lib/api";
import { LANGUAGE_SUGGESTIONS } from "../lib/languages";
import { useAppStore } from "../stores/appStore";

const WEB_TOOL_ICON: Record<string, React.ReactNode> = {
  tavily: <Search size={16} />,
  perplexity: <Sparkles size={16} />,
  wikipedia: <Globe size={16} />,
  web_agent: <Globe size={16} />,
  arxiv: <BookOpen size={16} />,
};
const WEB_TOOL_COLOR: Record<string, string> = {
  tavily: "bg-violet-100 text-violet-600 dark:bg-violet-900/40 dark:text-violet-300",
  perplexity: "bg-amber-100 text-amber-600 dark:bg-amber-900/40 dark:text-amber-300",
  wikipedia: "bg-sky-100 text-sky-600 dark:bg-sky-900/40 dark:text-sky-300",
  web_agent: "bg-emerald-100 text-emerald-600 dark:bg-emerald-900/40 dark:text-emerald-300",
  arxiv: "bg-red-100 text-red-600 dark:bg-red-900/40 dark:text-red-300",
};

function getWebToolIcon(type: string): React.ReactNode {
  return WEB_TOOL_ICON[type] ?? <Globe size={16} />;
}
function getWebToolColor(type: string): string {
  return WEB_TOOL_COLOR[type] ?? "bg-ink-100 text-ink-400 dark:bg-ink-800 dark:text-ink-500";
}

export default function UploadPage() {
  const navigate = useNavigate();
  const { webTools, loadWebTools } = useAppStore();

  const [files, setFiles] = useState<File[]>([]);
  const [urlList, setUrlList] = useState<string[]>([]);
  const [urlInput, setUrlInput] = useState("");
  const [name, setName] = useState("");
  const [language, setLanguage] = useState("english");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [researchMode, setResearchMode] = useState(false);
  const [webToolIds, setWebToolIds] = useState<Set<number>>(new Set());
  const [maxQueries, setMaxQueries] = useState<number>(0);
  const [quickAdding, setQuickAdding] = useState<string | null>(null);
  const [apiKeyInput, setApiKeyInput] = useState("");
  const [apiKeyTarget, setApiKeyTarget] = useState<string | null>(null);

  async function submitApiKeyTool() {
    const target = apiKeyTarget;
    if (!target || !apiKeyInput.trim()) return;
    const key = apiKeyInput.trim();
    setQuickAdding(target);
    setApiKeyTarget(null);
    setApiKeyInput("");
    try {
      await api.createWebTool({
        name: target === "tavily" ? "Tavily" : "Perplexity",
        tool_type: target,
        api_key: key,
        is_active: true,
      });
      await loadWebTools();
    } catch { /* ignore duplicate */ }
    setQuickAdding(null);
  }

  // Random placeholder picked once on mount.
  const titlePlaceholder = useMemo(() => {
    const pool = [
      "e.g. Deep Learning notes",
      "e.g. Quantum Computing fundamentals",
      "e.g. Machine Learning overview",
      "e.g. Neural Networks explained",
      "e.g. Computer Vision techniques",
      "e.g. Natural Language Processing guide",
      "e.g. Reinforcement Learning survey",
    ];
    return pool[Math.floor(Math.random() * pool.length)];
  }, []);

  useEffect(() => {
    loadWebTools();
  }, [loadWebTools]);

  const totalSources = files.length + urlList.length;
  const activeWebTools = webTools.filter((t) => t.is_active);
  const canSubmit = (totalSources > 0 || researchMode) && name.trim();

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
      form.append("web_tool_ids", [...webToolIds].join(","));
      form.append("research_max_queries", String(maxQueries));
      form.append("urls", urlList.join("\n"));
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
            placeholder={titlePlaceholder}
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
          onClick={() => setResearchMode(!researchMode)}
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
              className={
                "flex h-12 w-12 shrink-0 items-center justify-center rounded-xl" +
                " bg-ink-100 text-ink-400 dark:bg-ink-800 dark:text-ink-500"
              }
            >
              <Globe size={22} strokeWidth={1.5} />
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
                          <Globe size={10} />
                          Active
                        </span>
                      )}
                    </span>
                  }
                  hint="Generate a document purely from web research — no files needed."
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
                    <label className="mb-2 flex items-center gap-1.5 text-xs font-medium">
                      <Search size={12} className="text-emerald-500" />
                      Search tools
                    </label>
                    <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
                      {activeWebTools.map((t) => {
                        const selected = webToolIds.has(t.id);
                        const toolIcon = getWebToolIcon(t.tool_type);
                        const toolColor = getWebToolColor(t.tool_type);
                        const missingRequiredKey =
                          webToolRequiresKey(t.tool_type) && !t.has_api_key;
                        return (
                          <button
                            key={t.id}
                            type="button"
                            disabled={missingRequiredKey}
                            title={missingRequiredKey ? "API key required — configure in Settings" : undefined}
                            onClick={(e) => {
                              e.stopPropagation();
                              const next = new Set(webToolIds);
                              if (selected) next.delete(t.id);
                              else next.add(t.id);
                              setWebToolIds(next);
                            }}
                            className={cn(
                              "flex items-start gap-3 rounded-xl border-2 p-3 text-left transition-all duration-200",
                              "hover:shadow-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-emerald-500/40",
                              selected
                                ? "border-emerald-400 bg-emerald-50/60 shadow-sm dark:border-emerald-600 dark:bg-emerald-950/25"
                                : "border-ink-200/60 bg-white/60 hover:border-ink-300 dark:border-ink-800/60 dark:bg-ink-900/40 dark:hover:border-ink-600",
                            )}
                          >
                            <span
                              className={cn(
                                "flex h-8 w-8 shrink-0 items-center justify-center rounded-lg transition-colors",
                                selected
                                  ? toolColor
                                  : "bg-ink-100 text-ink-400 dark:bg-ink-800 dark:text-ink-500",
                              )}
                            >
                              {toolIcon}
                            </span>
                            <div className="min-w-0 flex-1">
                              <div className="flex items-center gap-1.5">
                                <span
                                  className={cn(
                                    "truncate text-sm font-medium transition-colors",
                                    selected ? "text-emerald-800 dark:text-emerald-200" : "text-ink-700 dark:text-ink-200",
                                  )}
                                >
                                  {t.name}
                                </span>
                                {selected && (
                                  <span className="shrink-0 rounded-full bg-emerald-500 p-0.5 text-white">
                                    <svg width="10" height="10" viewBox="0 0 10 10" fill="none">
                                      <path d="M2 5L4 7L8 3" stroke="white" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
                                    </svg>
                                  </span>
                                )}
                              </div>
                              <p className="mt-0.5 text-[11px] text-ink-400">
                                {t.has_api_key
                                  ? "API key configured"
                                  : webToolRequiresKey(t.tool_type)
                                    ? "API key required"
                                    : "No API key needed"}
                              </p>
                            </div>
                          </button>
                        );
                      })}
                    </div>
                        {/* Query limit */}
                        <div className="mt-3">
                          <label className="mb-1 flex items-center gap-1.5 text-xs font-medium">
                            <Search size={12} className="text-emerald-500" />
                            Max queries <span className="font-normal text-ink-400">(0 = unlimited)</span>
                          </label>
                          <input
                            type="number"
                            className="input w-full text-sm"
                            min={0}
                            value={maxQueries}
                            onClick={(e) => e.stopPropagation()}
                            onChange={(e) => setMaxQueries(Math.max(0, Number(e.target.value)))}
                            placeholder="0 = unlimited"
                          />
                        </div>
                  </>
                ) : apiKeyTarget ? (
                  <div className="space-y-2.5">
                    <p className="text-xs font-medium text-ink-500">
                      API key for {apiKeyTarget === "tavily" ? "Tavily" : "Perplexity"}
                    </p>
                    <div className="flex gap-2">
                      <input
                        autoFocus
                        type="password"
                        className="input flex-1 text-sm"
                        value={apiKeyInput}
                        onChange={(e) => setApiKeyInput(e.target.value)}
                        onKeyDown={(e) => {
                          if (e.key === "Enter" && apiKeyInput.trim()) {
                            e.preventDefault();
                            submitApiKeyTool();
                          }
                        }}
                        placeholder={`Paste your ${apiKeyTarget === "tavily" ? "Tavily" : "Perplexity"} API key…`}
                        onClick={(e) => e.stopPropagation()}
                      />
                      <button
                        type="button"
                        disabled={!apiKeyInput.trim() || quickAdding !== null}
                        onClick={(e) => {
                          e.stopPropagation();
                          submitApiKeyTool();
                        }}
                        className="btn-primary px-3 py-2 text-xs"
                      >
                        {quickAdding ? "Adding…" : "Add"}
                      </button>
                      <button
                        type="button"
                        onClick={(e) => {
                          e.stopPropagation();
                          setApiKeyTarget(null);
                          setApiKeyInput("");
                        }}
                        className="rounded-lg border border-ink-200 px-2 py-2 text-ink-400 hover:text-ink-600 dark:border-ink-700 dark:hover:text-ink-300"
                        aria-label="Cancel"
                      >
                        <X size={14} />
                      </button>
                    </div>
                  </div>
                ) : (
                  <div className="space-y-2.5">
                    <p className="text-xs font-medium text-ink-500">Quick add</p>
                    <div className="flex gap-2">
                      <button
                        type="button"
                        onClick={(e) => {
                          e.stopPropagation();
                          setApiKeyTarget("tavily");
                          setApiKeyInput("");
                        }}
                        className="flex items-center gap-2 rounded-lg border border-violet-300 px-3 py-2 text-xs font-medium text-violet-700 hover:bg-violet-50 transition-colors dark:border-violet-700 dark:text-violet-300 dark:hover:bg-violet-950/30"
                      >
                        <Search size={14} />
                        Tavily
                        <span className="inline-flex items-center gap-0.5 rounded-full bg-amber-100 px-1.5 py-0.5 text-[9px] font-semibold text-amber-700 dark:bg-amber-900/40 dark:text-amber-300" title="API key required — configure in Settings">
                          <Key size={8} />
                          KEY
                        </span>
                      </button>
                      <button
                        type="button"
                        onClick={(e) => {
                          e.stopPropagation();
                          setApiKeyTarget("perplexity");
                          setApiKeyInput("");
                        }}
                        className="flex items-center gap-2 rounded-lg border border-amber-300 px-3 py-2 text-xs font-medium text-amber-700 hover:bg-amber-50 transition-colors dark:border-amber-700 dark:text-amber-300 dark:hover:bg-amber-950/30"
                      >
                        <Sparkles size={14} />
                        Perplexity
                        <span className="inline-flex items-center gap-0.5 rounded-full bg-amber-100 px-1.5 py-0.5 text-[9px] font-semibold text-amber-700 dark:bg-amber-900/40 dark:text-amber-300" title="API key required — configure in Settings">
                          <Key size={8} />
                          KEY
                        </span>
                      </button>
                    </div>
                    <p className="text-[10px] text-ink-400">
                      <Link to="/settings" className="underline decoration-dotted hover:text-ink-600">
                        Or add API keys in Settings
                      </Link>
                    </p>
                  </div>
                )}
              </div>
            </div>
          </div>
        </div>

        {/* ── URL input ──────────────────────────────────────────────── */}
        <div className="space-y-2">
          <label className="block text-sm font-medium">
            <LinkIcon size={14} className="mr-1.5 inline text-ink-400" />
            Web URLs
          </label>
          <div className="flex gap-2">
            <input
              className="input flex-1"
              value={urlInput}
              onChange={(e) => setUrlInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && urlInput.trim()) {
                  e.preventDefault();
                  setUrlList([...urlList, urlInput.trim()]);
                  setUrlInput("");
                }
              }}
              placeholder="https://example.com/article"
            />
            <button
              className="btn-ghost px-3"
              disabled={!urlInput.trim()}
              onClick={() => {
                if (urlInput.trim()) {
                  setUrlList([...urlList, urlInput.trim()]);
                  setUrlInput("");
                }
              }}
            >
              <Plus size={16} /> Add
            </button>
          </div>
          {urlList.length > 0 && (
            <ul className="space-y-1">
              {urlList.map((url, i) => (
                <li key={i} className="flex items-center justify-between rounded-lg border border-ink-200 px-3 py-1.5 text-sm dark:border-ink-800">
                  <span className="truncate text-ink-500">{url}</span>
                  <button
                    onClick={() => setUrlList(urlList.filter((_, idx) => idx !== i))}
                    className="shrink-0 text-ink-400 hover:text-ink-700"
                    aria-label="Remove URL"
                  >
                    <X size={14} />
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>

        {/* ── File upload ─────────────────────────────────────────────── */}
        <Dropzone files={files} onChange={setFiles} />

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
          disabled={!canSubmit || submitting || (researchMode && webToolIds.size === 0)}
          onClick={handleSubmit}
        >
          {submitting
            ? "Creating…"
            : totalSources > 0
              ? researchMode
                ? `Continue (${totalSources} source${totalSources !== 1 ? "s" : ""} + research)`
                : `Continue (${totalSources} source${totalSources !== 1 ? "s" : ""})`
              : researchMode
                ? "Start research"
                : "Add sources or enable research mode"}
          <ArrowRight size={16} />
        </button>
      </div>
    </div>
  );
}
