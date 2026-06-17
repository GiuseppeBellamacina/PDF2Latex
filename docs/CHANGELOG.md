# CHANGELOG — Sessione 2025-06-18

## 🐛 Bug Fix

### Event loop bloccato durante l'upload PDF

**File**: `backend/app/api/routes.py`

Il metodo `create_project` eseguiva `pdf_page_count()` e `extract_figures()` in modo sincrono
dentro un endpoint `async def`, bloccando l'event loop di FastAPI. La richiesta POST rimaneva
in attesa fino al timeout, impedendo la navigazione alla pagina successiva.

**Fix**: wrapping con `await run_in_threadpool()` da `fastapi.concurrency`:

```python
from fastapi.concurrency import run_in_threadpool

# Prima (bloccante):
#   n_pages = pdf_page_count(target)
#   extract_figures(target, figures_dir)

# Dopo (non bloccante):
n_pages = await run_in_threadpool(pdf_page_count, target)
await run_in_threadpool(extract_figures, target, figures_dir)
```

---

## 🚀 Nuove funzionalità

### 1. Generazione basata su ricerca web (Research Mode)

L'utente può generare documenti LaTeX **senza caricare PDF**: il sistema ricerca l'argomento
online, sintetizza i risultati, e li inserisce nella pipeline esistente. I due flussi
(PDF + ricerca web) possono anche **lavorare insieme**.

**Nuovi file**:
- `backend/app/services/web_search.py` — Adapter per Tavily, Perplexity, Wikipedia (gratis, no API key), custom HTTPX
- `backend/app/agents/researcher.py` — Pipeline STORM-style: prospettive diverse → query → ricerca → fetch → sintesi

**File modificati**:
- `backend/app/db/models.py` — `WebToolConfig` model + campi `research_mode`/`web_tool_id` su `Project`
- `backend/app/api/schemas.py` — Schemi `WebToolCreate/Update/Out`, campi research in `ProjectUpdate`
- `backend/app/agents/state.py` — Campi `research_mode`, `web_tool_config`, `doc_analyses`, `web_analyses`
- `backend/app/agents/graph.py` — `research_node` (parallelo ad `analyze`), `merge_analyses_node`, routing condizionale da `START`
- `backend/app/services/runner.py` — Salta estrazione se research-only, costruisce `web_tool_config`
- `backend/app/core/config.py` — Settings: `research_max_queries`, `research_fetch_pages`, `research_page_max_chars`
- `backend/app/api/routes.py` — CRUD `/webtools`, `create_project` accetta `research_mode`

**Frontend**:
- `frontend/src/lib/api.ts` — Tipi `WebTool`/`WebToolInput`, metodi CRUD web tools
- `frontend/src/stores/appStore.ts` — Stato `webTools`, `loadWebTools()`
- `frontend/src/pages/SettingsPage.tsx` — Sezione "Web search tools" con form e hint per tipo
- `frontend/src/pages/UploadPage.tsx` — Toggle Research mode, selettore web tool
- `frontend/src/components/PipelineGraph.tsx` — Nuovi nodi **Research** e **Merge Sources** nel grafo

### 2. Caricamento immagini extra con didascalia e posizione

L'utente può caricare immagini proprie (non estratte dai PDF), specificare la sezione target
e la didascalia. Le immagini vengono inserite automaticamente nella sezione giusta durante
la generazione.

**File modificati**:
- `backend/app/db/models.py` — Figura: campi `user_uploaded`, `target_section_title`, `custom_caption`
- `backend/app/api/schemas.py` — `FigureOut` esteso con nuovi campi
- `backend/app/api/routes.py` — `POST /projects/{key}/figures/upload`, `DELETE /projects/{key}/figures/{figure_id}`
- `backend/app/services/runner.py` — Costruisce `user_figure_placements` e lo passa alla pipeline
- `backend/app/agents/graph.py` — `write_node`: abbina figure utente alle sezioni per titolo. Fallback per figure senza match
- `frontend/src/lib/api.ts` — `uploadUserFigure`/`deleteUserFigure` API methods
- `frontend/src/components/configure/FiguresPanel.tsx` — Sezione "Your images" con form upload + griglia + elimina
- `frontend/src/pages/ConfigurePage.tsx` — Refresh dopo upload/delete, lista `userUploadedFigures`

### 3. Effetto spark/burst nel grafo della pipeline

Quando una particella raggiunge il nodo di destinazione, un effetto scintilla si attiva:
un flash centrale bianco + 6 scintille direzionali che si espandono radialmente.

**File modificati**:
- `frontend/src/index.css` — 7 keyframe (`spark-0`…`spark-300` + `spark-flash`), classi `.animate-spark-*`
- `frontend/src/components/PipelineGraph.tsx` — `<g>` burst al centro del nodo destinazione, 3 gruppi sfalsati (0s/0.6s/1.2s)

### 4. Grafo interattivo della pipeline

Il `PipelineGraph` ora include:
- **Particelle animate** lungo gli archi attivi (effetto data-flow con `offset-path`)
- **Tooltip al passaggio del mouse** con dettagli per-nodo (documenti analizzati, topic, sezioni scritte, errori)
- **Pannello dettaglio al click** con struttura completa (es. Write → progress bar capitoli, Review → log compilazione)

**File modificato**: `frontend/src/components/PipelineGraph.tsx`

### 5. Heatmap degli stati dei nodi nella barra di progresso

Mini-segmenti colorati sotto la barra di progresso principale che rappresentano
lo stato di ogni nodo della pipeline (pending/active/completed/error).
Cliccabili per navigare al pannello dettaglio con switch automatico alla vista grafo.

