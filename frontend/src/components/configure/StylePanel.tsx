import { AlertTriangle, BookMarked, BookOpen, Globe, GraduationCap, Newspaper, Palette } from "lucide-react";
import Checkbox from "../Checkbox";
import type { LatexTemplate } from "../../lib/api";
import { LANGUAGE_SUGGESTIONS } from "../../lib/languages";

const OCR_LANG_RE = /^$|^[a-z]{3}(\+[a-z]{3})*$/;
const OCR_LANG_EXAMPLES = [
  { value: "ita+eng", label: "Italian + English" },
  { value: "eng", label: "English" },
  { value: "ita", label: "Italian" },
  { value: "fra", label: "French" },
  { value: "deu", label: "German" },
  { value: "spa", label: "Spanish" },
  { value: "por", label: "Portuguese" },
];

interface Props {
  language: string;
  setLanguage: (v: string) => void;
  ocrLang: string;
  setOcrLang: (v: string) => void;
  ocrLangTouched: boolean;
  setOcrLangTouched: (v: boolean) => void;
  writerUseKnowledge: boolean;
  setWriterUseKnowledge: (v: boolean) => void;
  latexTemplate: string;
  setLatexTemplate: (v: string) => void;
  availableTemplates: LatexTemplate[];
}

const TEMPLATE_ICONS: Record<string, typeof BookOpen> = {
  default: BookOpen,
  paper: Newspaper,
  "thesis-oneside": GraduationCap,
  "thesis-twoside": BookMarked,
};

export default function StylePanel({
  language, setLanguage,
  ocrLang, setOcrLang,
  ocrLangTouched, setOcrLangTouched,
  writerUseKnowledge, setWriterUseKnowledge,
  latexTemplate, setLatexTemplate,
  availableTemplates,
}: Props) {
  const ocrValid = OCR_LANG_RE.test(ocrLang);

  return (
    <div className="space-y-5">
      {/* Language */}
      <div>
        <div className="mb-4 flex items-center gap-2.5">
          <span className="rounded-lg bg-ink-100 p-1.5 text-ink-500 dark:bg-ink-800 dark:text-ink-400">
            <Globe size={16} />
          </span>
          <h2 className="text-sm font-semibold uppercase tracking-wide text-ink-400">Language & Style</h2>
        </div>

        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <div>
            <label className="mb-1 block text-sm font-medium">Document language</label>
            <input
              className="input"
              value={language}
              onChange={(e) => setLanguage(e.target.value.toLowerCase())}
              list="lang-cfg"
              placeholder="english, italian, french…"
            />
            <datalist id="lang-cfg">
              {LANGUAGE_SUGGESTIONS.map((l) => (
                <option key={l.value} value={l.value}>{l.label}</option>
              ))}
            </datalist>
          </div>
          <div>
            <label className="mb-1 block text-sm font-medium">
              OCR language <span className="text-ink-400">— optional</span>
            </label>
            <input
              className={`input ${ocrLangTouched && !ocrValid ? "border-red-400 dark:border-red-700" : ""}`}
              value={ocrLang}
              onChange={(e) => { setOcrLang(e.target.value.toLowerCase()); setOcrLangTouched(true); }}
              list="ocr-cfg"
              placeholder="ita+eng (default)"
            />
            <datalist id="ocr-cfg">
              {OCR_LANG_EXAMPLES.map((l) => (
                <option key={l.value} value={l.value}>{l.label}</option>
              ))}
            </datalist>
            {ocrLangTouched && !ocrValid && (
              <p className="mt-1 flex items-center gap-1 text-xs text-red-500">
                <AlertTriangle size={11} /> Use 3-letter codes, combine with + (e.g. ita+eng)
              </p>
            )}
          </div>
        </div>
      </div>

      {/* Writer knowledge */}
      <div className="rounded-lg border border-ink-200/60 p-4 dark:border-ink-700/60">
        <Checkbox
          checked={writerUseKnowledge}
          onChange={setWriterUseKnowledge}
          label="Allow writer to supplement with own knowledge"
          hint="Let the AI supplement source text with its own knowledge when needed."
        />
      </div>

      {/* Template */}
      <div className="border-t border-ink-200/60 pt-5 dark:border-ink-700/60">
        <div className="mb-4 flex items-center gap-2.5">
          <span className="rounded-lg bg-ink-100 p-1.5 text-ink-500 dark:bg-ink-800 dark:text-ink-400">
            <Palette size={16} />
          </span>
          <h2 className="text-sm font-semibold uppercase tracking-wide text-ink-400">LaTeX Template</h2>
        </div>
        <p className="mb-3 text-xs text-ink-500">
          Document class, layout, and typography.
        </p>
        <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
          {availableTemplates.map((t) => {
            const active = latexTemplate === t.id;
            const Icon = TEMPLATE_ICONS[t.id] ?? BookOpen;
            return (
              <button
                key={t.id}
                type="button"
                onClick={() => setLatexTemplate(t.id)}
                className={`flex flex-col items-start gap-1 rounded-xl border p-3 text-left transition-all duration-200 ${
                  active
                    ? "border-emerald-400 bg-emerald-50/40 shadow-sm dark:bg-emerald-900/20"
                    : "border-ink-200/60 hover:border-ink-400 hover:bg-ink-50/40 dark:border-ink-700/60 dark:hover:bg-ink-800/40"
                }`}
              >
                <div className="flex items-center gap-2">
                  <Icon size={18} className={active ? "text-emerald-500" : "text-ink-400"} />
                  <span className="text-sm font-semibold">{t.label}</span>
                </div>
                <span className="text-xs text-ink-500">{t.description}</span>
              </button>
            );
          })}
        </div>
      </div>
    </div>
  );
}
