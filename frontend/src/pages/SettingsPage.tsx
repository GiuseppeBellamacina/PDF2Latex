import {
  AlertTriangle,
  Check,
  ChevronDown,
  Clock,
  Cpu,
  Globe,
  Pencil,
  Plus,
  Search,
  Trash2,
  X,
  Zap,
} from "lucide-react";
import { useEffect, useRef, useState } from "react";
import {
  api,
  type Provider,
  type ProviderInput,
  type WebToolInput,
} from "../lib/api";
import { cn } from "../lib/utils";
import { PROVIDER_COLORS, PROVIDER_ICONS } from "../lib/providerIcons";
import { useAppStore } from "../stores/appStore";

type TestResult = Awaited<ReturnType<typeof api.testProvider>>;

const PROVIDER_TYPES = [
  "openai",
  "anthropic",
  "ollama",
  "custom",
  "fake",
  "deepseek",
  "nvidia",
  "openrouter",
  "grok",
  "alibaba",
  "together",
  "groq",
  "mistral",
] as const;
const WEB_TOOL_TYPES = ["tavily", "perplexity", "arxiv"] as const;

const KNOWN_MODELS: Record<string, string[]> = {
  openai: [
    "gpt-4o",
    "gpt-4o-mini",
    "gpt-4-turbo",
    "gpt-4",
    "gpt-3.5-turbo",
    "o1",
    "o1-mini",
    "o3-mini",
  ],
  anthropic: [
    "claude-3-5-sonnet-20241022",
    "claude-3-opus-20240229",
    "claude-3-haiku-20240307",
    "claude-3-sonnet-20240229",
  ],
  ollama: ["llama3", "llama3.1", "mistral", "codellama", "gemma2", "phi3"],
  custom: [],
  fake: [],
  deepseek: ["deepseek-chat", "deepseek-reasoner"],
  nvidia: [
    "meta/llama-3.3-70b-instruct",
    "nvidia/llama-3.1-nemotron-70b-instruct",
    "mistralai/mistral-large",
  ],
  openrouter: [
    "openai/gpt-4o",
    "anthropic/claude-3.5-sonnet",
    "google/gemini-2.0-flash",
    "meta-llama/llama-3.3-70b-instruct",
  ],
  grok: ["grok-2", "grok-2-vision"],
  alibaba: ["qwen-max", "qwen-plus", "qwen-turbo", "qwen-vl-max"],
  together: [
    "meta-llama/Llama-3.3-70B-Instruct-Turbo",
    "mistralai/Mixtral-8x7B-Instruct-v0.1",
    "Qwen/Qwen2.5-72B-Instruct",
  ],
  groq: [
    "llama-3.3-70b-versatile",
    "mixtral-8x7b-32768",
    "gemma2-9b-it",
    "deepseek-r1-distill-llama-70b",
  ],
  mistral: [
    "mistral-large-latest",
    "mistral-medium-latest",
    "mistral-small-latest",
    "codestral-latest",
  ],
};

const DEFAULT_BASE_URLS: Record<string, string> = {
  deepseek: "https://api.deepseek.com/v1",
  nvidia: "https://integrate.api.nvidia.com/v1",
  openrouter: "https://openrouter.ai/api/v1",
  grok: "https://api.x.ai/v1",
  alibaba: "https://dashscope-intl.aliyuncs.com/compatible-mode/v1",
  together: "https://api.together.xyz/v1",
  groq: "https://api.groq.com/openai/v1",
  mistral: "https://api.mistral.ai/v1",
};

const WEBTOOL_HINTS: Record<string, string> = {
  tavily: "https://tavily.com — API key required",
  perplexity: "https://docs.perplexity.ai — API key required",
  arxiv: "https://arxiv.org — No API key needed (academic paper search)",
};

const EMPTY: ProviderInput = {
  name: "",
  provider_type: "openai",
  api_key: "",
  base_url: "",
  default_model: "",
  is_active: true,
};

const EMPTY_WEBTOOL: WebToolInput = {
  name: "",
  tool_type: "tavily",
  api_key: "",
  base_url: "",
  is_active: true,
};

