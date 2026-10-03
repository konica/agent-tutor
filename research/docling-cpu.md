# How should Docling run on CPU in the worker image?

Research for wayfinder ticket #27 (map #25). Feeds benchmark ticket #28. Date: 2026-10-03. Docling version at time of writing: **2.132.0** (released 2026-10-01).

## Answer

1. **Install CPU-only PyTorch through uv** with an explicit PyTorch CPU index, and list `torch` and `torchvision` directly in the `ingest` extra so the pin is unambiguous. Default PyPI `torch` on Linux pulls CUDA 13 wheels; the CPU wheel avoids them.
2. **Use `docling-slim[format-pdf,models-local]`** instead of `docling`. The `docling` package is `docling-slim[standard]`, which adds RapidOCR (with full `opencv-python`), Office/HTML/email formats, the CLI, and more that we do not need.
3. **Turn OCR off** for born-digital scientific PDFs. OCR is the most expensive stage on CPU. Keep the table structure model on; benchmark `FAST` against `ACCURATE`. Keep the default Heron layout model and all enrichments off.
4. **Set the thread budget explicitly** (`OMP_NUM_THREADS` / `DOCLING_NUM_THREADS` equal to the pod CPU limit). The default is 4 threads.
5. **Bake the model weights into the image** (layout + TableFormer, about 0.5 GB) and point `DOCLING_ARTIFACTS_PATH` at them. The worker then needs no network access to Hugging Face and works on a read-only filesystem.
6. **What the published numbers say:** with OCR off, CPU throughput is about 0.7–1.3 s per page on 8–16 threads. With OCR on, it is about 3 s per page on average. Our latency targets (PRD §11) need about ≤ 1.2 s per page for Docling, so they are reachable only with OCR off.
7. **Image size:** the official CPU-only Docling Serve image is 4.4 GB (the default CUDA image is 8.7 GB on amd64). A slim worker should come out well below that, roughly 2 GB. This is an estimate; #28 measures it.

## Installing CPU-only PyTorch with uv

Docling's install guide gives exactly this for uv users ([Docling installation](https://docling-project.github.io/docling/getting_started/installation/)):

```toml
[[tool.uv.index]]
name = "pytorch-cpu"
url = "https://download.pytorch.org/whl/cpu"
explicit = true

[tool.uv.sources]
torch = [{ index = "pytorch-cpu" }]
```

