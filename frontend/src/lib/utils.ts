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

export interface ParsedSource {
  authors: string;
  title: string;
  year: string;
  venue: string;
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
