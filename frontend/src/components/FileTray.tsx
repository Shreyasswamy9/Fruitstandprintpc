import { useEffect, useRef, useState } from "react";
import type { HubFile } from "../api";
import { bytes, plural } from "../lib/format";
import { renderPage } from "../lib/pdf";
import { IconAlert, IconDown, IconImage, IconUp, IconUpload, IconX } from "./Icons";

export interface TrayEntry {
  key: string;
  name: string;
  size: number;
  state: "uploading" | "processing" | "ready" | "error";
  progress: number;
  error?: string;
  file?: HubFile;
  pageRanges: string;
  rangeError?: string;
}

const ACCEPT = ".pdf,.jpg,.jpeg,.png,.webp,application/pdf,image/jpeg,image/png,image/webp";

export function Thumb({ file, size = 52 }: { file: HubFile; size?: number }) {
  const canvas = useRef<HTMLCanvasElement>(null);
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    if (file.kind !== "pdf" || !canvas.current) return;
    renderPage(file.id, 1, canvas.current, size * 2).catch(() => setFailed(true));
  }, [file.id, file.kind, size]);
  if (file.kind === "image") return <img src={`/api/files/${file.id}/content`} alt="" loading="lazy" />;
  if (failed) return <IconAlert />;
  return <canvas ref={canvas} aria-hidden="true" />;
}

