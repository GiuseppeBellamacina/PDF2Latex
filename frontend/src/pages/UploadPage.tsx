import { Sparkles } from "lucide-react";
import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import Dropzone from "../components/Dropzone";
import { api } from "../lib/api";
import { useAppStore } from "../stores/appStore";

export default function UploadPage() {
  const navigate = useNavigate();
  const { providers, selectedProviderId, loadProviders, setSelectedProvider } =
    useAppStore();

  const [files, setFiles] = useState<File[]>([]);
  const [name, setName] = useState("");
  const [prompt, setPrompt] = useState("");
  const [language, setLanguage] = useState("italian");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    loadProviders();
  }, [loadProviders]);

  const canSubmit = files.length > 0 && name.trim() && selectedProviderId;

  async function handleSubmit() {
    if (!canSubmit) return;
    setSubmitting(true);
    setError(null);
    try {
      const form = new FormData();
      form.append("name", name.trim());
      form.append("user_prompt", prompt);
      form.append("language", language);
      files.forEach((f) => form.append("files", f));
      const project = await api.createProject(form);
      navigate(`/generate/${project.id}`);
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
          Carica uno o più PDF e genera un documento LaTeX organico e completo.
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

        <div>
          <label className="mb-1 block text-sm font-medium">
            Istruzioni personalizzate{" "}
            <span className="text-ink-400">(opzionale)</span>
          </label>
          <textarea
            className="input min-h-24 resize-y"
            value={prompt}
            onChange={(e) => setPrompt(e.target.value)}
            placeholder="Es. Concentrati sulle architetture, includi le formule chiave, taglio divulgativo…"
          />
        </div>

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
              Provider LLM
            </label>
            <select
              className="input"
              value={selectedProviderId ?? ""}
              onChange={(e) =>
                setSelectedProvider(Number(e.target.value) || null)
              }
            >
              <option value="">— seleziona —</option>
              {providers.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name} ({p.provider_type})
                </option>
              ))}
            </select>
          </div>
        </div>

        {providers.length === 0 && (
          <p className="text-xs text-ink-500">
            Nessun provider configurato. Vai in <strong>Provider</strong> per
            aggiungerne uno (o usa il provider <em>fake</em> per una prova
            offline).
          </p>
        )}

        {error && <p className="text-sm text-red-500">{error}</p>}

        <button
          className="btn-primary w-full"
          disabled={!canSubmit || submitting}
          onClick={handleSubmit}
        >
          <Sparkles size={16} />
          {submitting ? "Creazione…" : "Genera documento"}
        </button>
      </div>
    </div>
  );
}
