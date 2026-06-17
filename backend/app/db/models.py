"""SQLAlchemy ORM models for the PDF -> LaTeX generator."""

import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import DeclarativeBase, relationship


class Base(DeclarativeBase):
    pass


class ProjectStatus(str, enum.Enum):
    uploaded = "uploaded"
    analyzing = "analyzing"
    planning = "planning"
    writing = "writing"
    reviewing = "reviewing"
    compiling = "compiling"
    completed = "completed"
    failed = "failed"


class SectionStatus(str, enum.Enum):
    pending = "pending"
    writing = "writing"
    reviewing = "reviewing"
    completed = "completed"
    failed = "failed"


class Project(Base):
    """A generation job: a set of PDFs turned into one LaTeX document."""

    __tablename__ = "projects"

    id = Column(Integer, primary_key=True, autoincrement=True)
    # Opaque public identifier used in URLs (so the API never exposes the
    # sequential integer primary key). Generated once at creation.
    public_id = Column(
        String(32),
        unique=True,
        index=True,
        nullable=False,
        default=lambda: uuid.uuid4().hex,
    )
    name = Column(String(255), nullable=False)
    user_prompt = Column(Text, nullable=True)
    language = Column(String(50), nullable=False, default="italian")
    status = Column(SAEnum(ProjectStatus), default=ProjectStatus.uploaded)

    # Title-page / front-matter metadata
    author = Column(String(255), nullable=True)
    subtitle = Column(String(512), nullable=True)
    abstract = Column(Text, nullable=True)
    cover_date = Column(String(100), nullable=True)

    # Structure / index guidance for the planner
    structure_hint = Column(Text, nullable=True)

    # Optional per-chapter synopsis block rendered right after the TOC. Kept so
    # it survives reassembly on recompile / quick fix / regenerate.
    overview_latex = Column(Text, nullable=True)

    # Bibliography: the BibTeX database (references.bib) shown as an editable
    # file and shipped in the zip, holding only the entries actually cited in
    # the document. ``references_pool`` keeps every reference extracted from the
    # sources (with its citation key) so the cited subset can be recomputed.
    bibliography_bib = Column(Text, nullable=True)
    references_pool = Column(JSON, nullable=True)

    # When the user edits the whole ``main.tex`` from the file editor, the
    # verbatim document is stored here and compiled as-is (bypassing the
    # per-section reassembly). Any structured edit (a section/bib save, refine,
    # regenerate, undo) clears it so reassembly takes over again.
    main_tex_override = Column(Text, nullable=True)

    # Extraction configuration
    extractor_backend = Column(String(50), nullable=True)  # pymupdf|docling
    enable_ocr = Column(Boolean, default=False)
    # Per-project OCR language (e.g. "ita+eng", "eng", "fra"). When left empty,
    # the global ``settings.ocr_lang`` is used as fallback.
    ocr_lang = Column(String(50), nullable=True)
    # Composable extraction pipeline: a mapping {stage_id: tool_id} built in the
    # dashboard. When set it supersedes ``extractor_backend`` (which is kept as a
    # legacy fallback for older projects).
    pipeline_config = Column(JSON, nullable=True)
    # LaTeX document template (default | paper | thesis-oneside | thesis-twoside).
    latex_template = Column(String(50), default="default")
    # Optional vision judge (needs a multimodal model). Off by default.
    judge_vision = Column(Boolean, default=False)
    # Let the writer LLM supplement source material with its own knowledge
    # when the extracted text is insufficient on a topic.
    writer_use_knowledge = Column(Boolean, default=False)

    # User-provided bibliographic sources the system should cite and optionally
    # use to enrich the document. Stored as a JSON array of dicts with keys
    # ``authors``, ``title``, ``year``, ``venue``.
    user_sources = Column(JSON, nullable=True)

    # ── Research-based generation (no PDFs needed) ───────────────────────
    # When True, the pipeline researches the topic online before writing,
    # using the web tool configured in ``web_tool_id``. Works alongside
    # uploaded PDFs (research supplements the extracted content).
    research_mode = Column(Boolean, default=False)
    web_tool_id = Column(Integer, ForeignKey("web_tools.id"), nullable=True)

    output_tex_path = Column(String(512), nullable=True)
    output_pdf_path = Column(String(512), nullable=True)
    error_message = Column(Text, nullable=True)

    total_sources = Column(Integer, default=0)
    total_sections = Column(Integer, default=0)
    completed_sections = Column(Integer, default=0)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    sources = relationship(
        "Source", back_populates="project", cascade="all, delete-orphan"
    )
    sections = relationship(
        "Section", back_populates="project", cascade="all, delete-orphan"
    )
    figures = relationship(
        "Figure", back_populates="project", cascade="all, delete-orphan"
    )


