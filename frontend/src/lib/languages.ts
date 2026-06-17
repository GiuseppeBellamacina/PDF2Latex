// Language suggestions for the generated document. The `value` is sent to the
// backend (used both as the babel package selector and as the target language
// hint for the LLM). The user types freely; this list provides datalist hints.
export interface LanguageOption {
  value: string;
  label: string;
}

export const LANGUAGE_SUGGESTIONS: LanguageOption[] = [
  { value: "english", label: "English" },
  { value: "italian", label: "Italiano" },
  { value: "french", label: "Français" },
  { value: "german", label: "Deutsch" },
  { value: "spanish", label: "Español" },
  { value: "portuguese", label: "Português" },
  { value: "dutch", label: "Nederlands" },
  { value: "russian", label: "Русский" },
  { value: "polish", label: "Polski" },
  { value: "swedish", label: "Svenska" },
  { value: "chinese", label: "中文" },
  { value: "japanese", label: "日本語" },
  { value: "arabic", label: "العربية" },
];
