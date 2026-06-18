import { Download, ExternalLink, FileArchive } from "lucide-react";
import { Link } from "react-router-dom";
import { api } from "../../lib/api";

interface Props {
  id: string;
}

export default function CompletedCard({ id }: Props) {
  return (
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
  );
}
