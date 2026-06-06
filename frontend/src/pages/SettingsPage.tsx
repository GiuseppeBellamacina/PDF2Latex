import {
  AlertTriangle,
  Check,
  Clock,
  Cpu,
  Plus,
  Trash2,
  X,
  Zap,
} from "lucide-react";
import { useEffect, useState } from "react";
import { api, type Provider, type ProviderInput } from "../lib/api";
import { useAppStore } from "../stores/appStore";

type TestResult = Awaited<ReturnType<typeof api.testProvider>>;

const PROVIDER_TYPES = ["openai", "anthropic", "ollama", "custom", "fake"];

const EMPTY: ProviderInput = {
  name: "",
  provider_type: "openai",
  api_key: "",
  base_url: "",
  default_model: "",
  is_active: true,
};

export default function SettingsPage() {
  const { providers, loadProviders } = useAppStore();
  const [form, setForm] = useState<ProviderInput>(EMPTY);
  const [testResult, setTestResult] = useState<TestResult | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    loadProviders();
  }, [loadProviders]);

  const needsKey = ["openai", "anthropic", "custom"].includes(
    form.provider_type,
  );
  const needsUrl = ["ollama", "custom"].includes(form.provider_type);

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
        model: form.default_model || "gpt-4o-mini",
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

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">LLM providers</h1>
        <p className="mt-1 text-sm text-ink-500">
          API keys are stored encrypted. Use <em>fake</em> to try it offline.
        </p>
      </div>

      <div className="card space-y-4">
        <h2 className="text-sm font-semibold">New provider</h2>
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <div>
            <label className="mb-1 block text-sm font-medium">Name</label>
            <input
              className="input"
              value={form.name}
              onChange={(e) => setForm({ ...form, name: e.target.value })}
              placeholder="e.g. Main OpenAI"
            />
          </div>
          <div>
            <label className="mb-1 block text-sm font-medium">Type</label>
            <select
              className="input"
              value={form.provider_type}
              onChange={(e) =>
                setForm({ ...form, provider_type: e.target.value })
              }
            >
              {PROVIDER_TYPES.map((t) => (
                <option key={t} value={t}>
                  {t}
                </option>
              ))}
            </select>
          </div>
          <div>
            <label className="mb-1 block text-sm font-medium">
              Default model
            </label>
            <input
              className="input"
              value={form.default_model ?? ""}
              onChange={(e) =>
                setForm({ ...form, default_model: e.target.value })
              }
              placeholder="gpt-4o-mini / claude-3-5-sonnet / llama3"
            />
          </div>
          {needsUrl && (
            <div>
              <label className="mb-1 block text-sm font-medium">Base URL</label>
              <input
                className="input"
                value={form.base_url ?? ""}
                onChange={(e) => setForm({ ...form, base_url: e.target.value })}
                placeholder="http://localhost:11434"
              />
            </div>
          )}
          {needsKey && (
            <div className="sm:col-span-2">
              <label className="mb-1 block text-sm font-medium">API Key</label>
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
            <Zap size={16} /> Test
          </button>
          <button
            className="btn-primary"
            onClick={create}
            disabled={busy || !form.name.trim()}
          >
            <Plus size={16} /> Add
          </button>
        </div>
      </div>

      <div className="space-y-2">
        {providers.map((p) => (
          <div
            key={p.id}
            className="flex items-center justify-between rounded-xl border border-ink-200 px-4 py-3 dark:border-ink-800"
          >
            <div>
              <p className="font-medium">{p.name}</p>
              <p className="text-xs text-ink-500">
                {p.provider_type} · {p.default_model ?? "—"}{" "}
                {p.has_api_key && <span className="ml-1">· 🔑</span>}
              </p>
            </div>
            <div className="flex items-center gap-2">
              <span className="text-ink-400">
                {p.is_active ? <Check size={15} /> : <X size={15} />}
              </span>
              <button
                className="btn-ghost h-9 w-9 p-0"
                onClick={() => remove(p)}
              >
                <Trash2 size={15} />
              </button>
            </div>
          </div>
        ))}
      </div>
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
