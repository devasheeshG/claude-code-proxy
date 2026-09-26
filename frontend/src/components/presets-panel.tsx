"use client";

import { useState } from "react";
import { Plus, SlidersHorizontal, Trash2 } from "lucide-react";
import { api } from "@/lib/api";
import { Preset, ThinkingLevel, ThinkingMode, THINKING_LEVELS } from "@/lib/types";
import { Button, Field, Modal, TextInput } from "@/components/ui";

const MODES: ThinkingMode[] = ["disabled", "enabled", "adaptive"];

function toggle<T extends string>(values: T[], value: T): T[] {
    return values.includes(value) ? values.filter((item) => item !== value) : [...values, value];
}

function Chips<T extends string>({
    values,
    selected,
    onChange,
}: {
    values: readonly T[];
    selected: T[];
    onChange: (values: T[]) => void;
}) {
    return (
        <div className="flex flex-wrap gap-2">
            {values.map((value) => (
                <button
                    key={value}
                    type="button"
                    onClick={() => onChange(toggle(selected, value))}
                    aria-pressed={selected.includes(value)}
                    className={`rounded-md border px-3 py-2 text-xs transition-colors ${selected.includes(value) ? "border-brand-500/60 bg-brand-500/15 text-brand-300" : "border-ink-700 bg-ink-900 text-fog-400 hover:text-fog-100"}`}
                >
                    {value}
                </button>
            ))}
        </div>
    );
}

export function ModelAccessEditor({
    models,
    value,
    onChange,
}: {
    models: string[];
    value: string[] | null;
    onChange: (value: string[] | null) => void;
}) {
    return (
        <div className="space-y-3">
            <label className="text-fog-200 flex items-center gap-2 text-sm">
                <input
                    type="checkbox"
                    checked={value === null}
                    onChange={(event) => onChange(event.target.checked ? null : [])}
                />
                Allow every configured model
            </label>
            {value !== null && <Chips values={models} selected={value} onChange={onChange} />}
        </div>
    );
}

export function ThinkingModesEditor({
    value,
    onChange,
}: {
    value: ThinkingMode[];
    onChange: (value: ThinkingMode[]) => void;
}) {
    return <Chips values={MODES} selected={value} onChange={onChange} />;
}

export function ModelRulesEditor({
    models,
    levels,
    modes,
    onLevels,
    onModes,
}: {
    models: string[];
    levels: Record<string, ThinkingLevel[]>;
    modes: Record<string, ThinkingMode[]>;
    onLevels: (value: Record<string, ThinkingLevel[]>) => void;
    onModes: (value: Record<string, ThinkingMode[]>) => void;
}) {
    const [newModel, setNewModel] = useState("");
    const configured = [...new Set([...Object.keys(levels), ...Object.keys(modes)])];
    const remove = (model: string) => {
        const nextLevels = { ...levels };
        const nextModes = { ...modes };
        delete nextLevels[model];
        delete nextModes[model];
        onLevels(nextLevels);
        onModes(nextModes);
    };
    return (
        <div className="space-y-3">
            <div className="flex flex-col gap-2 sm:flex-row">
                <select
                    aria-label="Model for a new per-model rule"
                    value={newModel}
                    onChange={(event) => setNewModel(event.target.value)}
                    className="border-ink-700 bg-ink-900 text-fog-100 min-w-0 flex-1 rounded-md border px-3 py-2 text-sm"
                >
                    <option value="">Choose a model…</option>
                    {models
                        .filter((model) => !configured.includes(model))
                        .map((model) => (
                            <option key={model} value={model}>
                                {model}
                            </option>
                        ))}
                </select>
                <Button
                    type="button"
                    variant="ghost"
                    disabled={!newModel}
                    onClick={() => {
                        onLevels({ ...levels, [newModel]: [...THINKING_LEVELS] });
                        onModes({ ...modes, [newModel]: [...MODES] });
                        setNewModel("");
                    }}
                >
                    <Plus size={14} /> Add rule
                </Button>
            </div>
            {configured.map((model) => (
                <div
                    key={model}
                    className="border-ink-700 bg-ink-950/40 rounded-lg border p-3 sm:p-4"
                >
                    <div className="mb-3 flex items-center justify-between gap-2">
                        <code className="text-fog-100 min-w-0 text-sm break-all">{model}</code>
                        <button
                            type="button"
                            onClick={() => remove(model)}
                            aria-label={`Remove ${model} rule`}
                            className="text-fog-400 hover:text-bad-500 rounded p-1"
                        >
                            <Trash2 size={15} />
                        </button>
                    </div>
                    <div className="space-y-3">
                        <Field label="Thinking levels">
                            <Chips
                                values={THINKING_LEVELS}
                                selected={levels[model] ?? [...THINKING_LEVELS]}
                                onChange={(items) => onLevels({ ...levels, [model]: items })}
                            />
                        </Field>
                        <Field label="Thinking modes">
                            <Chips
                                values={MODES}
                                selected={modes[model] ?? MODES}
                                onChange={(items) => onModes({ ...modes, [model]: items })}
                            />
                        </Field>
                    </div>
                </div>
            ))}
        </div>
    );
}

