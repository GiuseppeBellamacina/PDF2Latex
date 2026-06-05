import { Check, Plus, Trash2, X, Zap } from "lucide-react";
import { useEffect, useState } from "react";
import { api, type Provider, type ProviderInput } from "../lib/api";
import { useAppStore } from "../stores/appStore";

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
  const [testResult, setTestResult] = useState<string | null>(null);
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
      setTestResult(r.success ? `OK: ${r.response}` : `Error: ${r.error}`);
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

        {testResult && (
          <p className="text-sm text-ink-600 dark:text-ink-400">{testResult}</p>
        )}

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