export default function SettingsPage() {
  const { providers, webTools, loadProviders, loadWebTools } = useAppStore();
  const [form, setForm] = useState<ProviderInput>(EMPTY);
  const [webToolForm, setWebToolForm] = useState<WebToolInput>(EMPTY_WEBTOOL);
  const [testResult, setTestResult] = useState<TestResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [editingId, setEditingId] = useState<number | null>(null);
  const [editForm, setEditForm] = useState<ProviderInput>(EMPTY);
  const [modelOpen, setModelOpen] = useState(false);
  const modelDropdownRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    loadProviders();
    loadWebTools();
  }, [loadProviders, loadWebTools]);

  // Close model dropdown on outside click
  useEffect(() => {
    if (!modelOpen) return;
    function handleClick(e: MouseEvent) {
      if (
        modelDropdownRef.current &&
        !modelDropdownRef.current.contains(e.target as Node)
      ) {
        setModelOpen(false);
      }
    }
    document.addEventListener("mousedown", handleClick);
    return () => document.removeEventListener("mousedown", handleClick);
  }, [modelOpen]);

  // All providers need an API key except local Ollama and offline Fake.
  const needsKey =
    form.provider_type !== "ollama" && form.provider_type !== "fake";
  // Providers that don't have a hardcoded SDK default need a base_url.
  const needsUrl =
    form.provider_type !== "openai" &&
    form.provider_type !== "anthropic" &&
    form.provider_type !== "fake";
  const typeModels = KNOWN_MODELS[form.provider_type] ?? [];
  const hasKnownModels = typeModels.length > 0;

  async function create() {
    setBusy(true);
    try {
      await api.createProvider(form);
      setForm(EMPTY);
      setTestResult(null);
      loadProviders();
    } finally {
      setBusy(false);
    }
  }

  async function test() {
    setBusy(true);
    setTestResult(null);
    try {
      const r = await api.testProvider({
        provider_type: form.provider_type,
        model: form.default_model || typeModels[0] || "gpt-4o-mini",
        api_key: form.api_key,
        base_url: form.base_url,
      });
      setTestResult(r);
    } finally {
      setBusy(false);
    }
  }

  async function remove(p: Provider) {
    await api.deleteProvider(p.id);
    loadProviders();
  }

  function startEditing(p: Provider) {
    setEditingId(p.id);
    setEditForm({
      name: p.name,
      provider_type: p.provider_type,
      api_key: "",
      base_url: p.base_url ?? "",
      default_model: p.default_model ?? "",
      is_active: p.is_active,
    });
  }

  async function saveEdit() {
    if (editingId == null) return;
    setBusy(true);
    try {
      const { api_key, ...rest } = editForm;
      const payload: Partial<ProviderInput> = {
        ...rest,
        ...(api_key ? { api_key } : {}),
      };
      await api.updateProvider(editingId, payload);
      setEditingId(null);
      loadProviders();
    } finally {
      setBusy(false);
    }
  }

  async function toggleActive(p: Provider) {
    await api.updateProvider(p.id, { is_active: !p.is_active });
    loadProviders();
  }

  // ── Web tool CRUD ─────────────────────────────────────────────────────
  async function createWeb() {
    setBusy(true);
    try {
      await api.createWebTool(webToolForm);
      setWebToolForm(EMPTY_WEBTOOL);
      loadWebTools();
    } finally {
      setBusy(false);
    }
  }

  async function removeWebTool(id: number) {
    await api.deleteWebTool(id);
    loadWebTools();
  }

  return (
    <div className="space-y-10">
      {/* ── LLM Providers ─────────────────────────────────────────────── */}
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">LLM Providers</h1>
        <p className="mt-1 text-sm text-ink-500">
          API keys are stored encrypted. Use{" "}
          <em className="font-mono text-ink-400">fake</em> to try it offline.
        </p>
      </div>

      {/* Provider form card */}
      <div className="card space-y-5">
        <h2 className="flex items-center gap-2 text-sm font-semibold">
          <Plus size={15} className="text-emerald-500" />
          New provider
        </h2>

        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <div>
            <label className="mb-1 block text-xs font-medium text-ink-500">
              Name
            </label>
            <input
              className="input"
              value={form.name}
              onChange={(e) => setForm({ ...form, name: e.target.value })}
              placeholder="e.g. Main OpenAI"
            />
          </div>
          <div>
            <label className="mb-1 block text-xs font-medium text-ink-500">
              Type
            </label>
            <ProviderTypeSelect
              value={form.provider_type}
              onChange={(t) => {
                const defaultUrl = DEFAULT_BASE_URLS[t] ?? "";
                setForm({
                  ...form,
                  provider_type: t,
                  default_model: "",
                  base_url: defaultUrl,
                });
                setModelOpen(false);
              }}
            />
          </div>

          {/* Model combobox */}
          <div ref={modelDropdownRef} className="relative">
            <label className="mb-1 block text-xs font-medium text-ink-500">
              Default model
              {hasKnownModels && (
                <span className="ml-1 text-ink-400">
                  — click for suggestions
                </span>
              )}
            </label>
            <div className="relative">
              <input
                className="input w-full pr-8"
                value={form.default_model ?? ""}
                onChange={(e) =>
                  setForm({ ...form, default_model: e.target.value })
                }
                onClick={() =>
                  hasKnownModels && !modelOpen && setModelOpen(true)
                }
                placeholder={
                  hasKnownModels
                    ? `e.g. ${typeModels[0]}`
                    : "gpt-4o-mini / claude-3-5-sonnet / llama3"
                }
              />
              {hasKnownModels && (
                <button
                  type="button"
                  className="absolute right-2 top-1/2 -translate-y-1/2 p-0.5 text-ink-400 hover:text-ink-600"
                  onClick={() => setModelOpen((o) => !o)}
                  tabIndex={-1}
                >
                  <ChevronDown
                    size={16}
                    className={cn(
                      "transition-transform",
                      modelOpen && "rotate-180",
                    )}
                  />
                </button>
              )}
            </div>
            {modelOpen && hasKnownModels && (
              <div className="absolute z-20 mt-1 w-full rounded-xl border border-ink-200 bg-white py-1 shadow-lg dark:border-ink-700 dark:bg-ink-900">
                {typeModels.map((m) => {
                  const isRecommended = m === typeModels[0];
                  return (
                    <button
                      key={m}
                      type="button"
                      className="flex w-full items-center gap-2 px-3 py-2 text-left text-sm transition-colors hover:bg-ink-50 dark:hover:bg-ink-800"
                      onClick={() => {
                        setForm({ ...form, default_model: m });
                        setModelOpen(false);
                      }}
                    >
                      <span className="truncate">{m}</span>
                      {isRecommended && (
                        <span className="shrink-0 rounded-full bg-emerald-100 px-1.5 py-0.5 text-[10px] font-medium text-emerald-700 dark:bg-emerald-900/40 dark:text-emerald-300">
                          recommended
                        </span>
                      )}
                    </button>
                  );
                })}
              </div>
            )}
          </div>

          {needsUrl && (
            <div>
              <label className="mb-1 block text-xs font-medium text-ink-500">
                Base URL
              </label>
              <input
                className="input"
                value={form.base_url ?? ""}
                onChange={(e) => setForm({ ...form, base_url: e.target.value })}
                placeholder="http://localhost:11434"
              />
            </div>
          )}
          {needsKey && (
            <div className={needsUrl ? "" : "sm:col-span-2"}>
              <label className="mb-1 block text-xs font-medium text-ink-500">
                API Key
              </label>
              <input
                type="password"
                className="input"
                value={form.api_key ?? ""}
                onChange={(e) => setForm({ ...form, api_key: e.target.value })}
                placeholder="sk-…"
              />
            </div>
          )}
        </div>

        {testResult && <TestResultCard result={testResult} />}

        <div className="flex gap-2">
          <button className="btn-ghost" onClick={test} disabled={busy}>
            <Zap size={16} /> Test connection
          </button>
          <button
            className="btn-primary"
            onClick={create}
            disabled={busy || !form.name.trim()}
          >
            <Plus size={16} /> Add provider
          </button>
        </div>
      </div>

      {/* Provider list */}
      <div className="space-y-2">
        {providers.length === 0 && (
          <p className="rounded-xl border border-dashed border-ink-200 px-4 py-8 text-center text-sm text-ink-400 dark:border-ink-800">
            No providers yet. Add one to start.
          </p>
        )}
        {providers.map((p) => {
          const Icon = PROVIDER_ICONS[p.provider_type] ?? Cpu;
          const iconBg = PROVIDER_COLORS[p.provider_type] ?? "";
          const isEditing = editingId === p.id;

          if (isEditing) {
            return (
              <div
                key={p.id}
                className="rounded-xl border-2 border-emerald-400 bg-emerald-50/20 p-4 dark:border-emerald-600 dark:bg-emerald-950/10"
              >
                <div className="mb-3 flex items-center gap-2 text-xs font-medium text-emerald-600 dark:text-emerald-400">
                  <Pencil size={13} /> Editing {p.name}
                </div>
                <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                  <div>
                    <label className="mb-1 block text-xs font-medium text-ink-500">
                      Name
                    </label>
                    <input
                      className="input text-sm"
                      value={editForm.name}
                      onChange={(e) =>
                        setEditForm({ ...editForm, name: e.target.value })
                      }
                    />
                  </div>
                  <div>
                    <label className="mb-1 block text-xs font-medium text-ink-500">
                      Default model
                    </label>
                    <input
                      className="input text-sm"
                      value={editForm.default_model ?? ""}
                      onChange={(e) =>
                        setEditForm({
                          ...editForm,
                          default_model: e.target.value,
                        })
                      }
                    />
                  </div>
                  {p.provider_type !== "openai" &&
                    p.provider_type !== "anthropic" &&
                    p.provider_type !== "fake" && (
                      <div>
                        <label className="mb-1 block text-xs font-medium text-ink-500">
                          Base URL
                        </label>
                        <input
                          className="input text-sm"
                          value={editForm.base_url ?? ""}
                          onChange={(e) =>
                            setEditForm({
                              ...editForm,
                              base_url: e.target.value,
                            })
                          }
                        />
                      </div>
                    )}
                  <div>
                    <label className="mb-1 block text-xs font-medium text-ink-500">
                      New API key{" "}
                      <span className="text-ink-400">
                        (leave empty to keep current)
                      </span>
                    </label>
                    <input
                      type="password"
                      className="input text-sm"
                      value={editForm.api_key ?? ""}
                      onChange={(e) =>
                        setEditForm({ ...editForm, api_key: e.target.value })
                      }
                    />
                  </div>
                </div>
                <div className="mt-3 flex gap-2">
                  <button
                    className="btn-primary text-xs"
                    onClick={saveEdit}
                    disabled={busy}
                  >
                    <Check size={14} /> Save
                  </button>
                  <button
                    className="btn-ghost text-xs"
                    onClick={() => setEditingId(null)}
                  >
                    Cancel
                  </button>
                </div>
              </div>
            );
          }

          return (
            <div
              key={p.id}
              className="group flex items-center gap-4 rounded-xl border border-ink-200 bg-white px-4 py-3 transition-shadow hover:shadow-sm dark:border-ink-800 dark:bg-ink-950"
            >
              {/* Provider icon */}
              <div
                className={cn(
                  "flex h-10 w-10 shrink-0 items-center justify-center rounded-lg",
                  iconBg,
                )}
              >
                <Icon size={18} />
              </div>

              {/* Info */}
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2">
                  <p className="truncate text-sm font-semibold">{p.name}</p>
                  <span
                    className={cn(
                      "shrink-0 rounded-full px-2 py-0.5 text-[10px] font-medium",
                      p.is_active
                        ? "bg-emerald-100 text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-400"
                        : "bg-ink-100 text-ink-500 dark:bg-ink-800 dark:text-ink-400",
                    )}
                  >
                    {p.is_active ? "active" : "inactive"}
                  </span>
                </div>
                <p className="text-xs text-ink-500">
                  <span className="capitalize">{p.provider_type}</span>
                  {p.default_model && ` · ${p.default_model}`}
                  {p.base_url && ` · ${p.base_url}`}
                  {p.has_api_key && (
                    <span className="ml-1" title="API key set">
                      · 🔑
                    </span>
                  )}
                </p>
              </div>

              {/* Actions */}
              <div className="flex shrink-0 items-center gap-1">
                <button
                  className="btn-ghost h-8 px-2 text-xs"
                  onClick={() => toggleActive(p)}
                  title={p.is_active ? "Deactivate" : "Activate"}
                >
                  {p.is_active ? "Disable" : "Enable"}
                </button>
                <button
                  className="btn-ghost h-9 w-9 p-0"
                  onClick={() => startEditing(p)}
                  title="Edit"
                >
                  <Pencil
                    size={14}
                    className="opacity-50 group-hover:opacity-100"
                  />
                </button>
                <button
                  className="btn-ghost h-9 w-9 p-0 text-red-400 hover:bg-red-50 hover:text-red-600 dark:hover:bg-red-950/30 dark:hover:text-red-400"
                  onClick={() => remove(p)}
                  title="Delete"
                >
                  <Trash2 size={14} />
                </button>
              </div>
            </div>
          );
        })}
      </div>

      {/* ── Web Search Tools ─────────────────────────────────────────────────── */}
      <div>
        <h2 className="text-xl font-semibold tracking-tight flex items-center gap-2">
          <Globe size={20} className="text-violet-500" />
          Web search tools
        </h2>
        <p className="mt-1 text-sm text-ink-500">
          Wikipedia and Web Agent are always available. Add Tavily or
          Perplexity for broader search coverage — they require API keys.
        </p>
      </div>

      <div className="card space-y-4">
        <h3 className="flex items-center gap-2 text-sm font-semibold">
          <Plus size={15} className="text-violet-500" />
          New web tool
        </h3>
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <div>
            <label className="mb-1 block text-xs font-medium text-ink-500">
              Name
            </label>
            <input
              className="input"
              value={webToolForm.name}
              onChange={(e) =>
                setWebToolForm({ ...webToolForm, name: e.target.value })
              }
              placeholder="e.g. Tavily"
            />
          </div>
          <div>
            <label className="mb-1 block text-xs font-medium text-ink-500">
              Type
            </label>
            <select
              className="input"
              value={webToolForm.tool_type}
              onChange={(e) =>
                setWebToolForm({ ...webToolForm, tool_type: e.target.value })
              }
            >
              {WEB_TOOL_TYPES.map((t) => (
                <option key={t} value={t}>
                  {t}
                </option>
              ))}
            </select>
            <p className="mt-1 text-[11px] text-ink-400">
              {WEBTOOL_HINTS[webToolForm.tool_type] ?? ""}
            </p>
          </div>
          {(webToolForm.tool_type === "tavily" ||
            webToolForm.tool_type === "perplexity") && (
            <div>
              <label className="mb-1 block text-xs font-medium text-ink-500">
                API Key
              </label>
              <input
                type="password"
                className="input"
                value={webToolForm.api_key ?? ""}
                onChange={(e) =>
                  setWebToolForm({ ...webToolForm, api_key: e.target.value })
                }
                placeholder="tvly-… / pplx-…"
              />
            </div>
          )}
        </div>

        <div className="flex gap-2">
          <button
            className="btn-primary"
            onClick={createWeb}
            disabled={busy || !webToolForm.name.trim()}
          >
            <Plus size={16} /> Add
          </button>
        </div>
      </div>

      <div className="space-y-2">
        {webTools.map((t) => (
          <div
            key={t.id}
            className="flex items-center justify-between rounded-xl border border-ink-200 px-4 py-3 dark:border-ink-800"
          >
            <div>
              <p className="flex items-center gap-2 font-medium">
                <Search size={14} className="text-violet-400" />
                {t.name}
              </p>
              <p className="text-xs text-ink-500">
                {t.tool_type}
                {t.base_url && ` · ${t.base_url}`}
                {t.has_api_key && <span className="ml-1">· 🔑</span>}
              </p>
            </div>
            <div className="flex items-center gap-2">
              <span className="text-ink-400">
                {t.is_active ? <Check size={15} /> : <X size={15} />}
              </span>
              <button
                className="btn-ghost h-9 w-9 p-0"
                onClick={() => removeWebTool(t.id)}
              >
                <Trash2 size={15} />
              </button>
            </div>
          </div>
        ))}
        {webTools.length === 0 && (
          <p className="rounded-xl border border-dashed border-ink-200 px-4 py-6 text-center text-sm text-ink-400 dark:border-ink-800">
            No search tools added yet. Add Tavily or Perplexity for broader coverage.
          </p>
        )}
      </div>
    </div>
  );
}