function PresetModal({
    preset,
    models,
    onClose,
    onSaved,
}: {
    preset: Preset | null;
    models: string[];
    onClose: () => void;
    onSaved: () => void;
}) {
    const [name, setName] = useState(preset?.name ?? "");
    const [allModels, setAllModels] = useState(preset?.allowed_models === null || !preset);
    const [allowedModels, setAllowedModels] = useState<string[]>(preset?.allowed_models ?? []);
    const [levels, setLevels] = useState<ThinkingLevel[]>(
        preset?.allowed_thinking_levels ?? [...THINKING_LEVELS],
    );
    const [modes, setModes] = useState<ThinkingMode[]>(preset?.allowed_thinking_modes ?? MODES);
    const [redirects, setRedirects] = useState<Record<string, string>>(
        preset?.model_overrides ?? {},
    );
    const [modelLevels, setModelLevels] = useState<Record<string, ThinkingLevel[]>>(
        preset?.model_thinking_levels ?? {},
    );
    const [modelModes, setModelModes] = useState<Record<string, ThinkingMode[]>>(
        preset?.model_thinking_modes ?? {},
    );
    const [source, setSource] = useState("");
    const [target, setTarget] = useState("");
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState<string | null>(null);
    const save = async (event: React.FormEvent) => {
        event.preventDefault();
        setError(null);
        setBusy(true);
        try {
            const payload = {
                name: name.trim(),
                allowed_models: allModels ? null : allowedModels,
                allowed_thinking_levels: levels,
                allowed_thinking_modes: modes,
                model_overrides: redirects,
                model_thinking_levels: modelLevels,
                model_thinking_modes: modelModes,
            };
            if (preset) await api.updatePreset(preset.id, payload);
            else await api.createPreset(payload);
            onSaved();
        } catch (err) {
            setError(err instanceof Error ? err.message : "Could not save preset");
        } finally {
            setBusy(false);
        }
    };
    return (
        <Modal
            title={preset ? `Edit ${preset.name}` : "Create preset"}
            onClose={onClose}
            widthClass="max-w-3xl"
        >
            <form onSubmit={(event) => void save(event)} className="space-y-5">
                <Field label="Preset name">
                    <TextInput
                        value={name}
                        onChange={(event) => setName(event.target.value)}
                        required
                        maxLength={120}
                        placeholder="e.g. Standard access"
                    />
                </Field>
                <div className="border-ink-700 rounded-lg border p-3 sm:p-4">
                    <label className="text-fog-200 flex items-center gap-2 text-sm">
                        <input
                            type="checkbox"
                            checked={allModels}
                            onChange={(event) => setAllModels(event.target.checked)}
                        />
                        Allow every configured model
                    </label>
                    {!allModels && (
                        <div className="mt-3">
                            <Chips
                                values={models}
                                selected={allowedModels}
                                onChange={setAllowedModels}
                            />
                        </div>
                    )}
                </div>
                <Field label="Allowed thinking levels">
                    <Chips values={THINKING_LEVELS} selected={levels} onChange={setLevels} />
                </Field>
                <Field label="Allowed thinking modes">
                    <Chips values={MODES} selected={modes} onChange={setModes} />
                </Field>
                <div className="space-y-2">
                    <div className="text-fog-200 text-sm font-medium">Model rewrites</div>
                    <p className="text-fog-400 text-xs">
                        Use exact model IDs. The client-facing source must also be allowed above.
                    </p>
                    {Object.entries(redirects).map(([from, to]) => (
                        <div
                            key={from}
                            className="border-ink-700 flex items-center gap-2 rounded border p-2 text-xs"
                        >
                            <code className="min-w-0 flex-1 break-all">
                                {from} → {to}
                            </code>
                            <button
                                type="button"
                                onClick={() => {
                                    const next = { ...redirects };
                                    delete next[from];
                                    setRedirects(next);
                                }}
                                aria-label={`Remove ${from} rewrite`}
                            >
                                <Trash2 size={14} />
                            </button>
                        </div>
                    ))}
                    <div className="grid gap-2 sm:grid-cols-[1fr_1fr_auto]">
                        <select
                            aria-label="Rewrite source"
                            value={source}
                            onChange={(event) => setSource(event.target.value)}
                            className="border-ink-700 bg-ink-900 rounded border px-2 py-2 text-sm"
                        >
                            <option value="">Source model…</option>
                            {models.map((model) => (
                                <option key={model}>{model}</option>
                            ))}
                        </select>
                        <select
                            aria-label="Rewrite target"
                            value={target}
                            onChange={(event) => setTarget(event.target.value)}
                            className="border-ink-700 bg-ink-900 rounded border px-2 py-2 text-sm"
                        >
                            <option value="">Target model…</option>
                            {models.map((model) => (
                                <option key={model}>{model}</option>
                            ))}
                        </select>
                        <Button
                            type="button"
                            variant="ghost"
                            disabled={!source || !target || source === target}
                            onClick={() => {
                                setRedirects({ ...redirects, [source]: target });
                                setSource("");
                                setTarget("");
                            }}
                        >
                            Add
                        </Button>
                    </div>
                </div>
                <Field
                    label="Per-model thinking rules"
                    hint="Optional narrower levels and modes per model."
                >
                    <ModelRulesEditor
                        models={models}
                        levels={modelLevels}
                        modes={modelModes}
                        onLevels={setModelLevels}
                        onModes={setModelModes}
                    />
                </Field>
                {error && (
                    <p role="alert" className="text-bad-500 text-sm">
                        {error}
                    </p>
                )}
                <div className="flex flex-wrap justify-end gap-2">
                    <Button type="button" variant="ghost" onClick={onClose}>
                        Cancel
                    </Button>
                    <Button
                        type="submit"
                        variant="primary"
                        disabled={
                            busy ||
                            !name.trim() ||
                            !levels.length ||
                            !modes.length ||
                            (!allModels && !allowedModels.length) ||
                            Object.values(modelLevels).some((items) => !items.length) ||
                            Object.values(modelModes).some((items) => !items.length)
                        }
                    >
                        {busy ? "Saving…" : "Save preset"}
                    </Button>
                </div>
            </form>
        </Modal>
    );
}

