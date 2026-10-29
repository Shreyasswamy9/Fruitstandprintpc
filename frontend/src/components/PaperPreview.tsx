import { useEffect, useRef, useState } from "react";
import type { Capabilities, HubFile, Settings } from "../api";
import { renderPage } from "../lib/pdf";
import { IconAlert } from "./Icons";
import { Spinner } from "./ui";

const LETTER = { width_mm: 215.9, height_mm: 279.4 };
const MM_TO_PT = 72 / 25.4;
const MAX_H = 360;
const MAX_W = 460;

/**
 * Approximate preview of one page on the chosen paper. It models paper size,
 * orientation, scaling and color/grayscale. It cannot model printer margins,
 * driver color conversion, duplex registration, finishing or tray behaviour.
 */
export default function PaperPreview({ file, page, caps, settings, firstPage }: {
  file: HubFile;
  page: number;
  caps: Capabilities | null;
  settings: Settings;
  firstPage?: number;
}) {
  const canvas = useRef<HTMLCanvasElement>(null);
  const [content, setContent] = useState<{ w: number; h: number } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [imgSize, setImgSize] = useState<{ w: number; h: number } | null>(null);

  const mediaKey = settings.media ?? caps?.defaults.media;
  const media = caps?.media.find((m) => m.key === mediaKey) ?? LETTER;
  let paperWpt = media.width_mm * MM_TO_PT;
  let paperHpt = media.height_mm * MM_TO_PT;

  const pageNumber = firstPage ?? page;

  useEffect(() => {
    setError(null);
    if (file.kind !== "pdf" || !canvas.current) return;
    let alive = true;
    renderPage(file.id, pageNumber, canvas.current, 520)
      .then((r) => alive && setContent({ w: r.widthPt, h: r.heightPt }))
      .catch(() => alive && setError("This page could not be drawn in the preview. It may still print correctly."));
    return () => {
      alive = false;
    };
  }, [file.id, file.kind, pageNumber]);

  // Content size in points
  let cw: number | null = null;
  let ch: number | null = null;
  if (file.kind === "pdf" && content) {
    cw = content.w;
    ch = content.h;
  } else if (file.kind === "image" && imgSize) {
    cw = file.width_pt ?? imgSize.w;
    ch = file.height_pt ?? imgSize.h;
  }

  const contentLandscape = cw !== null && ch !== null && cw > ch;
  const orientation = settings.orientation ?? (contentLandscape ? "landscape" : "portrait");
  if (orientation === "landscape") [paperWpt, paperHpt] = [paperHpt, paperWpt];

  const scaleToFrame = Math.min(MAX_W / paperWpt, MAX_H / paperHpt);
  const W = paperWpt * scaleToFrame;
  const H = paperHpt * scaleToFrame;

  const scaling = settings.scaling ?? "fit";
  let box = { left: 0, top: 0, width: W, height: H };
  const imageHasNoResolution = file.kind === "image" && !file.width_pt;
  if (cw && ch) {
    let s: number;
    if (scaling === "none" && !imageHasNoResolution) s = scaleToFrame;
    else if (scaling === "fill") s = Math.max(W / cw, H / ch);
    else s = Math.min(W / cw, H / ch);
    const w = cw * s;
    const h = ch * s;
    box = { left: (W - w) / 2, top: (H - h) / 2, width: w, height: h };
  }
  const margin = 4.2 * MM_TO_PT * scaleToFrame; // typical ~4 mm unprintable edge

  const mono = settings.color_mode === "monochrome" || (caps?.color_modes.length === 1 && caps.color_modes[0].key === "monochrome");

  return (
    <div>
      <div className="preview-stage">
        <div className="paper" data-mono={mono} style={{ width: W, height: H }} aria-label="Approximate print preview">
          <div className="paper-content" style={box}>
            {file.kind === "pdf" ? (
              <canvas ref={canvas} />
            ) : (
              <img
                src={`/api/files/${file.id}/content`}
                alt=""
                onLoad={(e) => setImgSize({ w: e.currentTarget.naturalWidth, h: e.currentTarget.naturalHeight })}
                onError={() => setError("This image could not be shown in the preview.")}
              />
            )}
          </div>
          <div className="paper-margin" style={{ inset: margin }} />
          {!content && file.kind === "pdf" && !error && (
            <div style={{ position: "absolute", inset: 0, display: "grid", placeItems: "center" }}>
              <Spinner label="Rendering preview" />
            </div>
          )}
        </div>
      </div>
      <div className="preview-caption">
        <span>
          {media === LETTER ? "Letter (assumed)" : caps?.media.find((m) => m.key === mediaKey)?.label} · {orientation}
          {settings.orientation ? "" : " (automatic)"} · {scaling === "none" ? "actual size" : scaling === "fill" ? "fill" : "fit"}
          {mono ? " · grayscale" : ""}
        </span>
        <span className="subtle">Dashed line ≈ typical unprintable edge</span>
      </div>
      {error && (
        <p className="field-error" style={{ marginTop: 8 }}>
          <IconAlert size={14} style={{ display: "inline", verticalAlign: "-2px" }} /> {error}
        </p>
      )}
      {scaling === "none" && imageHasNoResolution && (
        <p className="subtle" style={{ marginTop: 8 }}>
          This image has no resolution information, so its printed “actual size” is decided by the print system. Shown fitted instead.
        </p>
      )}
    </div>
  );
}

export const PREVIEW_LIMITS = [
  "Margins differ by printer; content near the edge may be clipped.",
  "Colors on paper won't match your screen exactly, and grayscale is only an approximation of the printer's conversion.",
  "Double-sided alignment, stapling and tray selection can't be shown on screen.",
  "With automatic orientation, the print system decides rotation; the preview shows the most likely result.",
];
