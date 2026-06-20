// Typed API client for the PDF2LaTeX backend.

export interface Provider {
  id: number;
  name: string;
  provider_type: string;
  base_url: string | null;
  default_model: string | null;
  params: Record<string, unknown> | null;
  is_active: boolean;
  has_api_key: boolean;
}

export interface ProviderInput {
  name: string;
  provider_type: string;
  api_key?: string | null;
  base_url?: string | null;
  default_model?: string | null;
  params?: Record<string, unknown> | null;
  is_active?: boolean;
}

export interface Source {
  id: number;
  filename: string;
  n_pages: number;
  order_index: number;
  source_type: string;
}

export interface Figure {
  id: number;
  source_filename: string | null;
  rel_path: string;
  page: number;
  mandatory: boolean;
  order_index: number;
  caption: string | null;
  score: number | null;
  suggested: boolean | null;
  user_uploaded: boolean | null;
  target_section_title: string | null;
  custom_caption: string | null;
}

export interface Section {
  id: number;
  part_title: string | null;
  title: string;
  order_index: number;
  status: string;
  latex: string | null;
  has_undo: boolean;
  has_source: boolean;
}

export interface Project {
  id: string;
  name: string;
  user_prompt: string | null;
  language: string;
  status: string;
  author: string | null;
  subtitle: string | null;
  abstract: string | null;
  cover_date: string | null;
  structure_hint: string | null;
  extractor_backend: string | null;
  enable_ocr: boolean | null;
  ocr_lang: string | null;
  judge_vision: boolean | null;
  latex_template: string | null;
  writer_use_knowledge: boolean | null;
  research_mode: boolean | null;
  web_tool_ids: number[] | null;
  research_max_queries: number | null;
  web_agent_max_iterations: number | null;
  web_agent_provider_id: number | null;
  web_agent_model: string | null;
  user_sources: { authors: string; title: string; year: string; venue: string }[] | null;
  pipeline_config: Record<string, string> | null;
  output_tex_path: string | null;
  output_pdf_path: string | null;
  error_message: string | null;
  total_sources: number;
  total_sections: number;
  completed_sections: number;
  created_at: string;
  sources: Source[];
  sections: Section[];
  figures: Figure[];
}

export interface ProjectUpdate {
  name?: string;
  user_prompt?: string;
  language?: string;
  author?: string;
  subtitle?: string;
  abstract?: string;
  cover_date?: string;
  structure_hint?: string;
  extractor_backend?: string;
  enable_ocr?: boolean;
  ocr_lang?: string | null;
  judge_vision?: boolean;
  latex_template?: string | null;
  writer_use_knowledge?: boolean;
  research_mode?: boolean;
  web_tool_ids?: number[] | null;
  research_max_queries?: number | null;
  web_agent_max_iterations?: number | null;
  web_agent_provider_id?: number | null;
  web_agent_model?: string | null;
  user_sources?: { authors: string; title: string; year: string; venue: string }[] | null;
  pipeline_config?: Record<string, string>;
  source_order?: number[];
  mandatory_figure_ids?: number[];
  figure_updates?: { id: number; custom_caption?: string; target_section_title?: string }[];
}

export interface Backends {
  hybrid: boolean;
  pymupdf: boolean;
  docling: boolean;
  ocr: boolean;
}

export interface PipelineTool {
  id: string;
  label: string;
  description: string;
  available: boolean;
  install: string | null;
  gpu: boolean;
}

export interface PipelineStage {
  id: string;
  label: string;
  description: string;
  optional: boolean;
  default: string;
  selected: string;
  tools: PipelineTool[];
}

export interface PipelineDescription {
  default: Record<string, string>;
  stages: PipelineStage[];
}

export interface ProjectSummary {
  id: string;
  name: string;
  status: string;
  language: string;
  total_sources: number;
  created_at: string;
}

export interface ProjectFile {
  name: string;
  kind: "main" | "section" | "bib";
  language: "latex" | "bibtex";
  content: string;
  section_id: number | null;
}

export interface ProjectFileSave {
  kind: "main" | "section" | "bib";
  section_id?: number | null;
  content: string;
}

export interface WebTool {
  id: number;
  name: string;
  tool_type: string;
  base_url: string | null;
  params: Record<string, unknown> | null;
  is_active: boolean;
  has_api_key: boolean;
}

export interface WebToolInput {
  name: string;
  tool_type: string;
  api_key?: string | null;
  base_url?: string | null;
  params?: Record<string, unknown> | null;
  is_active?: boolean;
}

export interface LatexTemplate {
  id: string;
  label: string;
  description: string;
}

const BASE = "/api";

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, init);
  if (!res.ok) {
    const text = await res.text().catch(() => "");
    throw new Error(text || `HTTP ${res.status}`);
  }
  return res.json() as Promise<T>;
}