export function PresetsPanel({
    presets,
    models,
    onChanged,
}: {
    presets: Preset[];
    models: string[];
    onChanged: () => void;
}) {
    const [editing, setEditing] = useState<Preset | null>(null);
    const [creating, setCreating] = useState(false);
    const [error, setError] = useState<string | null>(null);
    const remove = async (preset: Preset) => {
        if (!window.confirm(`Delete preset “${preset.name}”?`)) return;
        try {
            await api.deletePreset(preset.id);
            onChanged();
        } catch (err) {
            setError(err instanceof Error ? err.message : "Could not delete preset");
        }
    };
    return (
        <section
            className="border-ink-700 bg-ink-900 rounded-xl border p-4 sm:p-5"
            aria-label="Policy presets"
        >
            <div className="flex flex-wrap items-start justify-between gap-3">
                <div>
                    <h2 className="text-fog-100 flex items-center gap-2 text-lg font-semibold">
                        <SlidersHorizontal size={18} className="text-brand-400" /> Policy presets
                    </h2>
                    <p className="text-fog-400 mt-1 text-xs">
                        Reusable model and thinking baselines. User overrides stay in place when a
                        preset changes.
                    </p>
                </div>
                <Button variant="primary" onClick={() => setCreating(true)}>
                    <Plus size={14} /> New preset
                </Button>
            </div>
            {error && (
                <p role="alert" className="text-bad-500 mt-3 text-sm">
                    {error}
                </p>
            )}
            <div className="mt-4 grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
                {presets.map((preset) => (
                    <article
                        key={preset.id}
                        className="border-ink-700 bg-ink-950/40 rounded-lg border p-3.5"
                    >
                        <div className="flex items-start justify-between gap-2">
                            <div className="min-w-0">
                                <h3 className="text-fog-100 truncate text-sm font-semibold">
                                    {preset.name}
                                </h3>
                                <p className="text-fog-400 mt-0.5 text-xs">
                                    {preset.user_count} assigned ·{" "}
                                    {preset.allowed_models
                                        ? `${preset.allowed_models.length} models`
                                        : "All models"}
                                </p>
                            </div>
                            <div className="flex shrink-0 gap-1">
                                <button
                                    type="button"
                                    aria-label={`Edit ${preset.name}`}
                                    onClick={() => setEditing(preset)}
                                    className="text-fog-400 hover:text-brand-300 rounded p-1.5"
                                >
                                    <SlidersHorizontal size={15} />
                                </button>
                                <button
                                    type="button"
                                    aria-label={`Delete ${preset.name}`}
                                    disabled={preset.user_count > 0}
                                    title={
                                        preset.user_count > 0
                                            ? "Reassign users first"
                                            : "Delete preset"
                                    }
                                    onClick={() => void remove(preset)}
                                    className="text-fog-400 hover:text-bad-500 rounded p-1.5 disabled:opacity-30"
                                >
                                    <Trash2 size={15} />
                                </button>
                            </div>
                        </div>
                        <p className="text-fog-400 mt-3 line-clamp-2 font-mono text-[11px]">
                            {Object.entries(preset.model_overrides)
                                .map(([from, to]) => `${from} → ${to}`)
                                .join(" · ") || "No rewrites"}
                        </p>
                    </article>
                ))}
            </div>
            {creating && (
                <PresetModal
                    preset={null}
                    models={models}
                    onClose={() => setCreating(false)}
                    onSaved={() => {
                        setCreating(false);
                        onChanged();
                    }}
                />
            )}
            {editing && (
                <PresetModal
                    preset={editing}
                    models={models}
                    onClose={() => setEditing(null)}
                    onSaved={() => {
                        setEditing(null);
                        onChanged();
                    }}
                />
            )}
        </section>
    );
}
