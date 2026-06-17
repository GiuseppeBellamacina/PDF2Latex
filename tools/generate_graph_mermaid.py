"""Generate a Mermaid diagram of the PDF2LaTeX LangGraph pipeline.

Usage:  uv run python tools/generate_graph_mermaid.py

Writes the Mermaid code to ``graph.md`` at the project root.
"""

from pathlib import Path

from langchain_core.runnables.graph import CurveStyle

from app.agents.graph import build_graph


def main() -> None:
    # Build the compiled graph (same as in production).
    app = build_graph()

    # Extract the underlying StateGraph and draw with xray=True so
    # conditional edges are shown with their routing logic.
    mermaid_code = app.get_graph(xray=True).draw_mermaid(
        curve_style=CurveStyle.BASIS,
    )

    output = Path(__file__).resolve().parents[1] / "docs" / "GRAPH.md"
    output.write_text(
        f"# PDF2LaTeX — Pipeline LangGraph\n\n"
        f"Diagramma generato automaticamente con `get_graph(xray=True).draw_mermaid()`.\n\n"
        f"```mermaid\n{mermaid_code}\n```\n",
        encoding="utf-8",
    )
    print(f"Written {output}")


if __name__ == "__main__":
    main()
