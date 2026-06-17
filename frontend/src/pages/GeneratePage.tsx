import {
  Download,
  ExternalLink,
  FileArchive,
  Gavel,
  GitGraph,
  Hammer,
  List,
  Loader2,
  Play,
  Square,
  X,
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import PipelineGraph, {
  deriveState,
  deriveNodeDetails,
  statusBadge,
  NODE_ICONS,
  type NodeDetail,
} from "../components/PipelineGraph";
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

  const [view, setView] = useState<"graph" | "log">("graph");
  const [selectedNode, setSelectedNode] = useState<string | null>(null);

  const graphState = useMemo(() => deriveState(events), [events]);
  const nodeDetail: NodeDetail | null = selectedNode
    ? deriveNodeDetails(selectedNode, events, graphState)
    : null;

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

      {/* View toggle */}
      <div className="flex items-center gap-1 rounded-lg border border-ink-200/60 bg-ink-50/50 p-1 w-fit dark:border-ink-800/60 dark:bg-ink-900/50">
        <button
          onClick={() => setView("graph")}
          className={`flex items-center gap-1.5 rounded-md px-3 py-1.5 text-xs font-medium transition-colors ${
            view === "graph"
              ? "bg-white text-ink-900 shadow-sm dark:bg-ink-800 dark:text-ink-100"
              : "text-ink-500 hover:text-ink-700"
          }`}
        >
          <GitGraph size={14} /> Graph
        </button>
        <button
          onClick={() => setView("log")}
          className={`flex items-center gap-1.5 rounded-md px-3 py-1.5 text-xs font-medium transition-colors ${
            view === "log"
              ? "bg-white text-ink-900 shadow-sm dark:bg-ink-800 dark:text-ink-100"
              : "text-ink-500 hover:text-ink-700"
          }`}
        >
          <List size={14} /> Log
        </button>
      </div>

      {/* Graph view */}
      {view === "graph" && (
        <div className="space-y-4">
          <PipelineGraph events={events} onNodeClick={setSelectedNode} />

          {/* Node detail panel */}
          {selectedNode && nodeDetail && (
            <div className="card space-y-3">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2.5">
                  <span
                    className="rounded-lg p-1.5"
                    style={{
                      backgroundColor: statusBadge(nodeDetail.status).color + "18",
                      color: statusBadge(nodeDetail.status).color,
                    }}
                  >
                    <svg width={16} height={16} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2}>
                      <path d={NODE_ICONS[selectedNode] ?? ""} />
                    </svg>
                  </span>
                  <div>
                    <h3 className="text-sm font-semibold">{nodeDetail.title}</h3>
                    <span
                      className="rounded-full px-2 py-0.5 text-[10px] font-medium"
                      style={{
                        backgroundColor: statusBadge(nodeDetail.status).color + "18",
                        color: statusBadge(nodeDetail.status).color,
                      }}
                    >
                      {statusBadge(nodeDetail.status).label}
                    </span>
                  </div>
                </div>
                <button
                  className="rounded-md p-1 text-ink-400 hover:text-ink-700 hover:bg-ink-100 dark:hover:bg-ink-800"
                  onClick={() => setSelectedNode(null)}
                >
                  <X size={16} />
                </button>
              </div>

              {/* Divider */}
              <div
                className="h-0.5 w-full rounded-full"
                style={{
                  backgroundColor: (
                    nodeDetail.level === "error" ? "#EF4444"
                    : nodeDetail.level === "warning" ? "#F59E0B"
                    : nodeDetail.level === "success" ? "#10B981"
                    : "#6B7280"
                  ) + "30",
                }}
              />

              {/* Detail lines */}
              <div className="space-y-1.5">
                {nodeDetail.lines.map((line, i) => {
                  const isSection = line.startsWith("  ");
                  return (
                    <div
                      key={i}
                      className={`text-sm leading-relaxed ${
                        isSection
                          ? "ml-2 text-ink-500 dark:text-ink-400"
                          : "text-ink-700 dark:text-ink-300 font-medium"
                      }`}
                    >
                      {line.trimStart()}
                    </div>
                  );
                })}
              </div>

              {/* Extra: show full chapter list for Write node */}
              {selectedNode === "write" && graphState.chapters.length > 0 && (
                <div className="rounded-lg border border-ink-200/60 p-3 dark:border-ink-700/60">
                  <p className="mb-2 text-xs font-medium text-ink-400 uppercase">
                    Chapter details
                  </p>
                  <div className="space-y-2">
                    {graphState.chapters.map((ch) => {
                      const prog = graphState.chapterProgress[ch.name];
                      const done = prog?.done ?? 0;
                      const total = prog?.total ?? ch.sections;
                      const pct = total > 0 ? Math.round((done / total) * 100) : 0;
                      return (
                        <div key={ch.name}>
                          <div className="flex items-center justify-between text-xs">
                            <span className="font-medium text-ink-700 dark:text-ink-300">
                              {ch.name}
                            </span>
                            <span className="tabular-nums text-ink-400">
                              {done}/{total} sections ({pct}%)
                            </span>
                          </div>
                          <div className="mt-1 h-1.5 overflow-hidden rounded-full bg-ink-200 dark:bg-ink-800">
                            <div
                              className="h-full rounded-full transition-all duration-500"
                              style={{
                                width: `${pct}%`,
                                backgroundColor: done === total && total > 0 ? "#34D399" : "#10B981",
                              }}
                            />
                          </div>
                        </div>
                      );
                    })}
                  </div>
                </div>
              )}

              {/* Extra: show full structure for Plan node */}
              {selectedNode === "plan" && (() => {
                const planEvent = events.find((e) => e.node === "plan" && e.plan);
                if (!planEvent?.plan) return null;
                return (
                  <div className="rounded-lg border border-ink-200/60 p-3 dark:border-ink-700/60">
                    <p className="mb-2 text-xs font-medium text-ink-400 uppercase">
                      Full structure ({planEvent.plan.length} sections)
                    </p>
                    <ol className="space-y-1 text-sm text-ink-600 dark:text-ink-400">
                      {planEvent.plan.map((s, i) => (
                        <li key={i} className="flex gap-2">
                          <span className="shrink-0 tabular-nums text-ink-400">{i + 1}.</span>
                          <span>
                            <span className="font-medium text-ink-700 dark:text-ink-300">{s.part_title}</span>
                            {" — "}{s.title}
                          </span>
                        </li>
                      ))}
                    </ol>
                  </div>
                );
              })()}

              {/* Extra: show compilation log for Review node */}
              {selectedNode === "review" && (() => {
                const reviewEvents = events.filter((e) => e.node === "review");
                if (!reviewEvents.length) return null;
                return (
                  <div className="rounded-lg border border-ink-200/60 p-3 dark:border-ink-700/60">
                    <p className="mb-2 text-xs font-medium text-ink-400 uppercase">
                      Compilation log ({reviewEvents.length} event{reviewEvents.length !== 1 ? "s" : ""})
                    </p>
                    <div className="max-h-48 overflow-y-auto rounded bg-ink-50 p-2 font-mono text-[11px] leading-relaxed dark:bg-ink-950">
                      {reviewEvents.map((e, i) => (
                        <div
                          key={i}
                          className={
                            e.level === "error"
                              ? "text-red-600 dark:text-red-400"
                              : e.level === "warning"
                                ? "text-amber-600 dark:text-amber-400"
                                : e.level === "success"
                                  ? "text-emerald-600 dark:text-emerald-400"
                                  : "text-ink-500"
                          }
                        >
                          <span className="text-ink-400">[{e.stage}]</span>{" "}
                          {e.message}
                          {e.detail && <span className="text-ink-400"> — {e.detail}</span>}
                        </div>
                      ))}
                    </div>
                  </div>
                );
              })()}
            </div>
          )}

          {/* Progress bar (always visible) */}
          <div className="card">
            <ProgressTimeline
              events={events}
              latest={latest}
              onNodeClick={(nid) => {
                setSelectedNode(nid);
                setView("graph");
              }}
            />
          </div>
        </div>
      )}

      {/* Log view */}
      {view === "log" && (
        <div className="card">
          <ProgressTimeline
            events={events}
            latest={latest}
            onNodeClick={(nid) => {
              setSelectedNode(nid);
              setView("graph");
            }}
          />
        </div>
      )}

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
