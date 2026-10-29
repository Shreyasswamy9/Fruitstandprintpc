import * as pdfjs from "pdfjs-dist";
import workerUrl from "pdfjs-dist/build/pdf.worker.min.mjs?url";

pdfjs.GlobalWorkerOptions.workerSrc = workerUrl;

const docs = new Map<string, { task: pdfjs.PDFDocumentLoadingTask; promise: Promise<pdfjs.PDFDocumentProxy> }>();

/** Load (and cache) a PDF the current user uploaded. All assets are served by the hub itself. */
export function loadPdf(fileId: string): Promise<pdfjs.PDFDocumentProxy> {
  let entry = docs.get(fileId);
  if (!entry) {
    const task = pdfjs.getDocument({
      url: `/api/files/${encodeURIComponent(fileId)}/content`,
      withCredentials: true,
      cMapUrl: "/pdfjs/cmaps/",
      cMapPacked: true,
      standardFontDataUrl: "/pdfjs/standard_fonts/",
      wasmUrl: "/pdfjs/wasm/",
    });
    entry = { task, promise: task.promise };
    entry.promise.catch(() => docs.delete(fileId));
    docs.set(fileId, entry);
  }
  return entry.promise;
}

export function forgetPdf(fileId: string) {
  const entry = docs.get(fileId);
  docs.delete(fileId);
  entry?.task.destroy().catch(() => {});
}

/** Render one page into a canvas at roughly `targetWidth` CSS pixels. */
export async function renderPage(fileId: string, pageNumber: number, canvas: HTMLCanvasElement, targetWidth: number) {
  const doc = await loadPdf(fileId);
  const page = await doc.getPage(Math.min(Math.max(1, pageNumber), doc.numPages));
  const base = page.getViewport({ scale: 1 });
  const ratio = Math.min(window.devicePixelRatio || 1, 2);
  const viewport = page.getViewport({ scale: (targetWidth / base.width) * ratio });
  canvas.width = Math.floor(viewport.width);
  canvas.height = Math.floor(viewport.height);
  const task = page.render({ canvas, viewport });
  await task.promise;
  return { widthPt: base.width, heightPt: base.height };
}
