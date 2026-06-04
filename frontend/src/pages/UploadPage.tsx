import { ArrowRight } from "lucide-react";
import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import Dropzone from "../components/Dropzone";
import { api, type Backends } from "../lib/api";

export default function UploadPage() {
  const navigate = useNavigate();

  const [files, setFiles] = useState<File[]>([]);
  const [name, setName] = useState("");
  const [language, setLanguage] = useState("italian");
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
      setError(e instanceof Error ? e.message : "Errore");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">
          Nuovo documento
        </h1>
        <p className="mt-1 text-sm text-ink-500">
          Carica i PDF: nel passo successivo potrai scegliere ordine, figure,
          struttura e copertina.
        </p>
      </div>

      <div className="card space-y-4">
        <div>
          <label className="mb-1 block text-sm font-medium">
            Titolo del progetto
          </label>
          <input
            className="input"
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="Es. Appunti di Deep Learning"
          />
        </div>

        <Dropzone files={files} onChange={setFiles} />

        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <div>
            <label className="mb-1 block text-sm font-medium">Lingua</label>
            <select
              className="input"
              value={language}
              onChange={(e) => setLanguage(e.target.value)}
            >
              <option value="italian">Italiano</option>
              <option value="english">English</option>
            </select>
          </div>
          <div>
            <label className="mb-1 block text-sm font-medium">
              Backend di estrazione
            </label>
            <select
              className="input"
              value={backend}
              onChange={(e) => setBackend(e.target.value)}
            >
              <option value="hybrid">
                Ibrido — consigliato (testo + figure + OCR)
              </option>
              <option value="pymupdf">PyMuPDF (veloce)</option>
              <option
                value="docling"
                disabled={backends ? !backends.docling : false}
              >
                Docling (solo testo strutturato)
                {backends && !backends.docling ? " — non installato" : ""}
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
          {submitting ? "Caricamento…" : "Continua"}
          <ArrowRight size={16} />
        </button>
      </div>
    </div>
  );
}
