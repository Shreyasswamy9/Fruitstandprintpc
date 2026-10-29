import { useCallback, useEffect, useState } from "react";
import { del, get, patch, post, type Preset, type Settings } from "../../api";
import { IconInfo } from "../../components/Icons";
import { LABELS } from "../../components/SettingsPanel";
import { Dialog, Spinner, useToast } from "../../components/ui";

// Presets are printer-independent; values use the standard IPP keywords.
// When applied, each value is checked against the chosen printer and any
// unsupported value is reported to the person — never substituted.
const FIELDS: { key: keyof Settings; options: [string, string][] }[] = [
  { key: "color_mode", options: [["color", "Color"], ["monochrome", "Black & white"]] },
  { key: "sides", options: [["one-sided", "Single-sided"], ["two-sided-long-edge", "Double · long edge"], ["two-sided-short-edge", "Double · short edge"]] },
  { key: "quality", options: [["draft", "Draft"], ["normal", "Normal"], ["high", "High"]] },
  { key: "scaling", options: [["fit", "Fit to page"], ["none", "Actual size"], ["fill", "Fill page"]] },
  { key: "orientation", options: [["portrait", "Portrait"], ["landscape", "Landscape"]] },
  { key: "media", options: [["na_letter_8.5x11in", "Letter"], ["na_legal_8.5x14in", "Legal"], ["na_ledger_11x17in", "Tabloid"], ["iso_a4_210x297mm", "A4"]] },
];

function describe(s: Settings): string {
  const parts = FIELDS.filter((f) => s[f.key]).map((f) => f.options.find(([k]) => k === s[f.key])?.[1] ?? String(s[f.key]));
  return parts.join(" · ") || "No settings";
}

export default function AdminPresets() {
  const toast = useToast();
  const [presets, setPresets] = useState<Preset[] | null>(null);
  const [editing, setEditing] = useState<Partial<Preset> | null>(null);
  const load = useCallback(() => get<{ presets: Preset[] }>("/api/presets").then((r) => setPresets(r.presets)), []);
  useEffect(() => {
    load();
  }, [load]);

  const remove = async (p: Preset) => {
    await del(`/api/admin/presets/${p.id}`);
    toast({ title: `Deleted “${p.name}”` });
    load();
  };

  return (
    <div className="stack-lg">
      <div className="row-between">
        <div className="callout callout-info" style={{ maxWidth: 720 }}>
          <IconInfo />
          <span>Presets are checked against the selected printer every time they're used. Settings a printer doesn't support are listed for the person, never quietly swapped.</span>
        </div>
        <button className="btn btn-primary" onClick={() => setEditing({ name: "", description: "", settings: {} })}>
          New preset
        </button>
      </div>
      <div className="card table-wrap">
        <table className="table">
          <thead>
            <tr>
              <th>Name</th>
              <th>Settings</th>
              <th aria-label="Actions" />
            </tr>
          </thead>
          <tbody>
            {presets?.map((p) => (
              <tr key={p.id}>
                <td>
                  <b>{p.name}</b>
                  <div className="subtle">{p.description}</div>
                </td>
                <td className="subtle">{describe(p.settings)}</td>
                <td>
                  <div className="row" style={{ justifyContent: "flex-end" }}>
                    <button className="btn btn-sm" onClick={() => setEditing(p)}>
                      Edit
                    </button>
                    <button className="btn btn-sm btn-danger" onClick={() => remove(p)}>
                      Delete
                    </button>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {editing && <PresetEditor preset={editing} onClose={() => setEditing(null)} onSaved={() => { setEditing(null); load(); }} />}
    </div>
  );
}

function PresetEditor({ preset, onClose, onSaved }: { preset: Partial<Preset>; onClose: () => void; onSaved: () => void }) {
  const toast = useToast();
  const [name, setName] = useState(preset.name ?? "");
  const [description, setDescription] = useState(preset.description ?? "");
  const [settings, setSettings] = useState<Settings>(preset.settings ?? {});
  const [busy, setBusy] = useState(false);
  const save = async () => {
    setBusy(true);
    const body = { name, description, settings };
    try {
      if (preset.id) await patch(`/api/admin/presets/${preset.id}`, body);
      else await post("/api/admin/presets", body);
      toast({ title: "Preset saved" });
      onSaved();
    } catch (e: any) {
      toast({ title: "Not saved", body: e.message, tone: "bad" });
      setBusy(false);
    }
  };
  return (
    <Dialog title={preset.id ? "Edit preset" : "New preset"} size="sm" onClose={onClose} busy={busy}
      footer={<>
        <button className="btn" onClick={onClose}>Cancel</button>
        <button className="btn btn-primary" onClick={save} disabled={busy || !name.trim()}>{busy ? <Spinner /> : "Save"}</button>
      </>}>
      <div className="stack">
        <div className="field">
          <label htmlFor="psn">Name</label>
          <input id="psn" className="input" maxLength={60} value={name} onChange={(e) => setName(e.target.value)} />
        </div>
        <div className="field">
          <label htmlFor="psd">Description</label>
          <input id="psd" className="input" maxLength={200} value={description} onChange={(e) => setDescription(e.target.value)} />
        </div>
        <div className="form-grid" style={{ gridTemplateColumns: "1fr 1fr" }}>
          {FIELDS.map((f) => (
            <div className="field" key={f.key}>
              <label htmlFor={`pf-${f.key}`}>{LABELS[f.key]}</label>
              <select id={`pf-${f.key}`} className="select" value={(settings[f.key] as string) ?? ""}
                onChange={(e) => setSettings({ ...settings, [f.key]: e.target.value || undefined })}>
                <option value="">Leave as is</option>
                {f.options.map(([k, l]) => <option key={k} value={k}>{l}</option>)}
              </select>
            </div>
          ))}
        </div>
      </div>
    </Dialog>
  );
}
