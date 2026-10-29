import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { del, get, uploadFile, type Capabilities, type HubFile, type Job, type Preset, type Printer, type Settings } from "../api";
import FileTray, { checkRanges, type TrayEntry } from "../components/FileTray";
import { IconAlert, IconArrowRight, IconFlask, IconRefresh } from "../components/Icons";
import PrinterGrid, { printerBlocked } from "../components/PrinterGrid";
import PaperPreview from "../components/PaperPreview";
import ReviewDialog from "../components/ReviewDialog";
import SettingsPanel, { choiceLabel, initialSettings, LABELS, reconcile } from "../components/SettingsPanel";
import { Dialog, Spinner, useInterval, useToast } from "../components/ui";
import { useHub } from "../context";
import { plural } from "../lib/format";
import { forgetPdf } from "../lib/pdf";

const EXT_OK = /\.(pdf|jpe?g|png|webp)$/i;
const OFFICE = /\.(docx?|xlsx?|pptx?|odt|ods|odp|pages|numbers|key|rtf|txt|csv)$/i;
const UPLOAD_CONCURRENCY = 2;

let counter = 0;
const localKey = () => `local-${Date.now()}-${counter++}`;

function entryFromFile(f: HubFile): TrayEntry {
  return { key: f.id, name: f.name, size: f.size_bytes, state: "ready", progress: 1, file: f, pageRanges: "" };
}

