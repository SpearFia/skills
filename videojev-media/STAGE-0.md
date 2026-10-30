# VideoJev media search: Stage 0

Status: **passed on native Windows with SDPA**. Recorded 2026-10-30.
The pinned README demo returned sensible answers and fit on the RTX 5070 Ti.
This follows the creator's revised section 4. Stopped at the Stage 0 gate;
Stage 1 has not started.

## Scope and isolation

- Build plan: `D:\SpearFia\plans\videojev-media-search-build-plan.md`.
- Worktree: `C:\dev\spearfia\skills-videojev`.
- Branch: `feat/videojev-media`.
- Base: `origin/feat/media-search-sources`, commit
  `86ce40c0a8871a32a6562749171f6b62fb347218`.
- PR [SpearFia/skills#4](https://github.com/SpearFia/skills/pull/4) was open
  when the base was selected.
- Stage 0 changes reach this report, `config.json`, the isolated demo runner,
  its readiness test, saved results and resolved Windows dependency lock in `videojev-media/`.
  There are no changed callers, fixtures, exports or shared media-search code.
- The original skills checkout, Gemini pilot, Spear Fia checkout and cwi-003
  project received no file edits. Model weights and the upstream 10-second demo
  use the C: cache outside the repo. No push, PR creation or merge was performed.

## Machine checks

| Check | Observed result |
| --- | --- |
| GPU | NVIDIA GeForce RTX 5070 Ti |
| Driver | 610.88 |
| VRAM total | 16,303 MiB |
| VRAM free before environment setup | 14,711 MiB |
| VRAM free reported by CUDA before model loading | 15,037 MiB |
| C: free before environment setup | 74,116,759,552 bytes, about 69.0 GiB |
| Windows Python | Isolated uv-managed CPython 3.12.15 |
| WSL | Not used |
| Tools | git, gh, ffmpeg, ffprobe and uv available |
| ComfyUI queue before demo | 0 running, 0 pending |
| CUDA capability reported by PyTorch | 12.0 (`sm_120`) |

The runner checks the ComfyUI queue and requires at least 12,288 MiB free VRAM
before loading the model. That floor is provisional, not a measured minimum.
`config.json` starts pipeline context at 32,768 as the plan requests; the README
demo uses 8,192. Maximum context and feature sizes belong to Stage 1.

## Source pins and code review

The exact pins live in [config.json](config.json). Both model weights and
remote code must use its explicit revisions when loaded with Transformers.

- [VideoJev repository at the reviewed commit](https://github.com/MCG-NJU/VideoJev/tree/7f8b38aa7df67721303cdc61f06d8435f3c7db89).
- [VideoJev-4B at the reviewed revision](https://huggingface.co/ZhuYuhan/VideoJev-4B/tree/b614f1a6248ba1f169cd3bec9e4392758b566e5d).
- The demo dataset revision is also pinned from the upstream README.
- Source checkout, detached at the pinned commit:
  `C:\Users\caesa\AppData\Local\SpearFia\cache\videojev\source`.
- Hugging Face code and metadata, fetched at the pinned revision:
  `C:\Users\caesa\AppData\Local\SpearFia\cache\videojev\hf-audit\b614f1a6248ba1f169cd3bec9e4392758b566e5d`.

Read all six Python modules below and `videojev_hf/__init__.py`. Compared
the six downloaded modules with the source checkout: **6/6 match**, after
normalizing Git's Windows CRLF checkout to LF. These hashes are SHA-256 of
the downloaded Hugging Face bytes.

| File | SHA-256 |
| --- | --- |
| `configuration_videojev.py` | `b91c4bc181fe31b8297a80429f036782dc3331a3da84f1fca1203b6bf1413127` |
| `modeling_videojev.py` | `35ab5861f3337f3e51e79959551dd341b47a78cb19c124a22fcd08bedf4ea2e1` |
| `processing_videojev.py` | `001281d45e61db9baa31bd3be210969f35bf2735773f1819195a2b1a6e70227f` |
| `videojev_moe.py` | `6421edb75def784c77e08f61a04ce4d3beed0bfcae000256cb9c074d515c80db` |
| `videojev_temporal.py` | `68b19275ef5657e54188d782c6531f466681d3b3fa8b77329e5c20a1631decab` |
| `videojev_video.py` | `0c5f93f7ac4e7da402217491e000d7b6b2f36fa8b010462f4e0bc63ef87c8c3a` |

Review findings:

- These modules contain model configuration, preprocessing, scoring, video
  decoding and optional MoE helpers. No network downloads, shell execution,
  `eval` or pickle deserialization occur in these six modules. Third-party
  dependencies have not been audited.
- Model construction sets `FLA_INTRACARD_CP=0`. The dense 4B model does not
  invoke the optional XTuner grouped-expert installation.
- `prepare_for_inference()` promotes the vision encoder and head to FP32;
  BF16 weight size alone cannot establish whether inference fits.
- CUDA forward passes packed-sequence arguments to the language model.
  The revised plan requires testing those arguments with SDPA, without changing
  the model code.
- `read_video()` decodes the complete input with PyAV, so later rounds must
  receive sampled windows. Its frame cap can lower fps; later code must check it.
- Grounding's decoder always produces a span, even for all-negative scores.
  Later stages must decode `probabilities` themselves as the plan specifies.

## Native Windows environment

The environment and uv-managed interpreter are outside the repo, under
`C:\Users\caesa\AppData\Local\SpearFia\cache\videojev`:

- Environment: `venv-win` (interpreter: `venv-win\Scripts\python.exe`).
- Python installation: `python`.
- uv download cache: `uv`; Hugging Face cache: `hf`; remote code cache:
  `hf-modules`; Triton cache: `triton`.
- Job, output and logs: `stage0-job.json`, `stage0-result.json`,
  `stage0-stdout.log`, `stage0-stderr.log`.

| Package | Installed version |
| --- | --- |
| PyTorch | 2.8.0+cu128 |
| torchvision | 0.23.0+cu128 (processor's image/video dependency) |
| Transformers | 5.14.1 |
| Triton Windows | 3.4.0.post21 (module reports 3.4.0) |
| flash-linear-attention / fla-core | 0.4.2 / 0.4.2 |
| PyAV | 18.1.0 |
| accelerate / safetensors | 1.15.0 / 0.8.0 |
| numpy / pillow | 2.5.4 / 13.0.0 |
| flash-attn / causal-conv1d | Absent, as requested |

The complete resolved environment is in
[requirements-windows.lock.txt](requirements-windows.lock.txt). Install it into
a separate Python 3.12 venv with `uv pip install --python <venv-python> -r
videojev-media/requirements-windows.lock.txt`.

The runner uses `attn_implementation="sdpa"`, BF16 on `cuda:0`,
`prepare_for_inference()`, and the exact README questions, fps, frame cap and
demo context. It verifies downloaded Python files against the previously
reviewed copies before loading remote code. No upstream model code is patched.

Run `demo.py <job.json>` with the environment's interpreter. The job contains
`cache_dir` and `result_path` paths; all other settings come from `config.json`.
The demo was launched with `Start-Process -WindowStyle Hidden`, redirected logs
and unbuffered output. Results and failures are saved as JSON.

## Demo gate results

One cold-process run completed successfully. The gate compares the choice
with the README's `A. Pasta.` and the grounding with its interval `[3, 10]`
seconds. The runner requires a matching choice and temporal IoU of at least
0.5 as a sensible demo match; this run matched the interval exactly (IoU 1.0).

| Measurement | Result |
| --- | --- |
| Pinned demo and model download | 111.68 s |
| Processor/model load and inference preparation, after download | 16.82 s |
| First inference, both questions | 47.78 s |
| Whole process, including imports and downloads | 188.09 s |
| Peak PyTorch allocated VRAM, load plus inference | 10,281.72 MiB (10.04 GiB) |
| Peak PyTorch reserved VRAM, load plus inference | 10,646.00 MiB (10.40 GiB) |
| Attention implementation: model / text / vision | SDPA / SDPA / SDPA |

CUDA synchronization brackets load and inference timing. Peak memory values
come from PyTorch's allocator and exclude allocations outside that allocator.
The first inference may include kernel compilation; its share was not profiled.

| Output | Windows SDPA | Pinned README |
| --- | --- | --- |
| Grounding: woman in green eats pasta | 3.0–10.0 s | 3.0–10.0 s |
| Choice: what is she eating? | A. Pasta. | A. Pasta. |
| Probability of Pasta | 0.9999175072 | 0.9999161959 |

The ten grounding probabilities differ from the published FlashAttention
output by a maximum of 0.05126035 and a mean absolute difference of 0.00891772.
Both full probability arrays and all recorded metrics are saved in
[demo-result.json](demo-result.json).

The CUDA packed-sequence arguments caused no runtime errors under SDPA. The
vision encoder also loaded and ran with SDPA. Transformers logged its expected
torch fallback warning for the omitted fast-path library. FlashAttention and
causal-conv1d remain uninstalled; the pinned model source is unchanged.

This smoke check establishes fit and sensible answers for the 10-second demo
at context 8,192. It does not establish production grounding accuracy, maximum
context, warm inference speed or throughput for three-hour sources. No long
source or Stage 1 checks were run. Pipeline context 32,768 remains unvalidated.

## Validation completed

- Parsed the config and checked all four revisions are exact 40-character hashes.
- Verified all six code comparisons and every recorded SHA-256 hash.
- Rechecked the six downloaded runtime modules against the reviewed copies
  before executing them; the upstream checkout remains clean.
- `uv pip check`: all 44 installed packages compatible.
- Readiness unit test passed in the Python 3.12 environment: accepts an idle
  queue at the VRAM floor; rejects active/pending jobs, low VRAM and malformed queues.
- Saved-result checks: both README answers match exactly; model, text and
  vision attention all report SDPA.
- Markdownlint passed with zero issues. Git whitespace checks passed.
- Confirmed the worktree has no changes outside `videojev-media/` against its base.

## License

New files in this directory are dual licensed under MIT OR Apache-2.0;
see the repository's `LICENSE-MIT` and `LICENSE-APACHE`.
