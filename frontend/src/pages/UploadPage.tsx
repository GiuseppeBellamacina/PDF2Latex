import { ArrowRight } from "lucide-react";
import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import Dropzone from "../components/Dropzone";
import { api, type Backends } from "../lib/api";
import { DEFAULT_LANGUAGE, LANGUAGES } from "../lib/languages";

export default function UploadPage() {
  const navigate = useNavigate();

  const [files, setFiles] = useState<File[]>([]);
  const [name, setName] = useState("");
  const [language, setLanguage] = useState(DEFAULT_LANGUAGE);
  const [backend, setBackend] = useState("hybrid");
  const [backends, setBackends] = useState<Backends | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .backends()
      .then(setBackends)
      .catch(() => {});
  }, []);

  const canSubmit = files.length > 0 && name.trim();

  async function handleSubmit() {
    if (!canSubmit) return;
    setSubmitting(true);
    setError(null);
    try {
      const form = new FormData();
      form.append("name", name.trim());
      form.append("language", language);
      form.append("extractor_backend", backend);
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
          Upload your PDFs: in the next step you can choose order, figures,
          structure and cover page.
        </p>
      </div>

      <div className="card space-y-4">
        <div>
          <label className="mb-1 block text-sm font-medium">
            Project title
          </label>
          <input
            className="input"
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="e.g. Deep Learning notes"
          />
        </div>

        <Dropzone files={files} onChange={setFiles} />

        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <div>
            <label className="mb-1 block text-sm font-medium">Language</label>
            <select
              className="input"
              value={language}
              onChange={(e) => setLanguage(e.target.value)}
            >
              {LANGUAGES.map((l) => (
                <option key={l.value} value={l.value}>
                  {l.label}
                </option>
              ))}
            </select>
          </div>
          <div>
            <label className="mb-1 block text-sm font-medium">
              Extraction backend
            </label>
            <select
              className="input"
              value={backend}
              onChange={(e) => setBackend(e.target.value)}
            >
              <option value="hybrid">
                Hybrid — recommended (text + figures + OCR)
              </option>
              <option value="pymupdf">PyMuPDF (fast)</option>
              <option
                value="docling"
                disabled={backends ? !backends.docling : false}
              >
                Docling (structured text only)
                {backends && !backends.docling ? " — not installed" : ""}
              </option>
            </select>
          </div>
        </div>

        {error && <p className="text-sm text-red-500">{error}</p>}

        <button
          className="btn-primary w-full"
          disabled={!canSubmit || submitting}
          onClick={handleSubmit}
        >
          {submitting ? "Uploading…" : "Continue"}
          <ArrowRight size={16} />
        </button>
      </div>
    </div>
  );
}
