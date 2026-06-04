import {
  ArrowDown,
  ArrowRight,
  ArrowUp,
  CheckCircle2,
  ImageIcon,
  Loader2,
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import {
  api,
  type Backends,
  type Figure,
  type Project,
  type Source,
} from "../lib/api";

export default function ConfigurePage() {
  const { projectId } = useParams();
  const id = Number(projectId);
  const navigate = useNavigate();

  const [project, setProject] = useState<Project | null>(null);
  const [backends, setBackends] = useState<Backends | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Editable state
  const [name, setName] = useState("");
  const [author, setAuthor] = useState("");
  const [subtitle, setSubtitle] = useState("");
  const [coverDate, setCoverDate] = useState("");
  const [abstract, setAbstract] = useState("");
  const [prompt, setPrompt] = useState("");
  const [structureHint, setStructureHint] = useState("");
  const [language, setLanguage] = useState("italian");
  const [backend, setBackend] = useState("pymupdf");
  const [enableOcr, setEnableOcr] = useState(false);
  const [orderedSources, setOrderedSources] = useState<Source[]>([]);
  const [mandatoryIds, setMandatoryIds] = useState<Set<number>>(new Set());

  useEffect(() => {
    Promise.all([api.getProject(id), api.backends().catch(() => null)])
      .then(([p, b]) => {
        setProject(p);
        setBackends(b);
        setName(p.name ?? "");
        setAuthor(p.author ?? "");
        setSubtitle(p.subtitle ?? "");
        setCoverDate(p.cover_date ?? "");
        setAbstract(p.abstract ?? "");
        setPrompt(p.user_prompt ?? "");
        setStructureHint(p.structure_hint ?? "");
        setLanguage(p.language ?? "italian");
        setBackend(p.extractor_backend ?? "pymupdf");
        setEnableOcr(!!p.enable_ocr);
        setOrderedSources(
          [...p.sources].sort((a, b) => a.order_index - b.order_index),
        );
        setMandatoryIds(
          new Set(p.figures.filter((f) => f.mandatory).map((f) => f.id)),
        );
      })
      .catch((e) =>
        setError(e instanceof Error ? e.message : "Progetto non trovato"),
      )
      .finally(() => setLoading(false));
  }, [id]);

  const figuresBySource = useMemo(() => {
    const map = new Map<string, Figure[]>();
    for (const f of project?.figures ?? []) {
      const key = f.source_filename ?? "—";
      if (!map.has(key)) map.set(key, []);
      map.get(key)!.push(f);
    }
    for (const list of map.values())
      list.sort((a, b) => a.order_index - b.order_index);
    return map;
  }, [project]);

  function moveSource(index: number, dir: -1 | 1) {
    setOrderedSources((prev) => {
      const next = [...prev];
      const target = index + dir;
      if (target < 0 || target >= next.length) return prev;
      [next[index], next[target]] = [next[target], next[index]];
      return next;
    });
  }

  function toggleMandatory(figId: number) {
    setMandatoryIds((prev) => {
      const next = new Set(prev);
      if (next.has(figId)) next.delete(figId);
      else next.add(figId);
      return next;
    });
  }

  function selectFigures(mode: "suggested" | "all" | "none") {
    const figs = project?.figures ?? [];
    if (mode === "none") return setMandatoryIds(new Set());
    if (mode === "all") return setMandatoryIds(new Set(figs.map((f) => f.id)));
    setMandatoryIds(new Set(figs.filter((f) => f.suggested).map((f) => f.id)));
  }

  async function save(thenGenerate: boolean) {
    setSaving(true);
    setError(null);
    try {
      await api.updateProject(id, {
        name: name.trim() || undefined,
        user_prompt: prompt,
        language,
        author,
        subtitle,
        abstract,
        cover_date: coverDate,
        structure_hint: structureHint,
        extractor_backend: backend,
        enable_ocr: enableOcr,
        source_order: orderedSources.map((s) => s.id),
        mandatory_figure_ids: [...mandatoryIds],
      });
      if (thenGenerate) navigate(`/generate/${id}`);
      else {
        const fresh = await api.getProject(id);
        setProject(fresh);
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "Errore nel salvataggio");
    } finally {
      setSaving(false);
    }
  }

  if (loading) {
    return (
      <div className="flex items-center gap-2 text-ink-500">
        <Loader2 size={18} className="animate-spin" /> Caricamento…
      </div>
    );
  }

  if (!project) {
    return (
      <p className="text-sm text-red-500">{error ?? "Progetto non trovato"}</p>
    );
  }

  const totalFigures = project.figures.length;

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">
          Configura il documento
        </h1>
        <p className="mt-1 text-sm text-ink-500">
          Definisci copertina, struttura, ordine di estrazione e figure
          obbligatorie prima di generare.
        </p>
      </div>

      {/* Copertina / metadati */}
      <section className="card space-y-4">
        <h2 className="text-sm font-semibold uppercase tracking-wide text-ink-400">
          Copertina e prima pagina
        </h2>
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <div>
            <label className="mb-1 block text-sm font-medium">Titolo</label>
            <input
              className="input"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="Titolo del documento"
            />
          </div>
          <div>
            <label className="mb-1 block text-sm font-medium">
              Sottotitolo <span className="text-ink-400">(opzionale)</span>
            </label>
            <input
              className="input"
              value={subtitle}
              onChange={(e) => setSubtitle(e.target.value)}
              placeholder="Es. Una panoramica completa"
            />
          </div>
          <div>
            <label className="mb-1 block text-sm font-medium">
              Autore <span className="text-ink-400">(opzionale)</span>
            </label>
            <input
              className="input"
              value={author}
              onChange={(e) => setAuthor(e.target.value)}
              placeholder="Nome e cognome"
            />
          </div>
          <div>
            <label className="mb-1 block text-sm font-medium">
              Data <span className="text-ink-400">(opzionale)</span>
            </label>
            <input
              className="input"
              value={coverDate}
              onChange={(e) => setCoverDate(e.target.value)}
              placeholder="Es. Gennaio 2025"
            />
          </div>
        </div>
        <div>
          <label className="mb-1 block text-sm font-medium">
            Abstract <span className="text-ink-400">(opzionale)</span>
          </label>
          <textarea
            className="input min-h-20 resize-y"
            value={abstract}
            onChange={(e) => setAbstract(e.target.value)}
            placeholder="Breve riassunto del documento, mostrato dopo la copertina…"
          />
        </div>
      </section>

      {/* Struttura / indice */}
      <section className="card space-y-4">
        <h2 className="text-sm font-semibold uppercase tracking-wide text-ink-400">
          Struttura, indice e istruzioni
        </h2>
        <div>
          <label className="mb-1 block text-sm font-medium">
            Struttura / indice desiderato{" "}
            <span className="text-ink-400">(opzionale)</span>
          </label>
          <textarea
            className="input min-h-24 resize-y"
            value={structureHint}
            onChange={(e) => setStructureHint(e.target.value)}
            placeholder={
              "Indica capitoli, sezioni, ordine. Es.\n1. Introduzione\n2. Fondamenti teorici\n3. Architetture\n4. Conclusioni"
            }
          />
          <p className="mt-1 text-xs text-ink-500">
            Se lasciato vuoto, la struttura segue l'ordine di estrazione dei
            documenti.
          </p>
        </div>
        <div>
          <label className="mb-1 block text-sm font-medium">
            Istruzioni personalizzate{" "}
            <span className="text-ink-400">(opzionale)</span>
          </label>
          <textarea
            className="input min-h-20 resize-y"
            value={prompt}
            onChange={(e) => setPrompt(e.target.value)}
            placeholder="Es. Taglio divulgativo, includi le formule chiave…"
          />
        </div>
      </section>

      {/* Ordine di estrazione */}
      <section className="card space-y-4">
        <h2 className="text-sm font-semibold uppercase tracking-wide text-ink-400">
          Ordine di estrazione dei PDF
        </h2>
        <p className="text-xs text-ink-500">
          L'ordine qui sotto determina la sequenza con cui i contenuti vengono
          uniti nel documento finale.
        </p>
        <ul className="space-y-2">
          {orderedSources.map((s, i) => (
            <li
              key={s.id}
              className="flex items-center gap-3 rounded-lg border border-ink-800/60 bg-ink-900/40 px-3 py-2"
            >
              <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-ink-800 text-xs font-medium">
                {i + 1}
              </span>
              <div className="min-w-0 flex-1">
                <p className="truncate text-sm font-medium">{s.filename}</p>
                <p className="text-xs text-ink-500">{s.n_pages} pagine</p>
              </div>
              <div className="flex items-center gap-1">
                <button
                  className="btn-ghost px-2"
                  disabled={i === 0}
                  onClick={() => moveSource(i, -1)}
                  title="Sposta su"
                >
                  <ArrowUp size={16} />
                </button>
                <button
                  className="btn-ghost px-2"
                  disabled={i === orderedSources.length - 1}
                  onClick={() => moveSource(i, 1)}
                  title="Sposta giù"
                >
                  <ArrowDown size={16} />
                </button>
              </div>
            </li>
          ))}
        </ul>
      </section>

      {/* Estrazione / OCR */}
      <section className="card space-y-4">
        <h2 className="text-sm font-semibold uppercase tracking-wide text-ink-400">
          Estrazione contenuti
        </h2>
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
              Backend di estrazione
            </label>
            <select
              className="input"
              value={backend}
              onChange={(e) => setBackend(e.target.value)}
            >
              <option value="hybrid">
                Ibrido — consigliato (testo + figure + OCR)
              </option>
              <option value="pymupdf">PyMuPDF (veloce)</option>
              <option
                value="docling"
                disabled={backends ? !backends.docling : false}
              >
                Docling (solo testo strutturato)
                {backends && !backends.docling ? " — non installato" : ""}
              </option>
            </select>
          </div>
        </div>
        <label className="flex items-center gap-2 text-sm">
          <input
            type="checkbox"
            className="h-4 w-4 accent-emerald-500"
            checked={enableOcr}
            disabled={backends ? !backends.ocr : false}
            onChange={(e) => setEnableOcr(e.target.checked)}
          />
          Abilita OCR sulle pagine (più lento, utile per PDF scansionati)
          {backends && !backends.ocr ? (
            <span className="text-ink-500"> — Tesseract non installato</span>
          ) : null}
        </label>
        <p className="text-xs text-ink-500">
          Le figure vengono già analizzate con OCR al caricamento: quelle che
          contengono dati (grafici, schemi) sono marcate come{" "}
          <span className="text-emerald-400">Consigliate</span> e preselezionate
          qui sotto.
        </p>
      </section>

      {/* Figure obbligatorie */}
      <section className="card space-y-4">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h2 className="text-sm font-semibold uppercase tracking-wide text-ink-400">
            Figure da includere
          </h2>
          <span className="text-xs text-ink-500">
            {mandatoryIds.size} / {totalFigures} selezionate
          </span>
        </div>
        {totalFigures > 0 && (
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-xs text-ink-500">Selezione rapida:</span>
            <button
              type="button"
              className="btn-ghost px-2 py-1 text-xs"
              onClick={() => selectFigures("suggested")}
            >
              Consigliate
            </button>
            <button
              type="button"
              className="btn-ghost px-2 py-1 text-xs"
              onClick={() => selectFigures("all")}
            >
              Tutte
            </button>
            <button
              type="button"
              className="btn-ghost px-2 py-1 text-xs"
              onClick={() => selectFigures("none")}
            >
              Nessuna
            </button>
          </div>
        )}
        {totalFigures === 0 ? (
          <p className="flex items-center gap-2 text-sm text-ink-500">
            <ImageIcon size={16} /> Nessuna figura estratta dai PDF.
          </p>
        ) : (
          <div className="space-y-6">
            {orderedSources.map((s) => {
              const figs = figuresBySource.get(s.filename) ?? [];
              if (figs.length === 0) return null;
              return (
                <div key={s.id} className="space-y-2">
                  <p className="text-sm font-medium text-ink-300">
                    {s.filename}
                  </p>
                  <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 md:grid-cols-4">
                    {figs.map((f) => {
                      const active = mandatoryIds.has(f.id);
                      return (
                        <button
                          key={f.id}
                          type="button"
                          onClick={() => toggleMandatory(f.id)}
                          title={f.caption ?? undefined}
                          className={`group relative overflow-hidden rounded-lg border text-left transition ${
                            active
                              ? "border-emerald-500 ring-2 ring-emerald-500/40"
                              : "border-ink-800/60 hover:border-ink-600"
                          }`}
                        >
                          <img
                            src={api.figureUrl(id, f.rel_path)}
                            alt={`p.${f.page}`}
                            loading="lazy"
                            className="h-28 w-full bg-ink-950 object-contain"
                          />
                          <span className="absolute left-1 top-1 rounded bg-ink-950/80 px-1.5 py-0.5 text-[10px] text-ink-300">
                            p.{f.page}
                          </span>
                          {f.suggested && (
                            <span className="absolute left-1 bottom-1 rounded bg-emerald-500/90 px-1.5 py-0.5 text-[10px] font-medium text-ink-950">
                              Consigliata
                            </span>
                          )}
                          {active && (
                            <span className="absolute right-1 top-1 text-emerald-400">
                              <CheckCircle2 size={18} />
                            </span>
                          )}
                          {f.caption && (
                            <span className="block truncate px-1.5 py-1 text-[10px] text-ink-500">
                              {f.caption}
                            </span>
                          )}
                        </button>
                      );
                    })}
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </section>

      {error && <p className="text-sm text-red-500">{error}</p>}

      <div className="flex flex-wrap items-center justify-end gap-3">
        <button
          className="btn-ghost"
          disabled={saving}
          onClick={() => save(false)}
        >
          {saving ? <Loader2 size={16} className="animate-spin" /> : null}
          Salva
        </button>
        <button
          className="btn-primary"
          disabled={saving}
          onClick={() => save(true)}
        >
          Salva e procedi
          <ArrowRight size={16} />
        </button>
      </div>
    </div>
  );
}
