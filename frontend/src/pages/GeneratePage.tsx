import {
  ChevronDown,
  ChevronUp,
  ExternalLink,
  Gavel,
  GitGraph,
  Hammer,
  List,
  Loader2,
  Play,
  Search,
  Settings2,
  Square,
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import CompletedCard from "../components/generate/CompletedCard";
import NodeDetailPanel from "../components/generate/NodeDetailPanel";
import RoleProviderGrid from "../components/generate/RoleProviderGrid";
import PipelineGraph from "../components/PipelineGraph";
import {
  deriveState,
  deriveNodeDetails,
  type NodeDetail,
} from "../components/PipelineGraph.utils";
import ProgressTimeline from "../components/ProgressTimeline";
import ProviderSelect from "../components/ProviderSelect";
import { useGenerateWs } from "../hooks/useGenerateWs";
import { api, type Project } from "../lib/api";
import { cn, getResearchSourceStyle } from "../lib/utils";
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

  // Per-role provider assignment
  const [showRoleProviders, setShowRoleProviders] = useState(false);
  const [roleProviders, setRoleProviders] = useState<
    Record<string, { provider_id: number; model?: string }>
  >({});

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
          <ProviderSelect
            providers={providers}
            value={selectedProviderId}
            onChange={(id) => setSelectedProvider(id)}
            disabled={running}
            className="w-48"
          />
          {running ? (
            <button className="btn-ghost" onClick={stop}>
              <Square size={16} /> Stop
            </button>
          ) : (
            <button
              className="btn-primary"
              disabled={!selectedProviderId}
              onClick={() =>
                start(
                  selectedProviderId!,
                  provider?.default_model ?? undefined,
                  Object.keys(roleProviders).length > 0
                    ? roleProviders
                    : undefined,
                )
              }
            >
              <Play size={16} /> Start
            </button>
          )}
        </div>
      </div>

      {/* Per-role provider assignment */}
      <div className="card">
        <button
          type="button"
          className="flex w-full items-center justify-between text-sm"
          onClick={() => setShowRoleProviders(!showRoleProviders)}
          disabled={running}
        >
          <div className="flex items-center gap-2">
            <Settings2 size={15} className="text-ink-400" />
            <span className="font-medium">
              Assign providers per role
            </span>
            {Object.keys(roleProviders).length > 0 && (
              <span className="rounded-full bg-indigo-100 px-1.5 py-0.5 text-[10px] font-semibold text-indigo-600 dark:bg-indigo-900/50 dark:text-indigo-400">
                {Object.keys(roleProviders).length}
              </span>
            )}
          </div>
          {showRoleProviders ? (
            <ChevronUp size={16} className="text-ink-400" />
          ) : (
            <ChevronDown size={16} className="text-ink-400" />
          )}
        </button>

        {showRoleProviders && (
          <RoleProviderGrid
            providers={providers}
            roleProviders={roleProviders}
            setRoleProviders={setRoleProviders}
            running={running}
          />
        )}
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
            <NodeDetailPanel
              selectedNode={selectedNode}
              nodeDetail={nodeDetail}
              graphState={graphState}
              events={events}
              onClose={() => setSelectedNode(null)}
            />
          )}

          {/* Progress bar (always visible) */}
          <div className="card">
            <ProgressTimeline
              events={events}
              latest={latest}
              selectedNode={selectedNode}
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
            selectedNode={selectedNode}
            onNodeClick={(nid) => {
              setSelectedNode(nid);
              setView("graph");
            }}
          />
        </div>
      )}

      {completed && <CompletedCard id={id} />}

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

      {latest?.research_results && latest.research_results.length > 0 && (
        <div className="card space-y-3">
          <div className="flex items-center gap-2">
            <Search size={16} className="text-violet-500" />
            <h2 className="text-sm font-semibold">
              Web sources found ({latest.research_results.length})
            </h2>
          </div>
          <ul className="space-y-1.5 max-h-64 overflow-auto">
            {latest.research_results.map((r, i) => {
              const sourceStyle = getResearchSourceStyle(r.source);
              return (
                <li key={i} className="flex items-start gap-2 rounded-lg px-3 py-2 text-sm transition-colors hover:bg-ink-50 dark:hover:bg-ink-900/50">
                  <span
                    className={cn(
                      "mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded text-[10px]",
                      sourceStyle.color,
                    )}
                  >
                    {sourceStyle.icon}
                  </span>
                  <div className="min-w-0 flex-1">
                    <p className="truncate font-medium text-ink-700 dark:text-ink-200">
                      {r.title}
                    </p>
                    <div className="flex items-center gap-2 text-xs text-ink-400">
                      <span className="truncate">{r.source}</span>
                      {r.url && (
                        <a
                          href={r.url}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="shrink-0 text-violet-500 hover:text-violet-700 dark:text-violet-400 dark:hover:text-violet-300"
                          title={r.url}
                        >
                          <ExternalLink size={11} />
                        </a>
                      )}
                    </div>
                  </div>
                </li>
              );
            })}
          </ul>
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
