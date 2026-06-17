import { ListTree, Quote } from "lucide-react";
import { useMemo } from "react";
import { parseUserSources } from "../../lib/utils";

interface Props {
  structureHint: string;
  setStructureHint: (v: string) => void;
  prompt: string;
  setPrompt: (v: string) => void;
  userSourcesRaw: string;
  setUserSourcesRaw: (v: string) => void;
}

export default function StructurePanel({
  structureHint, setStructureHint,
  prompt, setPrompt,
  userSourcesRaw, setUserSourcesRaw,
}: Props) {
  const parsed = useMemo(() => parseUserSources(userSourcesRaw), [userSourcesRaw]);

  return (
    <div className="space-y-5">
      <div className="flex items-center gap-2.5">
        <span className="rounded-lg bg-ink-100 p-1.5 text-ink-500 dark:bg-ink-800 dark:text-ink-400">
          <ListTree size={16} />
        </span>
        <h2 className="text-sm font-semibold uppercase tracking-wide text-ink-400">Structure & Outline</h2>
      </div>

      <div>
        <label className="mb-1 block text-sm font-medium">
          Desired structure <span className="text-ink-400">— optional</span>
        </label>
        <textarea
          className="input min-h-20 resize-y font-mono text-xs"
          value={structureHint}
          onChange={(e) => setStructureHint(e.target.value)}
          placeholder="List chapters in order, e.g.\n1. Introduction\n2. Foundations\n3. Architectures\n4. Conclusions"
          spellCheck={false}
        />
        <p className="mt-1 text-xs text-ink-500">
          Leave empty to let the AI plan the structure automatically.
        </p>
      </div>

      <div>
        <label className="mb-1 block text-sm font-medium">
          Custom instructions <span className="text-ink-400">— optional</span>
        </label>
        <textarea
          className="input min-h-20 resize-y"
          value={prompt}
          onChange={(e) => setPrompt(e.target.value)}
          placeholder="e.g. Accessible tone, include key formulas, focus on applications…"
        />
      </div>

      <div className="rounded-lg border border-ink-200/60 bg-ink-50/40 p-4 dark:border-ink-700/60 dark:bg-ink-900/30">
        <div className="mb-3 flex items-center gap-2.5">
          <Quote size={16} className="text-ink-400" />
          <h3 className="text-sm font-medium">Bibliography sources</h3>
          <span className="text-xs text-ink-400">— optional</span>
        </div>
        <p className="mb-2 text-xs text-ink-500">
          References the system should cite. One per line: <code className="rounded bg-ink-200 px-1 dark:bg-ink-700">Author | Title | Year | Venue</code>.
          Lines starting with <code className="rounded bg-ink-200 px-1 dark:bg-ink-700">#</code> are ignored.
        </p>
        <textarea
          className="input min-h-24 resize-y font-mono text-xs"
          value={userSourcesRaw}
          onChange={(e) => setUserSourcesRaw(e.target.value)}
          placeholder={"# Format: Author(s) | Title | Year | Venue\nHe et al. | Deep Residual Learning | 2016 | CVPR\nVaswani et al. | Attention Is All You Need | 2017 | NeurIPS"}
          spellCheck={false}
        />
        {parsed.length > 0 && (
          <p className="mt-2 text-xs text-emerald-600 dark:text-emerald-400">
            {parsed.length} reference{parsed.length !== 1 ? "s" : ""} parsed — will be cited where relevant.
          </p>
        )}
      </div>
    </div>
  );
}
