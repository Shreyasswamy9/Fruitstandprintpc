import type { Capabilities, Choice, Preset, Printer, Settings } from "../api";
import { IconAlert, IconInfo } from "./Icons";
import { Disclosure, Segmented, Stepper } from "./ui";

export const LABELS: Record<string, string> = {
  copies: "Copies",
  color_mode: "Color",
  sides: "Sides",
  media: "Paper size",
  orientation: "Orientation",
  scaling: "Scaling",
  media_source: "Paper tray",
  media_type: "Paper type",
  quality: "Quality",
  collate: "Collation",
  finishings: "Finishing",
};

export const CHOICES: Record<string, keyof Capabilities> = {
  color_mode: "color_modes",
  sides: "sides",
  media: "media",
  orientation: "orientations",
  scaling: "scaling",
  media_source: "media_sources",
  media_type: "media_types",
  quality: "qualities",
};

export function choiceLabel(caps: Capabilities | null, key: string, value: unknown): string {
  if (value === undefined || value === null) return "Printer default";
  if (key === "copies") return String(value);
  if (key === "collate") return value ? "Collated (1,2,3 · 1,2,3)" : "Uncollated (1,1 · 2,2 · 3,3)";
  if (key === "finishings") {
    const list = value as string[];
    if (!list.length) return "None";
    return list.map((v) => caps?.finishings.find((f) => f.key === v)?.label ?? v).join(", ");
  }
  const opts = caps ? (caps[CHOICES[key]] as Choice[]) : [];
  return opts?.find((o) => o.key === value)?.label ?? String(value);
}

/** Keep only settings the printer supports. Returns what was removed so the UI can say so. */
export function reconcile(settings: Settings, caps: Capabilities): { kept: Settings; dropped: { key: string; value: unknown }[] } {
  const kept: Settings = {};
  const dropped: { key: string; value: unknown }[] = [];
  for (const [key, value] of Object.entries(settings) as [keyof Settings, any][]) {
    if (value === undefined) continue;
    let ok = false;
    if (key === "copies") ok = !!caps.copies && value >= caps.copies.min && value <= caps.copies.max;
    else if (key === "collate") ok = caps.collate;
    else if (key === "finishings") ok = (value as string[]).every((v) => caps.finishings.some((f) => f.key === v));
    else ok = (caps[CHOICES[key]] as Choice[]).some((c) => c.key === value);
    if (ok) (kept as any)[key] = value;
    else if (!(key === "copies" && value === 1)) dropped.push({ key, value });
  }
  return { kept, dropped };
}

/** Explicit starting values: the printer's own defaults plus the administrator's defaults for this printer. */
export function initialSettings(caps: Capabilities, printer: Printer): Settings {
  const fromPrinter: Settings = {};
  for (const [k, v] of Object.entries(caps.defaults)) if (v) (fromPrinter as any)[k] = v;
  return reconcile({ ...fromPrinter, ...(caps.collate ? { collate: true } : {}), ...printer.defaults, copies: 1 }, caps).kept;
}

function Choices({ k, caps, settings, onChange, autoLabel }: {
  k: keyof Settings; caps: Capabilities; settings: Settings; onChange: (p: Settings) => void; autoLabel?: string;
}) {
  const opts = caps[CHOICES[k]] as Choice[];
  const value = settings[k] as string | undefined;
  if (opts.length > 4) {
    return (
      <select className="select" aria-label={LABELS[k]} value={value ?? ""} onChange={(e) => onChange({ [k]: e.target.value || undefined })}>
        <option value="">{autoLabel ?? "Printer default"}</option>
        {opts.map((o) => (
          <option key={o.key} value={o.key}>
            {o.label}
          </option>
        ))}
      </select>
    );
  }
  const items = [...(autoLabel ? [{ key: "", label: autoLabel }] : []), ...opts.map((o) => ({ key: o.key, label: o.label }))];
  return (
    <Segmented
      label={LABELS[k]}
      value={value ?? ""}
      options={items}
      onChange={(v) => onChange({ [k]: v || undefined })}
    />
  );
}

