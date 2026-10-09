// The only file that imports pdf.js. Everything else depends on these types, so tests can fake the loader.
import { getDocument, GlobalWorkerOptions } from "pdfjs-dist";
import workerUrl from "pdfjs-dist/build/pdf.worker.min.mjs?url";

// width/height are at scale 1, in CSS px.
export type PdfPage = { width: number; height: number; render(canvas: HTMLCanvasElement, scale: number): Promise<void> };
export type PdfDoc = { numPages: number; page(n: number): Promise<PdfPage>; destroy(): void };
export type PdfLoader = (url: string) => Promise<PdfDoc>;

GlobalWorkerOptions.workerSrc = workerUrl;
const CSS_PER_PT = 96 / 72;

export const loadPdf: PdfLoader = async (url) => {
  const task = getDocument({ url });
  const pdf = await task.promise;
  return {
    numPages: pdf.numPages,
    destroy: () => void task.destroy(), // frees the worker and aborts any network requests
    page: async (n) => {
      const p = await pdf.getPage(n);
      const base = p.getViewport({ scale: CSS_PER_PT });
      return {
        width: base.width,
        height: base.height,
        render: async (canvas, scale) => {
          const ratio = window.devicePixelRatio || 1;
          const viewport = p.getViewport({ scale: CSS_PER_PT * scale * ratio });
          canvas.width = viewport.width;
          canvas.height = viewport.height;
          canvas.style.width = `${viewport.width / ratio}px`;
          canvas.style.height = `${viewport.height / ratio}px`;
          await p.render({ canvas, viewport }).promise;
        },
      };
    },
  };
};
