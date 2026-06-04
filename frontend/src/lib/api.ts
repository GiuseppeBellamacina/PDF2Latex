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

export interface Section {
  id: number;
  part_title: string | null;
  title: string;
  order_index: number;
  status: string;
  latex: string | null;
}

export interface Project {
  id: number;
  name: string;
  user_prompt: string | null;
  language: string;
  status: string;
  output_tex_path: string | null;
  output_pdf_path: string | null;
  error_message: string | null;
  total_sources: number;
  total_sections: number;
  completed_sections: number;
  created_at: string;
  sources: Source[];
  sections: Section[];
}

export interface ProjectSummary {
  id: number;
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
  getProject: (id: number) => req<Project>(`/projects/${id}`),
  deleteProject: (id: number) =>
    req<{ ok: boolean }>(`/projects/${id}`, { method: "DELETE" }),
  createProject: (form: FormData) =>
    req<Project>("/projects", { method: "POST", body: form }),
  previewLatex: (id: number) =>
    req<{ latex: string }>(`/projects/${id}/preview`),

  downloadUrl: (id: number, kind: "tex" | "pdf") =>
    `${BASE}/projects/${id}/download/${kind}`,
};