class Source(Base):
    """An uploaded PDF belonging to a project."""

    __tablename__ = "sources"

    id = Column(Integer, primary_key=True, autoincrement=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False)
    filename = Column(String(255), nullable=False)
    path = Column(String(512), nullable=False)
    n_pages = Column(Integer, default=0)
    order_index = Column(Integer, default=0)

    project = relationship("Project", back_populates="sources")


class Figure(Base):
    """An embedded figure — extracted from a source PDF or uploaded by the user."""

    __tablename__ = "figures"

    id = Column(Integer, primary_key=True, autoincrement=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False)
    source_id = Column(Integer, ForeignKey("sources.id"), nullable=True)
    source_filename = Column(String(255), nullable=True)
    rel_path = Column(String(512), nullable=False)  # e.g. "figures/fig_xxx.png"
    page = Column(Integer, default=0)
    mandatory = Column(Boolean, default=False)
    order_index = Column(Integer, default=0)
    # OCR-derived caption + heuristic "worth including" recommendation.
    caption = Column(Text, nullable=True)
    score = Column(Float, default=0.0)
    suggested = Column(Boolean, default=False)
    # ── User-uploaded figure fields ───────────────────────────────────
    # True when the image was uploaded by the user (not extracted from a PDF).
    user_uploaded = Column(Boolean, default=False)
    # Section title (or part_title — title) the user wants this figure placed in.
    target_section_title = Column(String(512), nullable=True)
    # Override caption specified by the user (takes priority over OCR caption).
    custom_caption = Column(Text, nullable=True)

    project = relationship("Project", back_populates="figures")


class Section(Base):
    """A planned section of the output document, with its generated LaTeX."""

    __tablename__ = "sections"

    id = Column(Integer, primary_key=True, autoincrement=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False)
    part_title = Column(String(255), nullable=True)
    title = Column(String(255), nullable=False)
    order_index = Column(Integer, default=0)
    outline = Column(JSON, nullable=True)
    # Source PDFs this section draws from (used to regenerate it from scratch).
    source_filenames = Column(JSON, nullable=True)
    latex = Column(Text, nullable=True)
    # Previous LaTeX kept so a quick fix / regenerate can be undone.
    previous_latex = Column(Text, nullable=True)
    status = Column(SAEnum(SectionStatus), default=SectionStatus.pending)

    project = relationship("Project", back_populates="sections")

    @property
    def has_undo(self) -> bool:
        """True when a previous LaTeX version is stored (a fix can be undone)."""
        return bool(self.previous_latex)

    @property
    def has_source(self) -> bool:
        """True when the source filenames are known (can regenerate from source)."""
        return bool(self.source_filenames)


class ProviderConfig(Base):
    """A configured LLM provider. API keys are stored encrypted."""

    __tablename__ = "provider_configs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(100), nullable=False, unique=True)
    provider_type = Column(
        String(50), nullable=False
    )  # openai|anthropic|ollama|custom|fake
    api_key_encrypted = Column(Text, nullable=True)
    base_url = Column(String(512), nullable=True)
    default_model = Column(String(100), nullable=True)
    params = Column(JSON, nullable=True)  # temperature, max_tokens, top_p, etc.
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class WebToolConfig(Base):
    """A configured web search/research tool (Tavily, Perplexity, Wikipedia, etc.).

    API keys are stored encrypted, mirroring the ``ProviderConfig`` design.
    """

    __tablename__ = "web_tools"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(100), nullable=False, unique=True)
    tool_type = Column(
        String(50), nullable=False
    )  # tavily|perplexity|wikipedia|custom_httpx
    api_key_encrypted = Column(Text, nullable=True)
    base_url = Column(String(512), nullable=True)
    params = Column(JSON, nullable=True)  # max_results, search_depth, language, etc.
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
