"""Generate a combined Mermaid diagram of the pipeline + web_agent subgraph.

Usage:  uv run python tools/generate_graph_mermaid.py

Reads the graph structure programmatically from both the main pipeline and
the web_agent subgraph, then builds a single Mermaid diagram where the
``research`` node is expanded into its internal subgraph.

Writes the Mermaid code to ``docs/GRAPH.md``.
"""

from pathlib import Path

from app.agents.graph import build_graph
from app.agents.web_agent import build_web_agent_graph


def _combined_mermaid() -> str:
    """Build a combined Mermaid diagram with the web_agent subgraph expanded."""
    app = build_graph()
    g = app.get_graph(xray=True)

    web_app = build_web_agent_graph()
    wg = web_app.get_graph(xray=True)

    lines: list[str] = []
    _L = lines.append

    # ── Front matter ────────────────────────────────────────────────────
    _L("---")
    _L("config:")
    _L("  flowchart:")
    _L("    curve: basis")
    _L("---")
    _L("graph TD;")
    _L("")

    # ── Classes ─────────────────────────────────────────────────────────
    _L("\tclassDef default fill:#f2f0ff,line-height:1.2")
    _L("\tclassDef first fill-opacity:0")
    _L("\tclassDef last fill:#bfb6fc")
    _L("")

    # ── Main pipeline nodes (skip start / end / research) ───────────────
    for nid, node in g.nodes.items():
        if nid in ("__start__", "__end__", "research"):
            continue
        _L(f'\t{nid}("{node.name}")')
    _L("")

    # ── research subgraph (web_agent internal) ──────────────────────────
    _L('\tsubgraph research["📡 research (web_agent)"]')
    for nid, node in wg.nodes.items():
        if nid in ("__start__", "__end__"):
            continue
        _L(f'\t\t{nid}["{node.name}"]')
    # Evaluator exit → annotate the edge that leaves the subgraph
    _L("\t\tevaluator -.-> |completed| _done_((done))")
    _L("\tend")
    _L("")

    # ── Special nodes ──────────────────────────────────────────────────
    _L('\t__start__(["start"]):::first')
    _L('\t__end__(["end"]):::last')
    _L("")

    # ── Main graph edges (excluding start/end) ──────────────────────────
    for e in g.edges:
        arrow = "-.->" if e.conditional else "-->"
        if e.source == "__start__":
            _L(f"\t__start__ {arrow} {e.target}")
            continue
        if e.target == "__end__":
            _L(f"\t{e.source} {arrow} __end__")
            continue
        if e.source == "research" and e.target != "__end__":
            _L(f"\tresearch {arrow} {e.target}")
            continue
        _L(f"\t{e.source} {arrow} {e.target}")
    _L("")

    # ── Web agent internal edges ────────────────────────────────────────
    _wa_labels: dict[tuple[str, str], str] = {
        ("evaluator", "planner"): "revise",
    }
    for e in wg.edges:
        if e.source in ("__start__", "__end__") or e.target in ("__end__",):
            continue
        # Evaluator → done (already drawn as _done_ inside subgraph)
        if e.source == "evaluator" and e.target == "__end__":
            continue
        arrow = "-.->" if e.conditional else "-->"
        label = _wa_labels.get((e.source, e.target), "")
        if label:
            _L(f"\t{e.source} {arrow} |{label}| {e.target}")
        else:
            _L(f"\t{e.source} {arrow} {e.target}")

    return "\n".join(lines)


def _write_diagram(code: str) -> None:
    output = Path(__file__).resolve().parents[1] / "docs" / "GRAPH.md"
    header = (
        "# PDF2LaTeX — Pipeline LangGraph\n\n"
        "Il diagramma combina il flusso principale con il subgraph "
        "di **research (web_agent)** estratto programmaticamente "
        "da `get_graph(xray=True)`.\n\n"
        "```mermaid\n"
    )
    footer = "\n```\n"
    output.write_text(header + code + footer, encoding="utf-8")
    print(f"Written {output}")


def main() -> None:
    code = _combined_mermaid()
    _write_diagram(code)


if __name__ == "__main__":
    main()
