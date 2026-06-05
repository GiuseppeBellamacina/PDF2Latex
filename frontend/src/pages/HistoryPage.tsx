import { Eye, Trash2 } from "lucide-react";
import { useEffect } from "react";
import { Link } from "react-router-dom";
import { api } from "../lib/api";
import { formatDate } from "../lib/utils";
import { useAppStore } from "../stores/appStore";

export default function HistoryPage() {
  const { projects, loadProjects } = useAppStore();

  useEffect(() => {
    loadProjects();
  }, [loadProjects]);

  async function remove(id: number) {
    await api.deleteProject(id);
    loadProjects();
  }

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-semibold tracking-tight">History</h1>

      {projects.length === 0 ? (
        <p className="text-sm text-ink-500">No projects yet.</p>
      ) : (
        <div className="space-y-2">
          {projects.map((p) => (
            <div
              key={p.id}
              className="flex items-center justify-between rounded-xl border border-ink-200 px-4 py-3 dark:border-ink-800"
            >
              <div>
                <p className="font-medium">{p.name}</p>
                <p className="text-xs text-ink-500">
                  {p.status} · {p.total_sources} PDF ·{" "}
                  {formatDate(p.created_at)}
                </p>
              </div>
              <div className="flex gap-2">
                <Link className="btn-ghost h-9 w-9 p-0" to={`/preview/${p.id}`}>
                  <Eye size={15} />
                </Link>
                <button
                  className="btn-ghost h-9 w-9 p-0"
                  onClick={() => remove(p.id)}
                >
                  <Trash2 size={15} />
                </button>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
