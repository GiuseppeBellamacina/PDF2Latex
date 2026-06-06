import {
  Download,
  ExternalLink,
  FileArchive,
  Play,
  Square,
} from "lucide-react";
import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import ProgressTimeline from "../components/ProgressTimeline";
import { useGenerateWs } from "../hooks/useGenerateWs";
import { api, type Project } from "../lib/api";
import { useAppStore } from "../stores/appStore";

export default function GeneratePage() {
  const { projectId } = useParams();
  const id = projectId ?? "";

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

  const completed = latest?.stage === "done" && !!latest.pdf;

  useEffect(() => {
    if (completed) {
      api
        .getProject(id)
        .then(setProject)
        .catch(() => {});
    }
  }, [completed, id]);

  const provider = providers.find((p) => p.id === selectedProviderId);

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">
            {project?.name ?? "Generation"}
          </h1>
          <p className="mt-1 text-sm text-ink-500">
            {project?.total_sources ?? 0} documents · language{" "}
            {project?.language}
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
              <Play size={16} /> Start
            </button>
          )}
        </div>
      </div>

      <div className="card">
        <ProgressTimeline events={events} latest={latest} />
      </div>

      {completed && (
        <div className="card space-y-4">
          <div className="flex items-center justify-between">
            <h2 className="text-sm font-semibold text-emerald-600 dark:text-emerald-400">
              Document ready
            </h2>
            <div className="flex gap-2">
              <a className="btn-ghost" href={api.downloadUrl(id, "tex")}>
                <FileArchive size={16} /> LaTeX (.zip)
              </a>
              <a className="btn-ghost" href={api.downloadUrl(id, "pdf")}>
                <Download size={16} /> PDF
              </a>
              <Link className="btn-primary" to={`/preview/${id}`}>
                <ExternalLink size={16} /> Preview
              </Link>
            </div>
          </div>
          <iframe
            title="PDF preview"
            src={`${api.downloadUrl(id, "pdf")}#view=FitH`}
            className="h-[70vh] w-full rounded-lg border border-ink-200 dark:border-ink-800"
          />
        </div>
      )}

      {latest?.plan && latest.plan.length > 0 && (
        <div className="card">
          <h2 className="mb-3 text-sm font-semibold">Proposed structure</h2>
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