**File modificati**:
- `frontend/src/components/ProgressTimeline.tsx` — Heatmap segmenti + `onNodeClick` prop
- `frontend/src/pages/GeneratePage.tsx` — Callback `setSelectedNode` + `setView("graph")`

---

## 🎨 UI / Branding

### Favicon personalizzato

**File**: `frontend/public/favicon.svg`

- Sostituito il favicon precedente con un SVG a tema scuro
- Sfondo indaco scuro arrotondato (`#1e1b4b` → `#0f0d2e`)
- Due blocchi diagonali sovrapposti (viola/blu) che simboleggiano la trasformazione PDF → LaTeX
- Punto luminoso all'intersezione, anello interno sottile
- **Nessun testo**, solo geometria astratta

### Logo SVG nell'header

**File**: `frontend/src/components/Layout.tsx`

- Sostituita l'icona generica `FileText` di Lucide con `<img src="/favicon.svg">`
- Titolo "PDF2LaTeX" mantenuto accanto al logo
- Dimensioni: `h-8 w-8` (32×32px)

---

## 🧪 Test E2E — 6 nuovi test sul grafo LangGraph

**File**: `backend/tests/test_full_graph_e2e.py`

Tutti i nuovi test sono **fully mocked** (nessuna chiamata LLM reale, nessun I/O).

### 1. `test_full_graph_user_sources_merged_and_audited`
> Fonti bibliografiche utente → merge nel `references_pool` → audit citazioni

- 2 fonti utente (He 2016, Vaswani 2017) con `make_key`
- Verifica merge con `source_filename="__user__"` e chiavi corrette
- `audit_citations` mockato per rilevare fonti non citate
- `citation_issues` nel final state, merge riporta "problemi citazioni"

### 2. `test_full_graph_judge_disapproves_then_approves_on_revision`
> Judge disapprova → revisione strutturale → ricompilazione → judge approva

- Primo `judge_structure`: `approved=False`, `score=35`, 2 issue
- `revise_structure` produce LaTeX corretto
- Secondo `judge_structure`: `approved=True`, `score=88`
- `judge_max_iterations` patched a 2
- Verifica: 2 chiamate judge, 1 revise, 2 compilazioni, `judge_rounds=1`, progress "Revisione struttura" e "approvata"

### 3. `test_full_graph_judge_max_iterations_exhausted`
> Judge disapprova due volte consecutive → raggiunto `judge_max_iterations=2` → END

- Judge sempre `approved=False` (`score=30`)
- 2 round completi: disapprove → revise → recompile → disapprove → revise → recompile
- `_after_review` restituisce END quando `judge_rounds=2 >= 2`
- Verifica: 2 chiamate judge, 2 revise, 3 compilazioni, `judge_action="revise"`, nessun messaggio "approvata"

### 4. `test_full_graph_judge_revision_fails_rollback_to_good`
> Revisione del judge non compila → rollback a `good_latex`/`good_pdf`

- Compilazione iniziale: successo → salva `good_latex`/`good_pdf`
- `revise_structure` produce LaTeX con `\badcommand`
- Tutti i tentativi di compilazione della revisione falliscono (3 tentativi: 1 + 2 retry)
- Rollback: `final_latex` torna alla versione buona, `pdf_path` preservato
- Verifica: progress "Revisione strutturale scartata", `review_document` 2×, compile 4×

### 5. `test_full_graph_coherence_and_citations_disabled`
> `coherence_enabled=False` e `citations_enabled=False` → nodi restituiscono `{}`

- `check_coherence` e `audit_citations`: `assert_not_called()`
- Nessuna chiave coherence/citation nel final state
- Nessun evento progress coherence/citation
- Merge: solo "Verifiche completate" (nessun problema)
- Grafo completa comunque: `judge_action="approve"`, PDF prodotto

### 6. `test_full_graph_judge_disabled_terminates_after_review`
> `judge_enabled=False` → `_after_review` restituisce END direttamente

- `judge_structure`: `assert_not_called()`
- Nessuna chiave `judge_action`/`judge_score`/`judge_rounds` nel final state
- Nessun evento progress "judging"
- Grafo completa: PDF prodotto, tutti gli stage core presenti
- Fan-out diamond (coherence/citations) non influenzato

---

## 🧹 Lint & Formattazione

**Tutti i file backend**:

- `ruff check --fix .` → 35 fix automatici applicati
- `ruff format .` → 16 file riformattati
- 9 warning rimanenti corretti manualmente:
  - `test_diamond_merge.py`: 3 variabili non usate
  - `test_full_graph_e2e.py`: 4 variabili non usate + 1 import ridondante
  - `test_writer_context.py`: 1 variabile non usata
- **Risultato finale**: 0 errori ruff, 0 file da riformattare

---

## 📊 Riepilogo finale

| Categoria | Dettaglio |
|-----------|-----------|
| Bug fix | 1 (event loop bloccato) |
| Nuove funzionalità | 5 (research mode, user images, spark effects, interactive graph, heatmap) |
| UI/Branding | 2 (favicon SVG, logo header) |
| Test E2E aggiunti | 6 |
| Totale test suite | **130 passed, 1 skipped, 0 failed** |
| File backend creati | 2 (`web_search.py`, `researcher.py`) |
| File backend modificati | 8 (`models.py`, `schemas.py`, `routes.py`, `state.py`, `graph.py`, `runner.py`, `config.py`, `writer.py`) |
| File frontend modificati | 7 (`api.ts`, `appStore.ts`, `SettingsPage.tsx`, `UploadPage.tsx`, `PipelineGraph.tsx`, `ProgressTimeline.tsx`, `FiguresPanel.tsx`, `ConfigurePage.tsx`, `index.css`, `Layout.tsx`) |
