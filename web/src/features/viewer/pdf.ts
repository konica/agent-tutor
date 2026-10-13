// The only file that imports pdf.js. Everything else depends on these types, so tests can fake the loader.
// The legacy build: the default one calls APIs only the newest browsers have (Uint8Array.prototype.toHex,
// Map.prototype.getOrInsertComputed), so Chrome 138 couldn't open any document.
import { getDocument, GlobalWorkerOptions, TextLayer, Util } from "pdfjs-dist/legacy/build/pdf.mjs";
import workerUrl from "pdfjs-dist/legacy/build/pdf.worker.min.mjs?url";

import type { TextItem } from "./passage";

// width/height are at scale 1, in CSS px. textItems: the page's text layer in CSS px at scale 1, origin top-left.
// renderText: fills `container` with the page's text, transparent over the canvas at `scale`, so it can be selected and
// copied; it replaces what an earlier call put there.
export type PdfPage = {
  width: number;
  height: number;
  render(canvas: HTMLCanvasElement, scale: number): Promise<void>;
  textItems(): Promise<TextItem[]>;
  renderText(container: HTMLElement, scale: number): Promise<void>;
};
export type PdfDoc = { numPages: number; page(n: number): Promise<PdfPage>; destroy(): void };
export type PdfLoader = (url: string) => Promise<PdfDoc>;

GlobalWorkerOptions.workerSrc = workerUrl;
const CSS_PER_PT = 96 / 72;

export const loadPdf: PdfLoader = async (url) => {
  const task = getDocument({ url });
  let pdf: Awaited<typeof task.promise>;
  try {
    pdf = await task.promise;
  } catch (error) {
    // A failed load still holds its worker; free it before the viewer shows the error.
    task.destroy().catch(() => {});
    throw error;
  }
  return {
    numPages: pdf.numPages,
    destroy: () => void task.destroy().catch(() => {}), // frees the worker and aborts any network requests
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
        // pdf.js sizes the layer and its spans from --total-scale-factor (CSS px per PDF point). The endOfContent div
        // after the spans is pdf.js's selection backstop (DocumentViewer.module.css).
        renderText: async (container, scale) => {
          const viewport = p.getViewport({ scale: CSS_PER_PT * scale });
          container.replaceChildren();
          container.style.setProperty("--total-scale-factor", `${viewport.scale}`);
          await new TextLayer({ textContentSource: p.streamTextContent(), container, viewport }).render();
          const end = document.createElement("div");
          end.className = "endOfContent";
          container.append(end);
        },
        // An item's matrix composed with the viewport's: (e, f) is its baseline start in CSS px and |(c, d)| its font
        // height, so the box's top is the baseline minus that height.
        textItems: async () => {
          const content = await p.getTextContent();
          return content.items.flatMap((it) => {
            if (!("str" in it)) return [];
            const [, , c, d, e, f] = Util.transform(base.transform, it.transform) as number[];
            const height = Math.hypot(c!, d!);
            return [{ str: it.str, hasEOL: it.hasEOL, x: e!, y: f! - height, width: it.width * CSS_PER_PT, height }];
          });
        },
      };
    },
  };
};
