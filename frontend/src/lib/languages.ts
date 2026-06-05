// Languages offered for the generated document. The `value` is sent to the
// backend (used both as the babel package selector and as the target language
// hint for the LLM); the `label` is what the user sees in the dropdown.
export interface LanguageOption {
  value: string;
  label: string;
}

export const LANGUAGES: LanguageOption[] = [
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
];

export const DEFAULT_LANGUAGE = "english";
