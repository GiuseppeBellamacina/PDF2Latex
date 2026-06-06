import CodeMirror from "@uiw/react-codemirror";
import { EditorView } from "@codemirror/view";
import { latex } from "codemirror-lang-latex";
import { useEffect, useMemo, useState } from "react";

/** Track the global dark-mode flag toggled on the <html> element. */
function useHtmlDark(): boolean {
  const [dark, setDark] = useState(() =>
    document.documentElement.classList.contains("dark"),
  );
  useEffect(() => {
    const root = document.documentElement;
    const obs = new MutationObserver(() =>
      setDark(root.classList.contains("dark")),
    );
    obs.observe(root, { attributes: true, attributeFilter: ["class"] });
    return () => obs.disconnect();
  }, []);
  return dark;
}

export function FileEditor({
  value,
  language,
  onChange,
  readOnly = false,
}: {
  value: string;
  language: "latex" | "bibtex";
  onChange?: (v: string) => void;
  readOnly?: boolean;
}) {
  const dark = useHtmlDark();
  const extensions = useMemo(() => {
    const exts = [EditorView.lineWrapping];
    if (language === "latex") exts.push(latex());
    return exts;
  }, [language]);

  return (
    <CodeMirror
      value={value}
      theme={dark ? "dark" : "light"}
      height="65vh"
      extensions={extensions}
      editable={!readOnly}
      readOnly={readOnly}
      onChange={onChange}
      basicSetup={{ lineNumbers: true, foldGutter: true }}
      className="text-sm"
    />
  );
}