export default function SettingsPanel({
  printer,
  caps,
  settings,
  onChange,
  presets,
  activePreset,
  onPreset,
  notices,
  onDismissNotices,
}: {
  printer: Printer;
  caps: Capabilities;
  settings: Settings;
  onChange: (patch: Settings) => void;
  presets: Preset[];
  activePreset: string | null;
  onPreset: (p: Preset) => void;
  notices: string[];
  onDismissNotices: () => void;
}) {
  const unavailable: string[] = [];
  if (caps.color_modes.length < 2) unavailable.push(caps.color_modes[0]?.key === "monochrome" ? "Color" : "Black & white choice");
  if (!caps.sides.some((s) => s.key !== "one-sided")) unavailable.push("Double-sided");
  if (!caps.finishings.length) unavailable.push("Stapling / finishing");
  if (!caps.media_sources.length) unavailable.push("Tray choice");
  if (!caps.media_types.length) unavailable.push("Paper type");
  if (!caps.qualities.length) unavailable.push("Quality");
  if (!caps.scaling.length) unavailable.push("Scaling");
  if (!caps.page_ranges) unavailable.push("Page ranges");
  if (!caps.copies) unavailable.push("Multiple copies");

  const copies = settings.copies ?? 1;
  const sidesOpts = caps.sides.map((s) => ({
    key: s.key,
    label: s.key === "one-sided" ? "Single" : s.key === "two-sided-long-edge" ? "Double · long edge" : "Double · short edge",
    sub: s.key === "two-sided-long-edge" ? "Flip like a book" : s.key === "two-sided-short-edge" ? "Flip like a notepad" : undefined,
  }));

  return (
    <div className="settings-panel">
      {notices.length > 0 && (
        <div className="callout callout-warn" style={{ marginBottom: 16 }} role="status">
          <IconAlert />
          <div className="stack" style={{ gap: 4 }}>
            {notices.map((n) => (
              <span key={n}>{n}</span>
            ))}
            <button className="link-btn" style={{ alignSelf: "flex-start" }} onClick={onDismissNotices}>
              OK
            </button>
          </div>
        </div>
      )}

      {presets.length > 0 && (
        <div className="setting">
          <div className="setting-head">
            <span className="field-label">Presets</span>
          </div>
          <div className="preset-list">
            {presets.map((p) => {
              const skipped = Object.keys(p.compatibility?.unsupported ?? {});
              return (
                <button key={p.id} type="button" className="preset" aria-pressed={activePreset === p.name} onClick={() => onPreset(p)}>
                  <b>{p.name}</b>
                  <span>{p.description}</span>
                  {skipped.length > 0 && (
                    <span className="preset-warn">
                      Skips {skipped.map((s) => LABELS[s]?.toLowerCase() ?? s).join(", ")} on this printer
                    </span>
                  )}
                </button>
              );
            })}
          </div>
        </div>
      )}

      <div className="setting">
        <div className="setting-head">
          <span className="field-label">Copies</span>
          {caps.copies && <span className="subtle">max {caps.copies.max}</span>}
        </div>
        {caps.copies ? (
          <Stepper label="copies" value={copies} min={caps.copies.min} max={caps.copies.max} onChange={(n) => onChange({ copies: n })} />
        ) : (
          <span className="subtle">1 copy — this printer doesn't report support for multiple copies.</span>
        )}
      </div>

      {caps.color_modes.length > 0 && (
        <div className="setting">
          <div className="setting-head">
            <span className="field-label">Color</span>
          </div>
          {caps.color_modes.length > 1 ? (
            <Choices k="color_mode" caps={caps} settings={settings} onChange={onChange} />
          ) : (
            <span className="muted">{caps.color_modes[0].label} only</span>
          )}
        </div>
      )}

      {caps.sides.length > 0 && (
        <div className="setting">
          <div className="setting-head">
            <span className="field-label">Sides</span>
          </div>
          {caps.sides.length > 1 ? (
            <Segmented label="Sides" value={settings.sides} options={sidesOpts} onChange={(v) => onChange({ sides: v })} />
          ) : (
            <span className="muted">{caps.sides[0].label} only</span>
          )}
        </div>
      )}

      {caps.media.length > 0 && (
        <div className="setting">
          <div className="setting-head">
            <span className="field-label">Paper size</span>
          </div>
          <Choices k="media" caps={caps} settings={settings} onChange={onChange} />
        </div>
      )}

      {caps.orientations.length > 0 && (
        <div className="setting">
          <div className="setting-head">
            <span className="field-label">Orientation</span>
          </div>
          <Choices k="orientation" caps={caps} settings={settings} onChange={onChange} autoLabel="Automatic" />
        </div>
      )}

      {caps.scaling.length > 0 && (
        <div className="setting">
          <div className="setting-head">
            <span className="field-label">Scaling</span>
          </div>
          <Choices k="scaling" caps={caps} settings={settings} onChange={onChange} autoLabel="Default" />
        </div>
      )}

      <Disclosure title="More options">
        <div className="stack">
          {caps.media_sources.length > 0 && (
            <div className="field">
              <span className="field-label">Paper tray</span>
              <Choices k="media_source" caps={caps} settings={settings} onChange={onChange} />
            </div>
          )}
          {caps.media_types.length > 0 && (
            <div className="field">
              <span className="field-label">Paper type</span>
              <Choices k="media_type" caps={caps} settings={settings} onChange={onChange} />
            </div>
          )}
          {caps.qualities.length > 0 && (
            <div className="field">
              <span className="field-label">Quality</span>
              <Choices k="quality" caps={caps} settings={settings} onChange={onChange} />
            </div>
          )}
          {caps.collate && copies > 1 && (
            <label className="check">
              <input type="checkbox" checked={settings.collate === true} onChange={(e) => onChange({ collate: e.target.checked })} />
              <span>
                Collate copies
                <span className="field-hint" style={{ display: "block" }}>
                  On: 1,2,3 · 1,2,3. Off: 1,1 · 2,2 · 3,3.
                </span>
              </span>
            </label>
          )}
          {caps.finishings.length > 0 && (
            <fieldset className="field" style={{ border: 0, padding: 0, margin: 0 }}>
              <legend className="field-label">Finishing</legend>
              {caps.finishings.map((f) => {
                const list = settings.finishings ?? [];
                return (
                  <label className="check" key={f.key}>
                    <input
                      type="checkbox"
                      checked={list.includes(f.key)}
                      onChange={(e) => onChange({ finishings: e.target.checked ? [...list, f.key] : list.filter((x) => x !== f.key) })}
                    />
                    {f.label}
                  </label>
                );
              })}
            </fieldset>
          )}
        </div>
      </Disclosure>

      {unavailable.length > 0 && (
        <div className="setting" style={{ borderTop: "1px solid var(--line)" }}>
          <div className="setting-head">
            <span className="field-label">Not available on {printer.display_name}</span>
          </div>
          <div className="not-supported">
            {unavailable.map((u) => (
              <span key={u}>{u}</span>
            ))}
          </div>
          <span className="field-hint">
            <IconInfo size={12} style={{ display: "inline", verticalAlign: "-2px" }} /> Only options the printer reports are offered.
          </span>
        </div>
      )}
    </div>
  );
}