function ProviderTypeSelect({
  value,
  onChange,
}: {
  value: string;
  onChange: (t: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    function handleClick(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node))
        setOpen(false);
    }
    document.addEventListener("mousedown", handleClick);
    return () => document.removeEventListener("mousedown", handleClick);
  }, [open]);

  const Icon = PROVIDER_ICONS[value] ?? Cpu;
  const iconBg = PROVIDER_COLORS[value] ?? "";

  return (
    <div ref={ref} className="relative">
      <button
        type="button"
        className="input flex w-full items-center gap-2 pr-8 text-left"
        onClick={() => setOpen((o) => !o)}
      >
        <span
          className={cn(
            "flex h-5 w-5 shrink-0 items-center justify-center rounded",
            iconBg,
          )}
        >
          <Icon size={13} />
        </span>
        <span className="capitalize">{value}</span>
        <ChevronDown
          size={15}
          className={cn(
            "absolute right-2 top-1/2 -translate-y-1/2 text-ink-400 transition-transform",
            open && "rotate-180",
          )}
        />
      </button>

      {open && (
        <div className="absolute z-20 mt-1 w-full rounded-xl border border-ink-200 bg-white py-1 shadow-lg dark:border-ink-700 dark:bg-ink-900">
          {PROVIDER_TYPES.map((t) => {
            const TIcon = PROVIDER_ICONS[t] ?? Cpu;
            const tBg = PROVIDER_COLORS[t] ?? "";
            return (
              <button
                key={t}
                type="button"
                className={cn(
                  "flex w-full items-center gap-2 px-3 py-2 text-left text-sm transition-colors hover:bg-ink-50 dark:hover:bg-ink-800",
                  t === value && "bg-ink-50 dark:bg-ink-800/60",
                )}
                onClick={() => {
                  onChange(t);
                  setOpen(false);
                }}
              >
                <span
                  className={cn(
                    "flex h-5 w-5 shrink-0 items-center justify-center rounded",
                    tBg,
                  )}
                >
                  <TIcon size={13} />
                </span>
                <span className="capitalize">{t}</span>
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}

function TestResultCard({ result }: { result: TestResult }) {
  if (!result.success) {
    return (
      <div className="rounded-xl border border-red-300 bg-red-50 px-4 py-3 text-sm dark:border-red-900/60 dark:bg-red-950/30">
        <div className="flex items-center gap-2 font-medium text-red-700 dark:text-red-300">
          <AlertTriangle size={16} />
          Connection failed
          {result.stage && (
            <span className="text-xs font-normal text-red-500">
              ({result.stage})
            </span>
          )}
        </div>
        <p className="mt-1 break-words text-red-600 dark:text-red-300/90">
          {result.error_type ? `${result.error_type}: ` : ""}
          {result.error}
        </p>
      </div>
    );
  }

  return (
    <div className="rounded-xl border border-emerald-300 bg-emerald-50 px-4 py-3 text-sm dark:border-emerald-900/60 dark:bg-emerald-950/30">
      <div className="flex items-center gap-2 font-medium text-emerald-700 dark:text-emerald-300">
        <Check size={16} />
        Connection OK
      </div>
      <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs text-ink-600 dark:text-ink-300">
        {result.model && (
          <span className="inline-flex items-center gap-1">
            <Cpu size={13} /> {result.model}
          </span>
        )}
        {result.latency_ms != null && (
          <span className="inline-flex items-center gap-1">
            <Clock size={13} /> {result.latency_ms} ms
          </span>
        )}
        {result.tokens && (
          <span>
            tokens: {result.tokens.input}→{result.tokens.output} (
            {result.tokens.total} total)
          </span>
        )}
        <span
          className={
            result.followed_instruction
              ? "text-emerald-600 dark:text-emerald-400"
              : "text-amber-600 dark:text-amber-400"
          }
        >
          {result.followed_instruction
            ? "instruction followed"
            : "answered, but didn't follow instruction"}
        </span>
      </div>
      {result.response && (
        <p className="mt-2 rounded-lg bg-white/60 px-2 py-1 font-mono text-xs text-ink-700 dark:bg-black/20 dark:text-ink-200">
          {result.response}
        </p>
      )}
    </div>
  );
}
