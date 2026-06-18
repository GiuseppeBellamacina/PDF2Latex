import { BookOpen, Bot, Globe, Search, Sparkles } from "lucide-react";
import { useEffect, useRef } from "react";
import { Link } from "react-router-dom";
import Checkbox from "../Checkbox";
import { cn } from "../../lib/utils";
import type { WebTool } from "../../lib/api";

const WEB_TOOL_ICON: Record<string, React.ReactNode> = {
  tavily: <Search size={16} />,
  perplexity: <Sparkles size={16} />,
  wikipedia: <Globe size={16} />,
  web_agent: <Bot size={16} />,
};
const WEB_TOOL_COLOR: Record<string, string> = {
  tavily: "bg-violet-100 text-violet-600 dark:bg-violet-900/40 dark:text-violet-300",
  perplexity: "bg-amber-100 text-amber-600 dark:bg-amber-900/40 dark:text-amber-300",
  wikipedia: "bg-sky-100 text-sky-600 dark:bg-sky-900/40 dark:text-sky-300",
  web_agent: "bg-emerald-100 text-emerald-600 dark:bg-emerald-900/40 dark:text-emerald-300",
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
  webTools: WebTool[];
  researchMaxQueriesStr: string;
  setResearchMaxQueriesStr: (v: string) => void;
}

export default function InformationPanel({
  name, setName,
  author, setAuthor,
  subtitle, setSubtitle,
  coverDate, setCoverDate,
  abstract, setAbstract,
  researchMode, setResearchMode,
  webToolIds, setWebToolIds,
  webTools,
  researchMaxQueriesStr, setResearchMaxQueriesStr,
}: Props) {
  const toggleTool = (id: number) => {
    setWebToolIds(
      webToolIds.includes(id)
        ? webToolIds.filter((x) => x !== id)
        : [...webToolIds, id]
    );
  };

  // Auto-select built-in (no-API-key) tools when research mode is enabled.
  const prevResearchMode = useRef(researchMode);
  useEffect(() => {
    if (researchMode && !prevResearchMode.current) {
      const builtinIds = webTools
        .filter((t) => !t.has_api_key)
        .map((t) => t.id);
      if (builtinIds.length > 0) {
        const next = new Set(webToolIds);
        for (const id of builtinIds) next.add(id);
        setWebToolIds([...next]);
      }
    }
    prevResearchMode.current = researchMode;
  }, [researchMode, webTools]);  // eslint-disable-line react-hooks/exhaustive-deps
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
      </div>

      <div className="rounded-lg border border-ink-200/60 bg-ink-50/40 p-4 dark:border-ink-700/60 dark:bg-ink-900/30">
        <div className="mb-3 flex items-center gap-2.5">
          <Globe size={16} className="text-ink-400" />
          <h3 className="text-sm font-medium">Web Research</h3>
          <span className="text-xs text-ink-400">— optional</span>
        </div>

        <Checkbox
          checked={researchMode}
          onChange={setResearchMode}
          label="Enable web research"
          hint="Let the LLM search the web for missing facts and references during generation."
        />

        {researchMode && (
          <div className="mt-4 space-y-4 border-t border-ink-200/60 pt-4 dark:border-ink-700/60">
            <div>
              <label className="mb-1 block text-xs font-medium text-ink-500">
                Search tools
              </label>
              <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
                {webTools.length === 0 && (
                  <p className="col-span-full text-xs text-ink-400">
                    No search tools configured.{" "}
                    <Link to="/settings" className="underline hover:text-ink-600">
                      Add one in Settings
                    </Link>
                    .
                  </p>
                )}
                {webTools.map((t) => {
                  const selected = webToolIds.includes(t.id);
                  const toolIcon = getWebToolIcon(t.tool_type);
                  const toolColor = getWebToolColor(t.tool_type);
                  return (
                    <button
                      key={t.id}
                      type="button"
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
                          {t.has_api_key ? "API key configured" : "No API key needed"}
                          {t.tool_type === "web_agent" && " · Agentic search"}
                        </p>
                      </div>
                    </button>
                  );
                })}
              </div>
              <p className="mt-1 text-[10px] text-ink-400">
                Select one or more search engines. Each query is searched
                across all selected tools and results are merged for broader coverage.
              </p>
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
