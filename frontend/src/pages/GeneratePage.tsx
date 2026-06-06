import {
  Download,
  ExternalLink,
  FileArchive,
  Gavel,
  Hammer,
  Loader2,
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

  // A run that ended without producing a PDF: offer manual recovery so the work
  // already done (sections, structure) is not lost.
  const runFailed =
    !running &&
    ((latest?.stage === "done" && !latest.pdf) ||
      latest?.stage === "error" ||
      (!latest && project?.status === "failed"));
  const canRecover = runFailed && (project?.total_sections ?? 0) > 0;

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
            src={`${api.viewPdfUrl(id)}#view=FitH`}
            className="h-[70vh] w-full rounded-lg border border-ink-200 dark:border-ink-800"
          />
        </div>
      )}

      {canRecover && (
        <RecoveryActions
          projectId={id}
          providerId={selectedProviderId}
          onRecovered={() =>
            api
              .getProject(id)
              .then(setProject)
              .catch(() => {})
          }
        />
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

function RecoveryActions({
  projectId,
  providerId,
  onRecovered,
}: {
  projectId: string;
  providerId: number | null;
  onRecovered: () => void;
}) {
  const [busy, setBusy] = useState<"recompile" | "rejudge" | null>(null);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);

  async function recompile() {
    if (providerId == null) return;
    setBusy("recompile");
    setMsg(null);
    try {
      const r = await api.recompile(projectId, { provider_id: providerId });
      setMsg({
        ok: r.success,
        text: r.success
          ? "Recompiled successfully — the document is ready."
          : `Still failing: ${r.log_excerpt || "see logs"}`,
      });
      onRecovered();
    } catch (e) {
      setMsg({ ok: false, text: e instanceof Error ? e.message : "Failed" });
    } finally {
      setBusy(null);
    }
  }

  async function rejudge() {
    if (providerId == null) return;
    setBusy("rejudge");
    setMsg(null);
    try {
      const r = await api.rejudge(projectId, { provider_id: providerId });
      const text = r.applied
        ? `Revision applied (${r.issues.length} issue(s)). ${
            r.success ? "Recompiled." : "Recompile failed."
          }`
        : `Approved (score ${r.score}). No changes needed.`;
      setMsg({ ok: r.success, text });
      onRecovered();
    } catch (e) {
      setMsg({ ok: false, text: e instanceof Error ? e.message : "Failed" });
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="card space-y-3 border-amber-300 dark:border-amber-700">
      <div>
        <h2 className="text-sm font-semibold text-amber-600 dark:text-amber-400">
          Run finished with errors
        </h2>
        <p className="mt-1 text-sm text-ink-500">
          The generated sections were saved. Retry the compilation (with
          automatic fixes) or run the judge again — no need to redo the whole
          generation. You can also fix individual sections from the Preview
          page.
        </p>
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <button
          className="btn-primary"
          onClick={recompile}
          disabled={busy !== null || providerId == null}
        >
          {busy === "recompile" ? (
            <Loader2 size={16} className="animate-spin" />
          ) : (
            <Hammer size={16} />
          )}
          Retry compilation
        </button>
        <button
          className="btn-ghost"
          onClick={rejudge}
          disabled={busy !== null || providerId == null}
        >
          {busy === "rejudge" ? (
            <Loader2 size={16} className="animate-spin" />
          ) : (
            <Gavel size={16} />
          )}
          Run judge
        </button>
        <Link className="btn-ghost" to={`/preview/${projectId}`}>
          <ExternalLink size={16} /> Fix sections
        </Link>
      </div>
      {msg && (
        <p
          className={
            msg.ok
              ? "text-xs text-emerald-600 dark:text-emerald-400"
              : "text-xs text-amber-600 dark:text-amber-400"
          }
        >
          {msg.text}
        </p>
      )}
    </div>
  );
}