export default function PrintPage() {
  const { boot } = useHub();
  const toast = useToast();
  const navigate = useNavigate();
  const limits = boot.limits;

  // ---- files ---------------------------------------------------------------
  const [tray, setTray] = useState<TrayEntry[]>([]);
  const [activeKey, setActiveKey] = useState<string | null>(null);
  const queue = useRef<{ key: string; file: File }[]>([]);
  const running = useRef(0);

  useEffect(() => {
    get<{ files: (HubFile & { used_in_jobs: number })[] }>("/api/files")
      .then((r) => setTray(r.files.filter((f) => f.used_in_jobs === 0).map(entryFromFile)))
      .catch(() => {});
  }, []);

  const patchEntry = useCallback((key: string, patch: Partial<TrayEntry>) => {
    setTray((list) => list.map((e) => (e.key === key ? { ...e, ...patch } : e)));
  }, []);

  const pump = useCallback(() => {
    while (running.current < UPLOAD_CONCURRENCY && queue.current.length) {
      const job = queue.current.shift()!;
      running.current++;
      uploadFile(job.file, (fraction) => patchEntry(job.key, { progress: fraction, state: fraction >= 1 ? "processing" : "uploading" }))
        .then((file) => {
          setTray((list) => list.map((e) => (e.key === job.key ? { ...entryFromFile(file), key: file.id } : e)));
        })
        .catch((err) => patchEntry(job.key, { state: "error", error: err.message }))
        .finally(() => {
          running.current--;
          pump();
        });
    }
  }, [patchEntry]);

  const addFiles = useCallback(
    (files: File[]) => {
      if (!files.length) return;
      const accepted: TrayEntry[] = [];
      const rejected: string[] = [];
      let room = limits.max_files_per_job - tray.filter((e) => e.state !== "error").length;
      for (const f of files) {
        if (!EXT_OK.test(f.name)) {
          rejected.push(
            OFFICE.test(f.name) ? `${f.name}: Office documents aren't supported yet — save it as PDF first.` : `${f.name}: unsupported type.`,
          );
          continue;
        }
        if (f.size > limits.max_file_mb * 1024 * 1024) {
          rejected.push(`${f.name}: larger than ${limits.max_file_mb} MB.`);
          continue;
        }
        if (room <= 0) {
          rejected.push(`${f.name}: a job can include at most ${limits.max_files_per_job} files.`);
          continue;
        }
        room--;
        const key = localKey();
        accepted.push({ key, name: f.name, size: f.size, state: "uploading", progress: 0, pageRanges: "" });
        queue.current.push({ key, file: f });
      }
      if (accepted.length) setTray((list) => [...list, ...accepted]);
      if (rejected.length)
        toast({ title: `${plural(rejected.length, "file")} not added`, body: rejected.slice(0, 3).join(" "), tone: "warn" });
      pump();
    },
    [limits, tray, pump, toast],
  );

  // Drop files anywhere on the page
  const [pageDrag, setPageDrag] = useState(false);
  useEffect(() => {
    let depth = 0;
    const isFiles = (e: DragEvent) => e.dataTransfer?.types.includes("Files");
    const enter = (e: DragEvent) => isFiles(e) && (depth++, setPageDrag(true));
    const leave = (e: DragEvent) => isFiles(e) && --depth <= 0 && (depth = 0, setPageDrag(false));
    const over = (e: DragEvent) => isFiles(e) && e.preventDefault();
    const drop = (e: DragEvent) => {
      if (!isFiles(e)) return;
      e.preventDefault();
      depth = 0;
      setPageDrag(false);
      addFiles(Array.from(e.dataTransfer?.files ?? []));
    };
    window.addEventListener("dragenter", enter);
    window.addEventListener("dragleave", leave);
    window.addEventListener("dragover", over);
    window.addEventListener("drop", drop);
    return () => {
      window.removeEventListener("dragenter", enter);
      window.removeEventListener("dragleave", leave);
      window.removeEventListener("dragover", over);
      window.removeEventListener("drop", drop);
    };
  }, [addFiles]);

  const removeEntry = async (key: string) => {
    const entry = tray.find((e) => e.key === key);
    queue.current = queue.current.filter((q) => q.key !== key);
    setTray((list) => list.filter((e) => e.key !== key));
    if (entry?.file) {
      forgetPdf(entry.file.id);
      try {
        await del(`/api/files/${entry.file.id}`);
      } catch (e: any) {
        toast({ title: "Couldn't remove file", body: e.message, tone: "bad" });
      }
    }
  };

  const moveEntry = (key: string, to: number) =>
    setTray((list) => {
      const from = list.findIndex((e) => e.key === key);
      if (from < 0) return list;
      const next = [...list];
      const [item] = next.splice(from, 1);
      next.splice(Math.max(0, Math.min(to, next.length)), 0, item);
      return next;
    });

  const setRanges = (key: string, value: string) =>
    setTray((list) => list.map((e) => (e.key === key ? { ...e, pageRanges: value, rangeError: checkRanges(value, e.file?.pages ?? null) } : e)));

  // ---- printers --------------------------------------------------------------
  const [printers, setPrinters] = useState<Printer[] | null>(null);
  const [printersError, setPrintersError] = useState<string | null>(null);
  const [printerId, setPrinterId] = useState<string | null>(null);
  const loadPrinters = useCallback(
    () =>
      get<{ printers: Printer[] }>("/api/printers")
        .then((r) => {
          setPrinters(r.printers);
          setPrintersError(null);
        })
        .catch((e) => setPrintersError(e.message)),
    [],
  );
  useEffect(() => {
    loadPrinters();
  }, [loadPrinters]);
  useInterval(loadPrinters, 15000);
  const printer = printers?.find((p) => p.id === printerId) ?? null;

  // ---- capabilities, presets, settings ----------------------------------------
  const [caps, setCaps] = useState<Capabilities | null>(null);
  const [capsLoading, setCapsLoading] = useState(false);
  const [capsError, setCapsError] = useState<string | null>(null);
  const [presets, setPresets] = useState<Preset[]>([]);
  const [settings, setSettings] = useState<Settings>({});
  const [presetName, setPresetName] = useState<string | null>(null);
  const [notices, setNotices] = useState<string[]>([]);
  const touched = useRef(false);

  const selectPrinter = async (id: string) => {
    if (id === printerId) return;
    const target = printers?.find((p) => p.id === id);
    if (!target) return;
    setPrinterId(id);
    setCapsLoading(true);
    setCapsError(null);
    try {
      const [c, p] = await Promise.all([
        get<{ capabilities: Capabilities }>(`/api/printers/${id}/capabilities?refresh=true`),
        get<{ presets: Preset[] }>(`/api/presets?printer_id=${encodeURIComponent(id)}`),
      ]);
      const newCaps = c.capabilities;
      setCaps(newCaps);
      setPresets(p.presets);
      const base = initialSettings(newCaps, target);
      if (touched.current) {
        const { kept, dropped } = reconcile(settings, newCaps);
        setSettings({ ...base, ...kept });
        setNotices(
          dropped.map(
            (d) => `${LABELS[d.key]} “${choiceLabel(caps, d.key, d.value)}” isn't available on ${target.display_name}, so it was reset to this printer's default.`,
          ),
        );
      } else {
        setSettings(base);
        setNotices([]);
      }
    } catch (e: any) {
      setCaps(null);
      setCapsError(e.message);
    } finally {
      setCapsLoading(false);
    }
  };

  const changeSettings = (patch: Settings) => {
    touched.current = true;
    setPresetName(null);
    setSettings((s) => {
      const next = { ...s, ...patch };
      for (const k of Object.keys(next) as (keyof Settings)[]) if (next[k] === undefined) delete next[k];
      return next;
    });
  };

  const applyPreset = (p: Preset) => {
    if (!caps || !printer) return;
    touched.current = true;
    const compat = p.compatibility ?? { applicable: p.settings, unsupported: {} };
    setSettings((s) => ({ ...s, ...compat.applicable }));
    setPresetName(p.name);
    const skipped = Object.entries(compat.unsupported);
    setNotices(skipped.length ? [`“${p.name}” applied, except: ${skipped.map(([, why]) => why).join(" ")}`] : []);
    if (!skipped.length) toast({ title: `Preset applied: ${p.name}` });
  };

  // ---- review -------------------------------------------------------------------
  const [reviewing, setReviewing] = useState(false);
  const readyFiles = tray.filter((e) => e.state === "ready" && e.file);
  const pending = tray.some((e) => e.state === "uploading" || e.state === "processing");
  const rangeErrors = readyFiles.some((e) => e.rangeError);
  const unsupportedFormat = caps ? readyFiles.filter((e) => e.file && !caps.formats[e.file.mime === "application/pdf" ? "pdf" : e.file.mime === "image/jpeg" ? "jpeg" : "png"]) : [];
  const blocked = printer ? printerBlocked(printer) : null;

  const reason = useMemo(() => {
    if (!readyFiles.length) return "Add at least one file";
    if (pending) return "Waiting for uploads to finish";
    if (!printer) return "Choose a printer";
    if (blocked) return blocked;
    if (capsLoading) return "Reading printer options…";
    if (!caps) return "Printer options unavailable";
    if (rangeErrors) return "Fix the page ranges";
    if (unsupportedFormat.length) return `${printer.display_name} can't print ${unsupportedFormat[0].name}`;
    return null;
  }, [readyFiles.length, pending, printer, blocked, capsLoading, caps, rangeErrors, unsupportedFormat]);

  const onSubmitted = (job: Job, duplicate: boolean) => {
    setReviewing(false);
    setTray((list) => list.filter((e) => !readyFiles.some((r) => r.key === e.key)));
    touched.current = false;
    toast({
      title: duplicate ? "Already submitted" : job.simulated ? "Simulated job started" : "Sent to the print queue",
      body: duplicate ? "That confirmation was already received — no duplicate was created." : `Job ${job.reference}`,
    });
    navigate(`/jobs/${job.id}`);
  };

  const step = !readyFiles.length ? 0 : !printer ? 1 : reviewing ? 3 : 2;
  const steps = ["Add files", "Choose printer", "Adjust settings", "Preview & confirm", "Track"];

  return (
    <div className="page">
      {pageDrag && (
        <div className="page-drop-hint">
          <div>Drop to add files</div>
        </div>
      )}
      <ol className="steps" aria-label="Progress">
        {steps.map((s, i) => (
          <li key={s} data-state={i < step ? "done" : i === step ? "current" : "todo"} aria-current={i === step ? "step" : undefined}>
            {s}
          </li>
        ))}
      </ol>

      <div className="workspace" data-panel={printer ? "open" : "closed"}>
        <section className="col col-tray" aria-labelledby="files-h">
          <div className="sticky-col">
            <div className="panel">
              <div className="panel-head">
                <h3 id="files-h">Files</h3>
                <span className="subtle">{readyFiles.length ? `${plural(readyFiles.length, "file")} · prints in this order` : "Nothing added yet"}</span>
              </div>
              <div className="panel-body">
                <FileTray
                  entries={tray}
                  activeKey={activeKey}
                  limits={limits}
                  onAdd={addFiles}
                  onRemove={removeEntry}
                  onMove={moveEntry}
                  onSelect={setActiveKey}
                  onRanges={setRanges}
                  pageRangesSupported={caps ? caps.page_ranges : null}
                />
                <p className="subtle" style={{ marginTop: 16 }}>
                  Files are private to you and deleted automatically after {boot.settings.file_retention_hours} hours. Nothing prints until you confirm.
                </p>
              </div>
            </div>
          </div>
        </section>

        <section className="col" aria-labelledby="printers-h">
          <div className="section-title">
            <div>
              <span className="eyebrow">Step 2</span>
              <h2 id="printers-h">Choose a printer</h2>
            </div>
            <button className="btn btn-ghost btn-sm" onClick={loadPrinters} aria-label="Refresh printer status">
              <IconRefresh size={16} /> Refresh
            </button>
          </div>
          {boot.mode === "demo" && (
            <div className="callout callout-sim" style={{ marginBottom: 16 }}>
              <IconFlask />
              <span>These printers are simulated for demonstration. Their statuses and supplies are made up.</span>
            </div>
          )}
          {printersError && (
            <div className="callout callout-bad" style={{ marginBottom: 16 }}>
              <IconAlert />
              <span>Couldn't load printers: {printersError}</span>
            </div>
          )}
          {printers ? (
            <PrinterGrid printers={printers} selectedId={printerId} onSelect={selectPrinter} />
          ) : (
            <div className="printer-grid">
              {[0, 1, 2].map((i) => (
                <div key={i} className="skeleton" style={{ height: 320 }} />
              ))}
            </div>
          )}
        </section>

        {printer && (
          <aside className="col" aria-labelledby="settings-h">
            <div className="sticky-col">
              <div className="panel">
                <div className="panel-head">
                  <div>
                    <span className="eyebrow">Step 3</span>
                    <h3 id="settings-h">Settings</h3>
                  </div>
                  <span className="subtle" style={{ textAlign: "right" }}>
                    {printer.display_name}
                  </span>
                </div>
                <div className="panel-body">
                  {capsLoading && (
                    <div className="row">
                      <Spinner /> Reading what this printer supports…
                    </div>
                  )}
                  {capsError && !capsLoading && (
                    <div className="callout callout-bad">
                      <IconAlert />
                      <span>
                        Couldn't read this printer's options: {capsError} Printing to it is blocked until they can be read, so no settings are guessed.
                      </span>
                    </div>
                  )}
                  {caps && !capsLoading && (
                    <SettingsPanel
                      printer={printer}
                      caps={caps}
                      settings={settings}
                      onChange={changeSettings}
                      presets={presets}
                      activePreset={presetName}
                      onPreset={applyPreset}
                      notices={notices}
                      onDismissNotices={() => setNotices([])}
                    />
                  )}
                </div>
              </div>
            </div>
          </aside>
        )}
      </div>

      <div className="action-bar">
        <div className="action-summary" aria-live="polite">
          <span className="chip">{readyFiles.length ? plural(readyFiles.length, "file") : "No files"}</span>
          <span className="chip">{printer ? printer.display_name : "No printer"}</span>
          {caps && settings.copies && settings.copies > 1 && <span className="chip">{settings.copies} copies</span>}
          {caps && settings.color_mode && <span className="chip">{choiceLabel(caps, "color_mode", settings.color_mode)}</span>}
          {caps && settings.sides && <span className="chip">{settings.sides === "one-sided" ? "Single-sided" : "Double-sided"}</span>}
          {presetName && <span className="chip chip-accent">{presetName}</span>}
        </div>
        {reason && <span className="subtle">{reason}</span>}
        <button className="btn btn-primary btn-lg" disabled={!!reason} onClick={() => setReviewing(true)}>
          Review & print <IconArrowRight size={18} />
        </button>
      </div>

      {activeKey && (() => {
        const entry = tray.find((e) => e.key === activeKey);
        if (!entry?.file) return null;
        return <FilePreview file={entry.file} caps={caps} settings={settings} onClose={() => setActiveKey(null)} />;
      })()}

      {reviewing && printer && caps && (
        <ReviewDialog
          printer={printer}
          caps={caps}
          files={readyFiles}
          settings={settings}
          presetName={presetName}
          onClose={() => setReviewing(false)}
          onSubmitted={onSubmitted}
        />
      )}
    </div>
  );
}

function FilePreview({ file, caps, settings, onClose }: { file: HubFile; caps: Capabilities | null; settings: Settings; onClose: () => void }) {
  const [page, setPage] = useState(1);
  const pages = file.pages ?? 1;
  return (
    <Dialog title={file.name} eyebrow="Preview" onClose={onClose} size="sm">
      <div className="stack">
        {file.kind === "pdf" && pages > 1 && (
          <div className="row" style={{ justifyContent: "center" }}>
            <button className="btn btn-sm" disabled={page <= 1} onClick={() => setPage(page - 1)} aria-label="Previous page">‹</button>
            <span className="subtle">Page {page} of {pages}</span>
            <button className="btn btn-sm" disabled={page >= pages} onClick={() => setPage(page + 1)} aria-label="Next page">›</button>
          </div>
        )}
        <PaperPreview file={file} page={page} caps={caps} settings={settings} />
        {!caps && <p className="subtle">Shown on Letter paper. Choose a printer to preview with its paper sizes and settings.</p>}
        {file.notes.map((n) => <p key={n} className="subtle">ⓘ {n}</p>)}
      </div>
    </Dialog>
  );
}
