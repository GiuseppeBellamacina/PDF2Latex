import { Play, Square } from "lucide-react";
import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import ProgressTimeline from "../components/ProgressTimeline";
import { useGenerateWs } from "../hooks/useGenerateWs";
import { api, type Project } from "../lib/api";
import { useAppStore } from "../stores/appStore";

export default function GeneratePage() {
  const { projectId } = useParams();
  const id = Number(projectId);
  const navigate = useNavigate();

  const { providers, selectedProviderId, loadProviders, setSelectedProvider } =
    useAppStore();
  const [project, setProject] = useState<Project | null>(null);
  const { events, latest, running, start, stop } = useGenerateWs(id);

  useEffect(() => {
    loadProviders();
    api
      .getProject(id)
      .then(setProject)
      .catch(() => {});
  }, [id, loadProviders]);

  useEffect(() => {
    if (latest?.stage === "done" && latest.pdf) {
      const t = setTimeout(() => navigate(`/preview/${id}`), 1200);
      return () => clearTimeout(t);
    }
  }, [latest, id, navigate]);

  const provider = providers.find((p) => p.id === selectedProviderId);

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">
            {project?.name ?? "Generazione"}
          </h1>
          <p className="mt-1 text-sm text-ink-500">
            {project?.total_sources ?? 0} documenti · lingua {project?.language}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <select
            className="input w-auto"
            value={selectedProviderId ?? ""}
            onChange={(e) =>
              setSelectedProvider(Number(e.target.value) || null)
            }
            disabled={running}
          >
            <option value="">— provider —</option>
            {providers.map((p) => (
              <option key={p.id} value={p.id}>
                {p.name}
              </option>
            ))}
          </select>
          {running ? (
            <button className="btn-ghost" onClick={stop}>
              <Square size={16} /> Stop
            </button>
          ) : (
            <button
              className="btn-primary"
              disabled={!selectedProviderId}
              onClick={() =>
                start(selectedProviderId!, provider?.default_model ?? undefined)
              }
            >
              <Play size={16} /> Avvia
            </button>
          )}
        </div>
      </div>

      <div className="card">
        <ProgressTimeline events={events} latest={latest} />
      </div>

      {latest?.plan && latest.plan.length > 0 && (
        <div className="card">
          <h2 className="mb-3 text-sm font-semibold">Struttura proposta</h2>
          <ul className="space-y-1 text-sm text-ink-600 dark:text-ink-400">
            {latest.plan.map((s, i) => (
              <li key={i}>
                <span className="text-ink-400">{s.part_title}</span> — {s.title}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
