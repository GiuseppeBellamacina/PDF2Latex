import { BookOpen } from "lucide-react";

interface Props {
  name: string;
  setName: (v: string) => void;
  author: string;
  setAuthor: (v: string) => void;
  subtitle: string;
  setSubtitle: (v: string) => void;
  coverDate: string;
  setCoverDate: (v: string) => void;
  abstract: string;
  setAbstract: (v: string) => void;
}

export default function InformationPanel({
  name, setName,
  author, setAuthor,
  subtitle, setSubtitle,
  coverDate, setCoverDate,
  abstract, setAbstract,
}: Props) {
  return (
    <div className="space-y-5">
      <div className="flex items-center gap-2.5">
        <span className="rounded-lg bg-ink-100 p-1.5 text-ink-500 dark:bg-ink-800 dark:text-ink-400">
          <BookOpen size={16} />
        </span>
        <h2 className="text-sm font-semibold uppercase tracking-wide text-ink-400">Cover & Metadata</h2>
      </div>

      <div>
        <label className="mb-1 block text-sm font-medium">Title</label>
        <input
          className="input"
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="Document title"
        />
      </div>

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        <div>
          <label className="mb-1 block text-sm font-medium">
            Subtitle <span className="text-ink-400">— optional</span>
          </label>
          <input
            className="input"
            value={subtitle}
            onChange={(e) => setSubtitle(e.target.value)}
            placeholder="e.g. A complete overview"
          />
        </div>
        <div>
          <label className="mb-1 block text-sm font-medium">
            Author <span className="text-ink-400">— optional</span>
          </label>
          <input
            className="input"
            value={author}
            onChange={(e) => setAuthor(e.target.value)}
            placeholder="First and last name"
          />
        </div>
      </div>

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        <div>
          <label className="mb-1 block text-sm font-medium">
            Date <span className="text-ink-400">— optional</span>
          </label>
          <input
            className="input"
            value={coverDate}
            onChange={(e) => setCoverDate(e.target.value)}
            placeholder="e.g. January 2025"
          />
        </div>
        <div />
      </div>

      <div>
        <label className="mb-1 block text-sm font-medium">
          Abstract <span className="text-ink-400">— optional</span>
        </label>
        <textarea
          className="input min-h-24 resize-y"
          value={abstract}
          onChange={(e) => setAbstract(e.target.value)}
          placeholder="Short summary of the document, shown on the first page…"
        />
      </div>
    </div>
  );
}