export default function FileTray({
  entries,
  activeKey,
  limits,
  onAdd,
  onRemove,
  onMove,
  onSelect,
  onRanges,
  pageRangesSupported,
}: {
  entries: TrayEntry[];
  activeKey: string | null;
  limits: { max_file_mb: number; max_files_per_job: number; max_pdf_pages: number; types: string[] };
  onAdd: (files: File[]) => void;
  onRemove: (key: string) => void;
  onMove: (key: string, toIndex: number) => void;
  onSelect: (key: string) => void;
  onRanges: (key: string, value: string) => void;
  pageRangesSupported: boolean | null;
}) {
  const input = useRef<HTMLInputElement>(null);
  const [over, setOver] = useState(false);
  const [dragKey, setDragKey] = useState<string | null>(null);
  const [dropIndex, setDropIndex] = useState<number | null>(null);

  const ready = entries.filter((e) => e.state === "ready").length;

  return (
    <div className="tray-layout">
      <div>
        <div
          className="dropzone"
          role="button"
          tabIndex={0}
          data-over={over}
          aria-label="Add files: browse or drop files here"
          onClick={() => input.current?.click()}
          onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && (e.preventDefault(), input.current?.click())}
          onDragOver={(e) => {
            if (e.dataTransfer.types.includes("Files")) {
              e.preventDefault();
              setOver(true);
            }
          }}
          onDragLeave={() => setOver(false)}
          onDrop={(e) => {
            e.preventDefault();
            e.stopPropagation();
            setOver(false);
            onAdd(Array.from(e.dataTransfer.files));
          }}
        >
          <IconUpload />
          <strong>{entries.length ? "Add more files" : "Add files"}</strong>
          <span className="subtle">Drop here or click to browse</span>
          <span className="subtle" style={{ fontSize: "0.72rem" }}>
            {limits.types.join(", ")} · up to {limits.max_file_mb} MB each · {limits.max_files_per_job} files per job
          </span>
        </div>
        <input
          ref={input}
          type="file"
          multiple
          accept={ACCEPT}
          hidden
          onChange={(e) => {
            onAdd(Array.from(e.target.files ?? []));
            e.target.value = "";
          }}
        />
      </div>

      {entries.length > 0 && (
        <ol className="tray-list" aria-label={`Files to print, ${plural(ready, "file")} ready`}>
          {entries.map((entry, index) => (
            <li
              key={entry.key}
              className="tray-item"
              data-state={entry.state}
              data-active={entry.key === activeKey}
              data-dragging={dragKey === entry.key}
              data-dropbefore={dropIndex === index && dragKey !== entry.key}
              draggable={entry.state === "ready"}
              onDragStart={(e) => {
                setDragKey(entry.key);
                e.dataTransfer.effectAllowed = "move";
                e.dataTransfer.setData("text/plain", entry.key);
              }}
              onDragOver={(e) => {
                if (!dragKey) return;
                e.preventDefault();
                setDropIndex(index);
              }}
              onDrop={(e) => {
                if (!dragKey) return;
                e.preventDefault();
                e.stopPropagation();
                onMove(dragKey, index);
                setDragKey(null);
                setDropIndex(null);
              }}
              onDragEnd={() => {
                setDragKey(null);
                setDropIndex(null);
              }}
            >
              <button
                type="button"
                className="thumb"
                style={{ border: 0, padding: 0, cursor: entry.file ? "pointer" : "default" }}
                onClick={() => entry.file && onSelect(entry.key)}
                aria-label={entry.file ? `Preview ${entry.name}` : entry.name}
                disabled={!entry.file}
              >
                {entry.file ? <Thumb file={entry.file} /> : entry.state === "error" ? <IconAlert /> : <IconImage />}
                {entry.file && <span className="badge">{entry.file.kind === "pdf" ? "PDF" : entry.file.mime.split("/")[1].toUpperCase()}</span>}
                {entry.state === "ready" && <span className="pos">{index + 1}</span>}
              </button>

              <div style={{ minWidth: 0 }}>
                <div className="tray-name" title={entry.name}>
                  {entry.name}
                </div>
                <div className="tray-meta">
                  {entry.state === "uploading" && `Uploading… ${Math.round(entry.progress * 100)}%`}
                  {entry.state === "processing" && "Checking file…"}
                  {entry.state === "ready" && entry.file && (
                    <>
                      {bytes(entry.size)}
                      {entry.file.pages ? ` · ${plural(entry.file.pages, "page")}` : ""}
                    </>
                  )}
                  {entry.state === "error" && <span style={{ color: "var(--bad)", fontWeight: 650 }}>{entry.error}</span>}
                </div>
                {(entry.state === "uploading" || entry.state === "processing") && (
                  <div className="progress" data-indeterminate={entry.state === "processing"} style={{ marginTop: 6 }}>
                    <span style={{ width: `${Math.round(entry.progress * 100)}%` }} />
                  </div>
                )}
              </div>

              <div className="tray-actions">
                {entry.state === "ready" && (
                  <>
                    <button type="button" className="btn btn-ghost btn-icon" aria-label={`Move ${entry.name} up`} disabled={index === 0}
                      onClick={() => onMove(entry.key, index - 1)}>
                      <IconUp size={16} />
                    </button>
                    <button type="button" className="btn btn-ghost btn-icon" aria-label={`Move ${entry.name} down`}
                      disabled={index === entries.length - 1} onClick={() => onMove(entry.key, index + 1)}>
                      <IconDown size={16} />
                    </button>
                  </>
                )}
                <button type="button" className="btn btn-ghost btn-icon btn-danger" aria-label={`Remove ${entry.name}`} onClick={() => onRemove(entry.key)}>
                  <IconX size={16} />
                </button>
              </div>

              {entry.state === "ready" && entry.file && (entry.file.kind === "pdf" || entry.file.notes.length > 0) && (
                <div className="tray-extra">
                  {entry.file.kind === "pdf" && (entry.file.pages ?? 0) > 1 && pageRangesSupported !== false && (
                    <div className="field" style={{ gap: 4 }}>
                      <div className="range-input">
                        <label htmlFor={`r-${entry.key}`} className="subtle" style={{ whiteSpace: "nowrap" }}>
                          Pages
                        </label>
                        <input
                          id={`r-${entry.key}`}
                          className="input"
                          placeholder={`All (1–${entry.file.pages})`}
                          value={entry.pageRanges}
                          aria-invalid={!!entry.rangeError}
                          onChange={(e) => onRanges(entry.key, e.target.value)}
                        />
                      </div>
                      {entry.rangeError && <span className="field-error" style={{ fontSize: "0.75rem" }}>{entry.rangeError}</span>}
                    </div>
                  )}
                  {entry.file.notes.map((n) => (
                    <span key={n} className="subtle" style={{ fontSize: "0.75rem" }}>
                      ⓘ {n}
                    </span>
                  ))}
                </div>
              )}
            </li>
          ))}
        </ol>
      )}
    </div>
  );
}

/** Client-side mirror of the server's page-range rules, for instant feedback. */
export function checkRanges(text: string, pages: number | null): string | undefined {
  const t = text.trim();
  if (!t) return undefined;
  if (!/^\s*\d+\s*(-\s*\d+\s*)?(,\s*\d+\s*(-\s*\d+\s*)?)*$/.test(t)) return "Use numbers and ranges like 1-3, 5";
  for (const chunk of t.split(",")) {
    const [a, b] = chunk.split("-").map((x) => parseInt(x, 10));
    const end = b ?? a;
    if (a < 1 || end < a) return `“${chunk.trim()}” isn't a valid range`;
    if (pages && end > pages) return `This file has ${pages} pages`;
  }
  return undefined;
}

export function countPages(text: string, pages: number | null): number | null {
  const t = text.trim();
  if (!t || checkRanges(t, pages)) return pages;
  return t.split(",").reduce((sum, chunk) => {
    const [a, b] = chunk.split("-").map((x) => parseInt(x, 10));
    return sum + ((b ?? a) - a + 1);
  }, 0);
}
