import { Download, FileArchive, FileCode, FileText } from "lucide-react";
import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { api, type Project } from "../lib/api";
import { cn } from "../lib/utils";

export default function PreviewPage() {
  const { projectId } = useParams();
  const id = projectId ?? "";
  const [project, setProject] = useState<Project | null>(null);
  const [latex, setLatex] = useState<string>("");
  const [tab, setTab] = useState<"pdf" | "latex">("pdf");

  useEffect(() => {
    api
      .getProject(id)
      .then(setProject)
      .catch(() => {});
    api
      .previewLatex(id)
      .then((r) => setLatex(r.latex))
      .catch(() => setLatex(""));
  }, [id]);

  const hasPdf = !!project?.output_pdf_path;

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">
            {project?.name ?? "Preview"}
          </h1>
          <p className="mt-1 text-sm text-ink-500">
            Status: {project?.status} · {project?.total_sections ?? 0} sections
          </p>
        </div>
        <div className="flex gap-2">
          <a className="btn-ghost" href={api.downloadUrl(id, "tex")}>
            <FileArchive size={16} /> LaTeX (.zip)
          </a>
          {hasPdf && (
            <a className="btn-primary" href={api.downloadUrl(id, "pdf")}>
              <Download size={16} /> PDF
            </a>
          )}
        </div>
      </div>

      <div className="flex gap-1">
        {(["pdf", "latex"] as const).map((t) => (
          <button
            key={t}
            onClick={() => setTab(t)}
            className={cn(
              "btn-ghost border-transparent",
              tab === t && "bg-ink-200 dark:bg-ink-800",
            )}
          >
            {t === "pdf" ? <FileText size={15} /> : <FileCode size={15} />}
            {t === "pdf" ? "PDF" : "LaTeX source"}
          </button>
        ))}
      </div>

      <div className="card overflow-hidden p-0">
        {tab === "pdf" ? (
          hasPdf ? (
            <iframe
              title="PDF"
              src={api.downloadUrl(id, "pdf")}
              className="h-[70vh] w-full"
            />
          ) : (
            <div className="p-10 text-center text-sm text-ink-500">
              PDF not available. {project?.error_message}
            </div>
          )
        ) : (
          <pre className="max-h-[70vh] overflow-auto p-4 font-mono text-xs leading-relaxed">
            {latex || "No source available."}
          </pre>
        )}
      </div>
    </div>
  );
}