The uv PyTorch guide uses the same pattern and also pins `torchvision` ([uv: Using uv with PyTorch](https://docs.astral.sh/uv/guides/integration/pytorch/)). It explains `explicit = true`: the index is used only for packages pinned to it, so everything else still comes from PyPI ([uv: Package indexes](https://docs.astral.sh/uv/concepts/indexes/)).

The uv docs do not say clearly whether an index pin in `tool.uv.sources` applies to a package that is only a transitive dependency. In our project `torch` comes in through Docling, so it is transitive. To avoid relying on that, add `torch` and `torchvision` directly to the `ingest` extra, then check that `uv.lock` resolves `torch` to a `+cpu` version from `download.pytorch.org/whl/cpu`.

Suggested change for #28 (in `backend/pyproject.toml`):

```toml
[project.optional-dependencies]
ingest = [
    "docling-slim[format-pdf,models-local]>=2.132",
    "torch>=2.2.2",        # pinned to the CPU index below
    "torchvision",
]

[tool.uv.sources]
torch = [{ index = "pytorch-cpu" }]
torchvision = [{ index = "pytorch-cpu" }]

[[tool.uv.index]]
name = "pytorch-cpu"
url = "https://download.pytorch.org/whl/cpu"
explicit = true
```

The CPU index also serves macOS and Windows wheels, so developer machines resolve with the same lock. The `--torch-backend` option is only in the `uv pip` interface, so it does not apply to `uv sync` ([uv PyTorch guide](https://docs.astral.sh/uv/guides/integration/pytorch/)).

### Why it matters for size (measured 2026-10-03)

| Wheel (torch 2.14.1, cp312, Linux) | Download | Installed |
|---|---|---|
| CPU, x86_64 (`download.pytorch.org/whl/cpu`) | 196 MB | 715 MB (sum of the wheel's file sizes) |
| CPU, aarch64 | 159 MB | not measured |
| PyPI default, x86_64 | 555 MB | plus CUDA dependencies |

The default PyPI `torch` 2.14.1 on Linux also requires `cuda-toolkit[...]==13.0.3`, `nvidia-cudnn-cu13` (553 MB wheel on x86_64), `nvidia-nccl-cu13`, `nvidia-cusparselt-cu13`, `nvidia-nvshmem-cu13`, and `triton` ([PyPI torch 2.14.1 metadata](https://pypi.org/pypi/torch/2.14.1/json)). The CPU wheel needs none of these.

## Which Docling package and extras

The repository publishes `docling-slim` (a minimal base, about 50 MB) with opt-in extras. `docling` is a meta package that depends on `docling-slim[standard]==<same version>` ([docling pyproject.toml](https://github.com/docling-project/docling/blob/main/pyproject.toml), [packages/docling/pyproject.toml](https://github.com/docling-project/docling/blob/main/packages/docling/pyproject.toml), [docling-slim README](https://github.com/docling-project/docling/blob/main/packages/docling-slim/README.md)).

| Extra | Contents | Needed? |
|---|---|---|
| `format-pdf` | `pypdfium2` + `docling-parse` | Yes |
| `models-local` | `torch`, `torchvision`, `docling-ibm-models` (layout, TableFormer), `accelerate`, `huggingface_hub` | Yes |
| `feat-ocr-rapidocr` / `feat-ocr-rapidocr-onnx` | `rapidocr` (+ `onnxruntime`) | Only if we enable OCR |
| `cli` | `typer`, `rich` (for `docling-tools`) | No. Download models from Python instead (see below). |
| `standard` (= `docling`) | All of the above plus RapidOCR, Office, web, LaTeX, email, iWork, chunking, extraction, service client, CLI | No |

`rapidocr` depends on `opencv_python` (the full build, not headless) ([PyPI rapidocr](https://pypi.org/pypi/rapidocr/json)). That is why Docling's own example Dockerfile installs `libgl1` and `libglib2.0-0` ([docling Dockerfile](https://github.com/docling-project/docling/blob/main/Dockerfile)). In `docling-ibm-models` 4.0.3, OpenCV is only an optional extra ([PyPI docling-ibm-models](https://pypi.org/pypi/docling-ibm-models/json)). So without OCR we may not need OpenCV or the system GL libraries at all. #28 should confirm this by running a conversion in the slim image.

## Pipeline options that matter (PdfPipelineOptions defaults)

Source: [`docling/datamodel/pipeline_options.py`](https://github.com/docling-project/docling/blob/main/docling/datamodel/pipeline_options.py) on main (2.132.0), plus the [pipeline options reference](https://docling-project.github.io/docling/reference/pipeline_options/).

| Option | Default | For born-digital scientific PDFs |
|---|---|---|
| `do_ocr` | `True` | **Set `False`.** OCR "significantly increases processing time" (docstring). In the default `OcrMode.DEFAULT` (= `PDF_AWARE_LAYOUT_REGIONS`) OCR skips clusters that contain only PDF text cells. It still runs on figures and other regions without a text layer, and it loads an OCR engine. |
| `ocr_options` | `OcrAutoOptions()` (engine picked at runtime) | Not used when OCR is off. The docstring warns: "RapidOCR has known issues with read-only filesystems". Our worker runs on a read-only filesystem (PRD §9.1). |
| `do_table_structure` | `True` | **Keep on.** Scientific papers have tables, and the saved output (D22) should have their structure. |
| `table_structure_options.mode` | `TableFormerMode.ACCURATE` | **Benchmark `FAST` against `ACCURATE`.** Tables cost 2–6 s each on CPU (see timings). A `TableStructureV2Options` (TableFormer V2) also exists but is not the default. |
| `table_structure_options.do_cell_matching` | `True` | Keep the default (it uses the PDF text cells). |
| `layout_options` | `LayoutObjectDetectionOptions` with preset `layout_heron_default` | **Keep Heron.** The Egret presets (`medium`, `large`, `xlarge`) aim at higher accuracy at more cost. |
| `do_formula_enrichment`, `do_code_enrichment`, `do_picture_classification`, `do_picture_description` | `False` | Keep off. Formula enrichment runs a VLM, and issue [#4444](https://github.com/docling-project/docling/issues/4444) reports CodeFormulaV2 in bfloat16 is about 7x slower on CPUs without native bfloat16. |
| `generate_page_images`, `generate_picture_images` | `False` | Keep off. `images_scale` stays 1.0. |
| `generate_parsed_pages` | `False` | Keep off. Turning it on "increases memory usage". |
| `force_backend_text` | `False` | Optional benchmark row: it uses the PDF's own text instead of layout predictions. |
| `document_timeout` | `None` | **Set it.** The docstring recommends a timeout for production. When it is exceeded, conversion returns `PARTIAL_SUCCESS` with `TIMEOUT` errors. Our value must fit the 15 min target for 500 pages, so the docstring's 90–120 s is too short for us. Use something like 600–900 s, and treat a partial result as a failure. |
| `accelerator_options` | `AcceleratorOptions(num_threads=4, device="auto")` | **Set `device="cpu"`** and set `num_threads` to the pod CPU limit. |
| `layout_batch_size`, `table_batch_size`, `ocr_batch_size` | 4 each | Benchmark 4 against 8 for layout. Larger batches use more memory. |
| `queue_max_size` | 100 | Lower it (e.g. 20) if peak memory on 500-page files is too high. |

Other settings:

- **PDF backend:** the default is `ThreadedDoclingParseDocumentBackend` (`PdfBackend.THREADED_DOCLING_PARSE`). `PYPDFIUM2` is the alternative ([document_converter.py](https://github.com/docling-project/docling/blob/main/docling/document_converter.py)). The 2024 technical report measured pypdfium as faster and lighter, but with "worse quality results, especially in table structure recovery" ([Docling Technical Report, arXiv:2408.09869](https://arxiv.org/abs/2408.09869)). Keep the default and add pypdfium as one benchmark row.
- **Global batch settings** (`docling.datamodel.settings`): `page_batch_size=4`, `doc_batch_size=1`, `doc_batch_concurrency=1`. The comment on the last one says it is experimental with "No benefit expected without free-threaded python" ([settings.py](https://github.com/docling-project/docling/blob/main/docling/datamodel/settings.py)). So one document per process; scale with pods, not threads.
- **Threads:** `AcceleratorOptions` reads `DOCLING_NUM_THREADS`, and falls back to `OMP_NUM_THREADS` ([accelerator_options.py](https://github.com/docling-project/docling/blob/main/docling/datamodel/accelerator_options.py)). Docling's Dockerfile says: "On container environments, always set a thread budget to avoid undesired thread congestion" and sets `OMP_NUM_THREADS=4`. The docs say the default is 4 CPU threads ([Advanced options](https://docling-project.github.io/docling/usage/advanced_options/)).
- **Size guards:** `converter.convert(source, max_num_pages=..., max_file_size=...)` ([Advanced options](https://docling-project.github.io/docling/usage/advanced_options/)). These can back up the PRD limits (≤ 500 pages, ≤ 50 MB) inside the worker.
- **Native pipeline:** `NativePdfPipelineOptions` runs no layout, OCR, or table model. It is fast, but its output has no reading order, headings, or tables (docstring), so it does not fit the saved output in D22. It could serve the first-pages step, but the PRD already plans a plain PDF text extractor for that step.

## Model weights in the image

- By default, models download on first use into `$HOME/.cache/docling/models`. You can prefetch them and point to them with `artifacts_path` or `DOCLING_ARTIFACTS_PATH` ([Advanced options](https://docling-project.github.io/docling/usage/advanced_options/)).
- `docling-tools models download` fetches layout, TableFormer, code_formula, picture_classifier, and RapidOCR by default ([cli/models.py](https://github.com/docling-project/docling/blob/main/docling/cli/models.py)). That is more than we need, and the CLI needs the `cli` extra. Use the Python function instead, in the build stage: `docling.utils.model_downloader.download_models(output_dir=..., with_layout=True, with_tableformer=True, with_code_formula=False, with_picture_classifier=False, with_rapidocr=False)` ([model_downloader.py](https://github.com/docling-project/docling/blob/main/docling/utils/model_downloader.py)).
- Weight sizes on Hugging Face (measured 2026-10-03): Heron layout `model.safetensors` 172 MB ([docling-layout-heron](https://huggingface.co/docling-project/docling-layout-heron)). TableFormer accurate 213 MB and fast 145 MB ([docling-models](https://huggingface.co/docling-project/docling-models)). Both TableFormer modes are in the same repository, so the total is about 530 MB.
- Docling's Dockerfile sets `HF_HOME=/tmp/` and `TORCH_HOME=/tmp/`. With a read-only root filesystem, mount an `emptyDir` at `/tmp`. Also set `HF_HUB_OFFLINE=1` so nothing tries the network, which matches our egress NetworkPolicy.

## Reported CPU timings and memory

| Source | Hardware | Settings | Result |
|---|---|---|---|
| [Docling GPU/perf docs](https://docling-project.github.io/docling/usage/gpu/) | Host of the RTX 5090 / RTX 5070 boxes, CPU only, **16 PyTorch threads** (CPU model not stated) | Standard pipeline, **no OCR**, one "PDF doc" | **1.5 pages/s** (≈0.67 s/page) and **1.2 pages/s** (≈0.83 s/page) |
| same | RTX 5090 GPU | Standard, with OCR | 1.6 pages/s (on GPU), so OCR costs a lot even with a GPU |
| [Docling paper, arXiv:2501.17887](https://arxiv.org/abs/2501.17887) §5 | AWS g6.xlarge, AMD EPYC 7R13, **8 threads, CPU only** | EasyOCR on, layout, TableFormer **fast**; 89 PDFs, 4,008 pages, 1,842 tables | **Median 0.79 s/page, mean 3.1 s/page**, 5th–95th percentile 0.6–16.3 s |
| same | same | Stage costs | OCR about 13 s per page where applied; layout 633 ms/page; TableFormer (fast) 1.74 s per table |
| same | x86 CPU and M3 Max | OCR off | "Disabling OCR saves 60% of runtime on the x86 CPU and the M3 Max SoC" → mean about **1.2 s/page** on 8 threads |
| [Docling Technical Report, arXiv:2408.09869](https://arxiv.org/abs/2408.09869) (v1, 2024; older versions) | Intel Xeon E5-2690 | 225 pages (arXiv + Redbooks), docling-parse backend | 0.60 pages/s on 4 threads, 0.92 pages/s on 16 threads |
| same | M3 Max, 4 threads | docling-parse vs pypdfium backend | 1.27 vs 2.18 pages/s; **peak memory 6.20 GB vs 2.56 GB** |
| same | "standard CPU" | TableFormer | "Typical tables require between 2 and 6 seconds"; EasyOCR "upwards of 30 seconds per page" on CPU |

Memory signals from the issue tracker (user reports; maintainers have not confirmed a cause):

- [#2788](https://github.com/docling-project/docling/issues/2788) (open): RSS grows over many successive conversions in one process. A maintainer could not reproduce it on macOS and suggested it may be a measurement effect. Users on Linux/Kubernetes report residual memory after CPU conversions and pods crashing.
- [#2786](https://github.com/docling-project/docling/issues/2786) (open): one user reports about 3x memory on a 7,000-page PDF in 2.60 compared with 2.16.
- [#2779](https://github.com/docling-project/docling/issues/2779), [#2540](https://github.com/docling-project/docling/issues/2540): OOM kills on large PDFs. A recent comment on #2788 reports a 1,100+ page PDF crashing a 12 GB / 2 vCPU container.
- No primary source gives a current peak-RSS figure for a 500-page born-digital PDF. **#28 must measure it.**

### What the timings mean for our targets

PRD §11 asks: new content searchable at p95 ≤ 5 min for ≤ 200 pages, and ≤ 15 min for 201–500 pages. Embedding and other steps also take time, so Docling needs roughly **≤ 1.2 s/page** (200 pages in about 4 min, 500 pages in about 10 min). The published CPU numbers with OCR off (0.67–1.2 s/page on 8–16 threads) are at or just inside that budget. With OCR on (about 3.1 s/page mean) they are far outside it. Table-heavy papers will be slower than the mean. These numbers are for one document on a dedicated machine. Queueing behind other uploads adds to them, so replica count matters as much as per-page speed.

## Image size

- Official images ([docling-serve README](https://github.com/docling-project/docling-serve)): `docling-serve-cpu` (torch from the CPU index) is **4.4 GB**. The default `docling-serve` image is 8.7 GB on amd64. `docling-serve-cu128` is 11.4 GB. These images include everything (the full extras, the service, and more models).
- Our slim worker, estimated: `python:3.12-slim` (~0.13 GB) + CPU torch (0.72 GB installed) + transformers, scipy, numpy, docling-parse, pypdfium2, and other dependencies (a few hundred MB) + baked weights (~0.53 GB). That is **about 1.8–2.5 GB uncompressed**. This is an estimate; #28 records the real `docker image ls` size.

## Recommended settings to benchmark in #28

Hold these fixed: `docling-slim[format-pdf,models-local]` 2.132.x, CPU torch, `device=cpu`, all enrichments off, `generate_*` off, Heron layout, weights baked in, `HF_HUB_OFFLINE=1`. Run one document per process. Use seed-corpus PDFs with a mix of page counts (about 10, 50, 200, and 500 pages) and table density. Report s/page (median, mean, p95), peak RSS, and RSS after 20 successive conversions in one process.

| Run | OCR | TableFormer | Backend | Threads (= CPU limit) | Purpose |
|---|---|---|---|---|---|
| A (candidate default) | off | FAST | docling-parse (default) | 4 | Baseline at the documented default thread count |
| B | off | ACCURATE | docling-parse | 4 | Table quality vs cost |
| C | off | FAST | docling-parse | 8 | Thread scaling, to choose the pod size |
| D | off | FAST | pypdfium2 | 4 | Speed and memory vs quality |
| E | on (RapidOCR, default mode) | FAST | docling-parse | 4 | Measure the cost of OCR if we ever need it |

Also record:

- Image size, and whether the image without OpenCV/libGL runs the conversion.
- `layout_batch_size` 4 against 8 on run C.
- Peak RSS on the 500-page file. Use it to set the memory request and limit. Start the benchmark with a limit of 8 GiB.
- Whether RSS keeps growing across conversions (#2788). If it does, recycle the worker process after N documents, or run each extraction in a child process.
- Optionally run A on an arm64 (Graviton) node: a CPU torch aarch64 wheel exists, and docling-serve publishes arm64 CPU images.

Leaning (to confirm with #28): **run A or B**, depending on the table quality difference, with OCR off. Scanned PDFs (no text layer) are detected in the first-pages step. Per PRD §5 non-goals there is no OCR quality guarantee for them.
