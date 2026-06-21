import React from "react";
import { Globe, Search, Sparkles } from "lucide-react";

export function cn(...classes: (string | false | null | undefined)[]): string {
  return classes.filter(Boolean).join(" ");
}

/** Web tool types that require an API key to function. */
const WEB_TOOLS_REQUIRING_KEY = new Set(["tavily", "perplexity"]);

/** True when a web tool type needs an API key (Tavily, Perplexity). */
export function webToolRequiresKey(toolType: string): boolean {
  return WEB_TOOLS_REQUIRING_KEY.has(toolType);
}

export function formatDate(iso: string): string {
  try {
    return new Date(iso).toLocaleString("en-US", {
      dateStyle: "medium",
      timeStyle: "short",
    });
  } catch {
    return iso;
  }
}

/** Research source badge colours: arxiv → red, wikipedia → sky, tavily → violet, perplexity → amber. */
const RESEARCH_SOURCE_COLORS: Record<string, string> = {
  arxiv: "bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-300",
  wikipedia: "bg-sky-100 text-sky-700 dark:bg-sky-900/30 dark:text-sky-300",
  tavily: "bg-violet-100 text-violet-700 dark:bg-violet-900/30 dark:text-violet-300",
  perplexity: "bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-300",
};

/** Research source icons: arxiv → A, wikipedia → globe, tavily → search, perplexity → sparkles. */
const RESEARCH_SOURCE_ICONS: Record<string, React.ReactNode> = {
  arxiv: React.createElement("span", { className: "font-bold text-[9px]" }, "A"),
  wikipedia: React.createElement(Globe, { size: 11 }),
  tavily: React.createElement(Search, { size: 11 }),
  perplexity: React.createElement(Sparkles, { size: 11 }),
};

const DEFAULT_SOURCE_COLOR = "bg-ink-100 text-ink-600 dark:bg-ink-800 dark:text-ink-300";
const DEFAULT_SOURCE_ICON = React.createElement(Globe, { size: 11 });

/** Return both the color classes and icon node for a research source in a single key lookup. */
export function getResearchSourceStyle(source: string): { color: string; icon: React.ReactNode } {
  const key = Object.keys(RESEARCH_SOURCE_COLORS).find((k) =>
    source.toLowerCase().includes(k),
  );
  if (key) {
    return { color: RESEARCH_SOURCE_COLORS[key], icon: RESEARCH_SOURCE_ICONS[key] };
  }
  return { color: DEFAULT_SOURCE_COLOR, icon: DEFAULT_SOURCE_ICON };
}

export interface ParsedSource {
  authors: string;
  title: string;
  year: string;
  venue: string;
}

/** Return color classes for a document filename icon in the analyze list.
 *  PDF → red, Markdown/Text → sky, URL → emerald, default → ink. */
export function getDocumentSourceColor(name: string): string {
  const lower = name.toLowerCase();
  if (lower.endsWith(".pdf")) return "text-red-500 dark:text-red-400";
  if (lower.endsWith(".md") || lower.endsWith(".txt")) return "text-sky-500 dark:text-sky-400";
  if (lower.includes("://") || lower.startsWith("http")) return "text-emerald-500 dark:text-emerald-400";
  return "text-ink-400";
}

/** Parse user-provided bibliography sources in "Author | Title | Year | Venue" format. */
export function parseUserSources(raw: string): ParsedSource[] {
  const sources: ParsedSource[] = [];
  for (const line of raw.trim().split("\n")) {
    const trimmed = line.trim();
    if (!trimmed || trimmed.startsWith("#")) continue;
    const parts = trimmed.split("|").map((p) => p.trim());
    if (parts.length < 3) continue;
    const [authors, title, year, venue = ""] = parts;
    if (!authors || !title || !year) continue;
    sources.push({ authors, title, year, venue });
  }
  return sources;
}
