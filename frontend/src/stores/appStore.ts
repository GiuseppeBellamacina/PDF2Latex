import { create } from "zustand";
import { api, type Provider, type ProjectSummary } from "../lib/api";

interface AppState {
  providers: Provider[];
  projects: ProjectSummary[];
  selectedProviderId: number | null;
  loadProviders: () => Promise<void>;
  loadProjects: () => Promise<void>;
  setSelectedProvider: (id: number | null) => void;
}

export const useAppStore = create<AppState>((set) => ({
  providers: [],
  projects: [],
  selectedProviderId: null,
  loadProviders: async () => {
    const providers = await api.listProviders();
    set((s) => ({
      providers,
      selectedProviderId:
        s.selectedProviderId ?? providers.find((p) => p.is_active)?.id ?? null,
    }));
  },
  loadProjects: async () => {
    const projects = await api.listProjects();
    set({ projects });
  },
  setSelectedProvider: (id) => set({ selectedProviderId: id }),
}));