export const api = {
  // Templates
  listTemplates: () => req<LatexTemplate[]>("/templates"),

  // Web Tools
  listWebTools: () => req<WebTool[]>("/webtools"),
  createWebTool: (data: WebToolInput) =>
    req<WebTool>("/webtools", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(data),
    }),
  updateWebTool: (id: number, data: Partial<WebToolInput>) =>
    req<WebTool>(`/webtools/${id}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(data),
    }),
  deleteWebTool: (id: number) =>
    req<{ ok: boolean }>(`/webtools/${id}`, { method: "DELETE" }),

  // Providers
  listProviders: () => req<Provider[]>("/providers"),
  createProvider: (data: ProviderInput) =>
    req<Provider>("/providers", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(data),
    }),
  updateProvider: (id: number, data: Partial<ProviderInput>) =>
    req<Provider>(`/providers/${id}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(data),
    }),
  deleteProvider: (id: number) =>
    req<{ ok: boolean }>(`/providers/${id}`, { method: "DELETE" }),
  testProvider: (data: {
    provider_type: string;
    model: string;
    api_key?: string | null;
    base_url?: string | null;
  }) =>
    req<{
      success: boolean;
      stage?: string;
      error?: string;
      error_type?: string;
      latency_ms?: number;
      model?: string;
      followed_instruction?: boolean;
      response?: string;
      tokens?: { input: number; output: number; total: number } | null;
    }>("/providers/test", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(data),
    }),

  // Projects
  listProjects: () => req<ProjectSummary[]>("/projects"),
  getProject: (id: string) => req<Project>(`/projects/${id}`),
  updateProject: (id: string, data: ProjectUpdate) =>
    req<Project>(`/projects/${id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(data),
    }),
  deleteProject: (id: string) =>
    req<{ ok: boolean }>(`/projects/${id}`, { method: "DELETE" }),
  createProject: (form: FormData) =>
    req<Project>("/projects", { method: "POST", body: form }),
  previewLatex: (id: string) =>
    req<{ latex: string }>(`/projects/${id}/preview`),
  getFiles: (id: string) => req<ProjectFile[]>(`/projects/${id}/files`),
  saveFile: (id: string, data: ProjectFileSave) =>
    req<{ success: boolean; pdf: boolean; log_excerpt: string }>(
      `/projects/${id}/files`,
      {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(data),
      },
    ),
  refineSection: (
    id: string,
    sectionId: number,
    data: { provider_id: number; model?: string; extra_prompt: string },
  ) =>
    req<{
      success: boolean;
      section_id: number;
      latex: string;
      log_excerpt: string;
      can_undo?: boolean;
    }>(`/projects/${id}/sections/${sectionId}/refine`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(data),
    }),
  regenerateSection: (
    id: string,
    sectionId: number,
    data: { provider_id: number; model?: string },
  ) =>
    req<{
      success: boolean;
      section_id: number;
      latex: string;
      log_excerpt: string;
      can_undo?: boolean;
    }>(`/projects/${id}/sections/${sectionId}/regenerate`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(data),
    }),
  undoSection: (id: string, sectionId: number) =>
    req<{
      success: boolean;
      section_id: number;
      latex: string;
      log_excerpt: string;
      can_undo: boolean;
    }>(`/projects/${id}/sections/${sectionId}/undo`, { method: "POST" }),
  recompile: (id: string, data: { provider_id: number; model?: string }) =>
    req<{ success: boolean; pdf: boolean; log_excerpt: string }>(
      `/projects/${id}/recompile`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(data),
      },
    ),
  rejudge: (id: string, data: { provider_id: number; model?: string }) =>
    req<{
      applied: boolean;
      approved: boolean;
      score: number;
      issues: string[];
      summary?: string;
      success: boolean;
      log_excerpt?: string;
    }>(`/projects/${id}/rejudge`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(data),
    }),
  backends: () => req<Backends>("/backends"),
  getPipeline: (projectKey?: string) =>
    req<PipelineDescription>(
      projectKey
        ? `/pipeline?project_key=${encodeURIComponent(projectKey)}`
        : "/pipeline",
    ),

  figureUrl: (projectId: string, relPath: string) => {
    const file = relPath.split("/").pop() ?? relPath;
    return `${BASE}/projects/${projectId}/figures/${file}`;
  },
  // User-uploaded figure management
  uploadUserFigure: (
    projectId: string,
    file: File,
    caption: string,
    targetSectionTitle: string,
  ): Promise<Project> => {
    const form = new FormData();
    form.append("file", file);
    form.append("caption", caption);
    form.append("target_section_title", targetSectionTitle);
    return req<Project>(`/projects/${projectId}/figures/upload`, {
      method: "POST",
      body: form,
    });
  },
  updateUserFigure: (
    projectId: string,
    figureId: number,
    data: { custom_caption?: string; target_section_title?: string },
  ): Promise<Project> =>
    req<Project>(`/projects/${projectId}/figures/${figureId}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(data),
    }),
  deleteUserFigure: (projectId: string, figureId: number): Promise<Project> =>
    req<Project>(`/projects/${projectId}/figures/${figureId}`, {
      method: "DELETE",
    }),
  downloadUrl: (id: string, kind: "tex" | "pdf") =>
    `${BASE}/projects/${id}/download/${kind}`,
  // Inline PDF URL for in-browser preview (served with Content-Disposition: inline).
  viewPdfUrl: (id: string) => `${BASE}/projects/${id}/view/pdf`,
};
