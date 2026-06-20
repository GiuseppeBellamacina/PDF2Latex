import { BookOpen, Bot, Globe, Key, Search, Sparkles, X } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router-dom";
import Checkbox from "../Checkbox";
import { cn, webToolRequiresKey } from "../../lib/utils";
import { api } from "../../lib/api";
import { useAppStore } from "../../stores/appStore";
import type { Provider } from "../../lib/api";

const WEB_TOOL_ICON: Record<string, React.ReactNode> = {
  tavily: <Search size={16} />,
  perplexity: <Sparkles size={16} />,
  wikipedia: <Globe size={16} />,
  web_agent: <Bot size={16} />,
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

interface Props {
  name: string;
  setName: (v: string) => void;
  author: string;
  setAuthor: (v: string) => void;
  subtitle: string;
  setSubtitle: (v: string) => void;
  coverDate: string;
  setCoverDate: (v: string) => void;
  abstract: string;
  setAbstract: (v: string) => void;
  researchMode: boolean;
  setResearchMode: (v: boolean) => void;
  webToolIds: number[];
  setWebToolIds: (v: number[]) => void;
  researchMaxQueriesStr: string;
  setResearchMaxQueriesStr: (v: string) => void;
  webAgentMaxIterations: number;
  setWebAgentMaxIterations: (v: number) => void;
  providers: Provider[];
  webAgentProviderId: number | null;
  setWebAgentProviderId: (v: number | null) => void;
  webAgentModel: string;
  setWebAgentModel: (v: string) => void;
}

export default function InformationPanel({
  name, setName,
  author, setAuthor,
  subtitle, setSubtitle,
  coverDate, setCoverDate,
  abstract, setAbstract,
  researchMode, setResearchMode,
  webToolIds, setWebToolIds,
  researchMaxQueriesStr, setResearchMaxQueriesStr,
  webAgentMaxIterations, setWebAgentMaxIterations,
  providers,
  webAgentProviderId, setWebAgentProviderId,
  webAgentModel, setWebAgentModel,
}: Props) {
  const toggleTool = (id: number) => {
    setWebToolIds(
      webToolIds.includes(id)
        ? webToolIds.filter((x) => x !== id)
        : [...webToolIds, id]
    );
  };

  const { webTools, loadWebTools } = useAppStore();
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

  return (
    <div className="space-y-5">
      <div className="flex items-center gap-2.5">
        <span className="rounded-lg bg-ink-100 p-1.5 text-ink-500 dark:bg-ink-800 dark:text-ink-400">
          <BookOpen size={16} />
        </span>
        <h2 className="text-sm font-semibold uppercase tracking-wide text-ink-400">Cover & Metadata</h2>
      </div>

      <div>
        <label className="mb-1 block text-sm font-medium">Title</label>
        <input
          className="input"
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="Document title"
        />
      </div>

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        <div>
          <label className="mb-1 block text-sm font-medium">
            Subtitle <span className="text-ink-400">— optional</span>
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
            Author <span className="text-ink-400">— optional</span>
          </label>
          <input
            className="input"
            value={author}
            onChange={(e) => setAuthor(e.target.value)}
            placeholder="First and last name"
          />
        </div>
      </div>

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        <div>
          <label className="mb-1 block text-sm font-medium">
            Date <span className="text-ink-400">— optional</span>
          </label>
          <input
            className="input"
            value={coverDate}
            onChange={(e) => setCoverDate(e.target.value)}
            placeholder="e.g. January 2025"
          />
        </div>
        <div />
      </div>

      <div>
        <label className="mb-1 block text-sm font-medium">
          Abstract <span className="text-ink-400">— optional</span>
        </label>
        <textarea
          className="input min-h-24 resize-y"
          value={abstract}
          onChange={(e) => setAbstract(e.target.value)}
          placeholder="Short summary of the document, shown on the first page…"
        />
      </div>          <div className="rounded-lg border border-ink-200/60 bg-ink-50/40 p-4 dark:border-ink-700/60 dark:bg-ink-900/30">
        <div className="mb-3 flex items-center gap-2.5">
          <Globe size={16} className="text-ink-400" />
          <h3 className="text-sm font-medium">Web Research</h3>
          <span className="text-xs text-ink-400">— optional</span>
        </div>

        <Checkbox
          checked={researchMode}
          onChange={setResearchMode}
          label="Enable web research"
          hint="Generate a document purely from web research — no files needed."
        />

        {researchMode && (
          <div className="mt-4 space-y-4 border-t border-ink-200/60 pt-4 dark:border-ink-700/60">
            <div>
              <label className="mb-1 block text-xs font-medium text-ink-500">
                Search tools
              </label>
              <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
                {webTools.length === 0 && (
                  <div className="col-span-full space-y-2.5">
                    {apiKeyTarget ? (
                      <>
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
                          />
                          <button
                            type="button"
                            disabled={!apiKeyInput.trim() || quickAdding !== null}
                            onClick={() => submitApiKeyTool()}
                            className="btn-primary px-3 py-2 text-xs"
                          >
                            {quickAdding ? "Adding…" : "Add"}
                          </button>
                          <button
                            type="button"
                            onClick={() => {
                              setApiKeyTarget(null);
                              setApiKeyInput("");
                            }}
                            className="rounded-lg border border-ink-200 px-2 py-2 text-ink-400 hover:text-ink-600 dark:border-ink-700 dark:hover:text-ink-300"
                            aria-label="Cancel"
                          >
                            <X size={14} />
                          </button>
                        </div>
                      </>
                    ) : (
                      <>
                        <p className="text-xs font-medium text-ink-500">Quick add</p>
                        <div className="flex gap-2">
                          <button
                            type="button"
                            onClick={() => {
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
                            onClick={() => {
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
                      </>
                    )}
                  </div>
                )}
                {webTools.map((t) => {
                  const selected = webToolIds.includes(t.id);
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
                      onClick={() => toggleTool(t.id)}
                      className={cn(
                        "flex items-start gap-3 rounded-xl border-2 p-3 text-left transition-all duration-200",
                        "hover:shadow-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-violet-500/40",
                        selected
                          ? "border-violet-400 bg-violet-50/60 shadow-sm dark:border-violet-600 dark:bg-violet-950/25"
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
                              selected ? "text-violet-800 dark:text-violet-200" : "text-ink-700 dark:text-ink-200",
                            )}
                          >
                            {t.name}
                          </span>
                          {selected && (
                            <span className="shrink-0 rounded-full bg-violet-500 p-0.5 text-white">
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
                          {t.tool_type === "web_agent" && " · Agentic search"}
                        </p>
                      </div>
                    </button>
                  );
                })}
              </div>

            </div>

            <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
              <div>
                <div className="mb-1 flex items-center gap-2">
                  <Bot size={13} className="text-ink-400" />
                  <label className="text-xs font-medium text-ink-500">
                    Web Agent iterations
                  </label>
                </div>
                <input
                  type="number"
                  className="input w-full"
                  min={1}
                  max={10}
                  value={webAgentMaxIterations}
                  onChange={(e) =>
                    setWebAgentMaxIterations(Math.max(1, Math.min(10, Number(e.target.value) || 3)))
                  }
                />
                <p className="mt-0.5 text-[10px] text-ink-400">
                  Planner→fetch→evaluate loops (1-10)
                </p>
              </div>
              <div>
                <div className="mb-1 flex items-center gap-2">
                  <Bot size={13} className="text-ink-400" />
                  <label className="text-xs font-medium text-ink-500">
                    Web Agent LLM{" "}
                    <span className="font-normal text-ink-400">— optional</span>
                  </label>
                </div>
                <select
                  className="input w-full"
                  value={webAgentProviderId ?? ""}
                  onChange={(e) => {
                    const v = e.target.value;
                    setWebAgentProviderId(v ? Number(v) : null);
                  }}
                >
                  <option value="">Use project default</option>
                  {providers.filter((p) => p.is_active).map((p) => (
                    <option key={p.id} value={p.id}>
                      {p.name} ({p.provider_type})
                    </option>
                  ))}
                </select>
                <p className="mt-0.5 text-[10px] text-ink-400">
                  Dedicated LLM for web research; falls back to project default
                </p>
              </div>
              <div>
                <div className="mb-1 flex items-center gap-2">
                  <Bot size={13} className="text-ink-400" />
                  <label className="text-xs font-medium text-ink-500">
                    Model override{" "}
                    <span className="font-normal text-ink-400">— optional</span>
                  </label>
                </div>
                <input
                  className="input w-full"
                  value={webAgentModel}
                  onChange={(e) => setWebAgentModel(e.target.value)}
                  placeholder="e.g. gpt-4o-mini"
                />
                <p className="mt-0.5 text-[10px] text-ink-400">
                  Override the provider's default model
                </p>
              </div>
            </div>

            <div>
              <div className="mb-1 flex items-center gap-2">
                <Search size={13} className="text-ink-400" />
                <label className="text-xs font-medium text-ink-500">
                  Max search queries
                </label>
              </div>
              <p className="mb-2 text-xs text-ink-400">
                Maximum number of web searches per run. Leave empty for unlimited.
              </p>
              <input
                type="text"
                inputMode="numeric"
                className="input w-32"
                placeholder="unlimited"
                value={researchMaxQueriesStr}
                onChange={(e) => {
                  const v = e.target.value.replace(/[^0-9]/g, "");
                  setResearchMaxQueriesStr(v);
                }}
              />
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
