import { useMemo, useRef, useState } from "react";
import { newKey, post, type ApiError, type Capabilities, type Job, type Printer, type Settings } from "../api";
import { plural } from "../lib/format";
import type { TrayEntry } from "./FileTray";
import { countPages } from "./FileTray";
import { IconAlert, IconFlask, IconInfo } from "./Icons";
import PaperPreview, { PREVIEW_LIMITS } from "./PaperPreview";
import { CHOICES, choiceLabel, LABELS } from "./SettingsPanel";
import { Dialog, Spinner } from "./ui";

const ORDER: (keyof Settings)[] = ["copies", "color_mode", "sides", "media", "orientation", "scaling", "media_source", "media_type", "quality", "collate", "finishings"];

export default function ReviewDialog({ printer, caps, files, settings, presetName, onClose, onSubmitted }: {
  printer: Printer;
  caps: Capabilities;
  files: TrayEntry[];
  settings: Settings;
  presetName: string | null;
  onClose: () => void;
  onSubmitted: (job: Job, duplicate: boolean) => void;
}) {
  // One key per review: repeated clicks or a network retry can never create a second job.
  const key = useRef(newKey());
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);
  const [previewIndex, setPreviewIndex] = useState(0);
  const [page, setPage] = useState(1);

  const totals = useMemo(() => {
    let pages = 0;
    for (const f of files) pages += countPages(f.pageRanges, f.file?.pages ?? 1) ?? 1;
    return { pages, sheetsHint: settings.sides && settings.sides !== "one-sided" ? Math.ceil(pages / 2) : pages };
  }, [files, settings.sides]);
  const copies = settings.copies ?? 1;

  const current = files[previewIndex];
  const firstSelected = current?.pageRanges.trim() ? parseInt(current.pageRanges.trim(), 10) : undefined;
  const maxPage = current?.file?.pages ?? 1;

  const submit = async () => {
    setBusy(true);
    setError(null);
    try {
      const r = await post<{ job: Job; duplicate: boolean }>("/api/jobs", {
        idempotency_key: key.current,
        printer_id: printer.id,
        items: files.map((f) => ({ file_id: f.file!.id, page_ranges: f.pageRanges.trim() || null })),
        settings,
        preset_name: presetName,
      });
      onSubmitted(r.job, r.duplicate);
    } catch (e: any) {
      setError(e);
      setBusy(false);
    }
  };

  const detailErrors: string[] = error?.details
    ? [...Object.values<string>(error.details.settings ?? {}), ...Object.values<string>(error.details.items ?? {})]
    : [];

  return (
    <Dialog
      title="Review and print"
      eyebrow={`Step 4 of 5 · ${printer.display_name}`}
      onClose={onClose}
      busy={busy}
      footer={
        <>
          <span className="subtle grow">
            {plural(files.length, "file")} · {plural(totals.pages, "page")} × {plural(copies, "copy", "copies")}
            {settings.sides && settings.sides !== "one-sided" ? ` · about ${plural(totals.sheetsHint * copies, "sheet")}` : ""}
          </span>
          <button className="btn" onClick={onClose} disabled={busy}>
            Back to settings
          </button>
          <button className="btn btn-primary btn-lg" onClick={submit} disabled={busy} data-autofocus>
            {busy ? <Spinner /> : printer.simulated ? "Run simulated print" : `Print ${plural(files.length, "file")}`}
          </button>
        </>
      }
    >
      <div className="review-grid">
        <div className="stack-lg">
          {printer.simulated && (
            <div className="callout callout-sim">
              <IconFlask />
              <span>Demo mode: this job is simulated. No printer will receive it and no paper will be used.</span>
            </div>
          )}
          {printer.status.state === "unknown" && (
            <div className="callout callout-warn">
              <IconAlert />
              <span>This printer's status is unknown. The job will be queued, but the hub can't confirm the printer is ready.</span>
            </div>
          )}
          {printer.status.reasons.filter((r) => r.severity !== "report").map((r) => (
            <div key={r.keyword} className="callout callout-warn">
              <IconAlert />
              <span>
                {printer.display_name} reports: {r.explanation}
              </span>
            </div>
          ))}

          <dl className="summary-list">
            <dt>Printer</dt>
            <dd>
              {printer.display_name}
              {printer.location && <div className="subtle">{printer.location}</div>}
            </dd>
            <dt>Files</dt>
            <dd>
              <ol className="ordered-files">
                {files.map((f, i) => (
                  <li key={f.key}>
                    <span className="n">{i + 1}</span>
                    <span style={{ minWidth: 0 }}>
                      <button className="link-btn" style={{ textAlign: "left", wordBreak: "break-word" }} onClick={() => { setPreviewIndex(i); setPage(1); }}>
                        {f.name}
                      </button>
                      <div className="subtle">
                        {f.pageRanges.trim() ? `Pages ${f.pageRanges.trim()}` : f.file?.pages ? `All ${plural(f.file.pages, "page")}` : "1 page"}
                      </div>
                    </span>
                  </li>
                ))}
              </ol>
            </dd>
            {presetName && (
              <>
                <dt>Preset</dt>
                <dd>{presetName}</dd>
              </>
            )}
            {ORDER.filter((k) => (CHOICES[k] ? (caps[CHOICES[k]] as unknown[]).length > 0 : k !== "finishings" || caps.finishings.length > 0)).map((k) => {
              if (k === "collate" && (copies < 2 || !caps.collate)) return null;
              const value = settings[k];
              const unset = value === undefined;
              const def = caps.defaults[k];
              return (
                <FragmentRow key={k} label={LABELS[k]}>
                  {unset ? (
                    <>
                      Printer default
                      {def ? <span className="subtle"> ({choiceLabel(caps, k, def)})</span> : null}
                    </>
                  ) : (
                    choiceLabel(caps, k, value)
                  )}
                </FragmentRow>
              );
            })}
          </dl>

          {error && (
            <div className="callout callout-bad" role="alert">
              <IconAlert />
              <div className="stack" style={{ gap: 4 }}>
                <b>{error.message}</b>
                {detailErrors.map((d) => (
                  <span key={d}>{d}</span>
                ))}
                {error.status === 0 && <span>Your job may not have been sent. Pressing Print again is safe — it can't create a duplicate.</span>}
              </div>
            </div>
          )}
        </div>

        <div className="stack">
          <div className="row-between">
            <span className="eyebrow">
              Preview · file {previewIndex + 1} of {files.length}
            </span>
            {current?.file?.kind === "pdf" && !current.pageRanges.trim() && maxPage > 1 && (
              <div className="row" style={{ gap: 6 }}>
                <button className="btn btn-sm" disabled={page <= 1} onClick={() => setPage(page - 1)} aria-label="Previous page">
                  ‹
                </button>
                <span className="subtle">
                  Page {page} / {maxPage}
                </span>
                <button className="btn btn-sm" disabled={page >= maxPage} onClick={() => setPage(page + 1)} aria-label="Next page">
                  ›
                </button>
              </div>
            )}
          </div>
          {current?.file && (
            <PaperPreview file={current.file} page={page} caps={caps} settings={settings} firstPage={firstSelected && !Number.isNaN(firstSelected) ? firstSelected : undefined} />
          )}
          <div className="callout callout-info">
            <IconInfo />
            <div className="stack" style={{ gap: 4 }}>
              <b>What the preview can't show</b>
              {PREVIEW_LIMITS.map((l) => (
                <span key={l}>{l}</span>
              ))}
            </div>
          </div>
        </div>
      </div>
    </Dialog>
  );
}

function FragmentRow({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <>
      <dt>{label}</dt>
      <dd>{children}</dd>
    </>
  );
}
