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
}

export interface Section {
  id: number;
  part_title: string | null;
  title: string;
  order_index: number;
  status: string;
  latex: string | null;
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
  source_order?: number[];
  mandatory_figure_ids?: number[];
}

export interface Backends {
  hybrid: boolean;
  pymupdf: boolean;
  docling: boolean;
  ocr: boolean;
}

export interface ProjectSummary {
  id: string;
  name: string;
  status: string;
  language: string;
  total_sources: number;
  created_at: string;
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
    req<{ success: boolean; response?: string; error?: string }>(
      "/providers/test",
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(data),
      },
    ),

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
  backends: () => req<Backends>("/backends"),

  figureUrl: (projectId: string, relPath: string) => {
    const file = relPath.split("/").pop() ?? relPath;
    return `${BASE}/projects/${projectId}/figures/${file}`;
  },
  downloadUrl: (id: string, kind: "tex" | "pdf") =>
    `${BASE}/projects/${id}/download/${kind}`,
};
