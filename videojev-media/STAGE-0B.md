# Stage 0b: Ubuntu full stack and matched Windows comparison

Run date: 2026-10-30. **Stage 0b passed in Ubuntu.** Ubuntu completed both real
sample benchmarks. Windows SDPA encoded both samples but ran out of memory
on the first grounding query for each, at the identical context and sampling
settings. The remaining Stage 1 checks have not been started.

## Environments and isolation

The creator's revised build-plan section 4 selects Ubuntu WSL2 for the model,
with FlashAttention 2 and causal-conv1d. The Windows SDPA venv is the baseline.
All new repository files are under `videojev-media/`, on `feat/videojev-media`.
The original project, shared media-search code and other worktrees are unchanged.

Ubuntu 26.04.1 LTS runs under WSL2, kernel 6.18.54.1-microsoft-standard-WSL2.
The GPU is the same RTX 5070 Ti, driver 610.88, with 16,303 MiB reported VRAM.
The Linux environment lives at `/home/caesar/videojev/venv`, outside the repo.
It uses uv-managed CPython 3.12.15, PyTorch 2.8.0+cu128, torchvision 0.23.0+cu128,
Triton 3.4.0, Transformers 5.14.1, PyAV 18.1.0, flash-linear-attention 0.4.2
and fla-core 0.4.2. The Windows venv's packages were not installed or upgraded.

Native extensions are the official Linux x86-64 wheels for Python 3.12,
PyTorch 2.8, CUDA 12 and the matching C++11 ABI:

- [FlashAttention 2.8.3.post2 release](https://github.com/Dao-AILab/flash-attention/releases/tag/v2.8.3.post2).
  Wheel SHA-256: `61ab39b7038d6a05cb97664f3481a92ced300d11aa14529ae3b675300a99f5e6`.
- [causal-conv1d 1.7.0 release](https://github.com/Dao-AILab/causal-conv1d/releases/tag/v1.7.0).
  Wheel SHA-256: `a1fcd5d022b67ddfc9e1c291f890004c1c081a03d66b532f6eebe31219168e0e`.

uv verified the wheel hashes. Both extensions passed direct BF16 CUDA calls
on this `sm_120` GPU, and `uv pip check` passed for all 60 Linux packages.
The complete environment is recorded in
[requirements-wsl.lock.txt](requirements-wsl.lock.txt).
Ubuntu received `build-essential` and `ca-certificates` for Triton compilation.
No Linux display driver or system-wide Windows package was installed.
The pinned Linux lock can be installed into a separate Python 3.12 venv with
`uv pip install --python <venv-python> -r requirements-wsl.lock.txt`.

The model, tokenizer, demo and source revisions are unchanged from Stage 0.
The model snapshot was copied into Ubuntu's filesystem, and the six Python
modules were checked against the previously reviewed files before execution.
No model code was patched. Native Linux files avoid `/mnt/c` media reads during
the timed preprocessing. The Windows run reads the matching files on C:.

## Inputs and method

[benchmark-inputs.json](benchmark-inputs.json) records the complete input
manifest, sample hashes and 40 fixed grounding questions.
The source is the cached 480p video
[Resident Evil 4 Remake Longplay, part 2](https://www.youtube.com/watch?v=xxloZbzqVIk),
by Game Archives. No project media was changed or committed.

| Sample | Original source range | Sampling | Frames |
| --- | --- | --- | --- |
| 30-minute segment | 10:00–40:00 | 0.2 fps | 360 |
| 2-minute excerpt | 20:00–22:00 | 2 fps | 240 |

Both samples are 854×480 video-only H.264 with every frame a keyframe. The
files have identical SHA-256 hashes in Windows and Ubuntu. Windows ffmpeg
sampling took 12.74 s and 1.10 s respectively, measured on a repeat with the
source already cached.

Both processes use BF16, `cuda:0`, context 32,768, `groups_per_chunk=16`,
and two OMP/MKL/OpenBLAS threads, following the authors' environment defaults.
The packages in the Windows venv remain unchanged; these thread settings
apply only to the benchmark process. The environments run sequentially on
the GPU, with ComfyUI confirmed inactive on the Windows host before launch.

[benchmark.py](benchmark.py) accepts a job JSON and writes results plus a
20-second heartbeat. The Windows launcher uses a hidden console and redirected
logs. Ubuntu is invoked through `wsl -d Ubuntu -- <venv-python> benchmark.py job.json`;
Windows paths used by the Ubuntu worker are converted to `/mnt/c/...` paths.

CUDA synchronization brackets each measurement:

- Preprocessing is reported separately from vision encoding.
- Encoding has one warm-up and two measured repeats; the table uses their median.
- Single-question latency is the median of six calls, two each for three queries,
  after a warm-up. Every question uses the same encoded features for that window.
- The complete 40-question call has a warm-up and then one measured repeat.
  VideoJev groups queries within context; the batch cost includes its grouping
  and prompt construction. Amortized time is that measured cost divided by 40.
- Allocator caches are cleared outside the timed sections between samples.
  Peak memory covers the complete sample test, including warm-ups, with the
  loaded model retained. Allocated/reserved values are PyTorch allocator peaks,
  excluding memory allocated outside PyTorch.

Real-footage outputs were used only to exercise inference for timing. No
accuracy judgment, threshold calibration, names test, absent-query test,
feature save/reload test, timestamp-alignment test or context sweep was run.

## Stage 0b demo

Both current processes used the same pinned 10-second spaghetti demo, 2 fps,
context 8,192 and the README's grounding and choice questions.

| Measurement | Windows SDPA | Ubuntu FA2 + causal-conv1d |
| --- | --- | --- |
| Processor/model load and inference preparation | 10.52 s | 8.95 s |
| First inference with a fresh kernel cache | 47.16 s | 37.49 s |
| Warm inference, both questions | 0.736 s | 0.683 s |
| Grounding interval | 3–10 s | 3–10 s |
| Choice | A. Pasta. | A. Pasta. |
| Pasta probability | 0.9999175072 | 0.9999173880 |
| Peak allocated / reserved, including model load | 10,281.72 / 10,646 MiB | 9,748.54 / 9,922 MiB |

The interval and answer match the pinned README exactly in both environments.
Ubuntu's model, text and vision all reported `flash_attention_2`; Windows
reported `sdpa`. The warm demo differs by only about 0.05 seconds. The real
workload, rather than that tiny demo, exposes the Windows capacity failure.
Ubuntu's initial Triton compilation logged macro-redefinition warnings and
completed successfully; no model code changes were needed.

## Matched sample results

| Measurement | 30-minute sample, Windows | 30-minute sample, Ubuntu | 2-minute sample, Windows | 2-minute sample, Ubuntu |
| --- | --- | --- | --- | --- |
| Preprocessing | 2.49 s | 2.60 s | 1.77 s | 2.46 s |
| Warm vision encoding, median of two | 1.72 s | 1.57 s | 1.67 s | 1.64 s |
| Video tokens | 25,920 | 25,920 | 25,080 | 25,080 |
| Warm single-question median | Unavailable: OOM | 3.88 s | Unavailable: OOM | 3.41 s |
| Warm 40-question call | Unavailable: OOM | 147.67 s | Unavailable: OOM | 87.60 s |
| Amortized seconds/question in that call | Unavailable: OOM | 3.69 s | Unavailable: OOM | 2.19 s |
| Query groups in the 40-question call | Not reached | 20 (2 questions each) | Not reached | 8 (5 questions each) |
| Peak allocated / reserved | 16,242.20 / 19,644 MiB, failed | 13,376.90 / 16,474 MiB | 15,430.08 / 18,520 MiB, failed | 13,394.52 / 17,230 MiB |

Windows failed during the single-question warm-up, before there could be a
valid warm question timing or 40-question timing:

- Long sample: `torch.nn.functional.scaled_dot_product_attention` requested
  an additional **52.53 GiB**. The error reported 15.86 GiB already allocated.
  A repeat of the failed case, with failure-side peak recording, measured
  16,242.20 MiB peak allocation and 19,644 MiB peak reservations. No parameters
  were changed. The encoding row above uses the original run (the repeat was 1.70 s).
- Short sample, run independently in a fresh process: the same SDPA function
  requested an additional **44.38 GiB**. The recorded peak allocation before
  failure was 15,430.08 MiB, with peak reservations of 18,520 MiB.

No context reduction, kernel forcing, model patch, package change or Windows
fallback was attempted. These failures are the result of the requested fixed
comparison, and a finite Windows full-scan estimate cannot be supported.

The Ubuntu active allocation peaks were about 13.06–13.08 GiB. Its reserved
peaks exceeded the card's dedicated capacity. Those are allocator reservation
statistics, not proof of dedicated residency: Windows GPU counters showed
about 2.4 GiB of shared GPU memory assigned to a VM worker in one observation
during the Ubuntu run. The scan completed, but memory pressure at context
32,768 remains a material limit; this test does not establish a safe maximum.

Full Ubuntu measurements are in
[wsl-benchmark-result.json](wsl-benchmark-result.json). Windows's original
long-sample failure and independent short-sample run are in
[windows-long-benchmark-result.json](windows-long-benchmark-result.json) and
[windows-short-benchmark-result.json](windows-short-benchmark-result.json).
The repeated long-case peak capture is in
[windows-long-peak-result.json](windows-long-peak-result.json).

## Three-hour estimates

There are six 30-minute windows or ninety 2-minute windows in three hours.
For 40 questions on every window, the estimate is:

```text
one model load + windows × (ffmpeg sampling + preprocessing + warm encoding + warm 40-question batch)
```

The sampling measurements are shared Windows costs because the approved
architecture keeps sampling/orchestration on Windows. The raw worker estimates
exclude ffmpeg sampling; the comparison adds it explicitly.

| Three-hour scan, 40 questions on every window | Windows SDPA | Ubuntu full stack |
| --- | --- | --- |
| Coarse pass: six 30-minute windows at 0.2 fps | Cannot run at these settings: OOM | **996.43 s / 16.61 min** |
| Full fine scan: ninety 2-minute windows at 2 fps | Cannot run at these settings: OOM | **8,360.99 s / 139.35 min / 2.32 h** |

Ubuntu's coarse calculation is `8.95 + 6 × (12.74 + 2.60 + 1.57 + 147.67)`
seconds, using unrounded measurements for the result. The fine calculation is
`8.95 + 90 × (1.10 + 2.46 + 1.64 + 87.60)` seconds. Encoding happens once per
window, shared by all 40 questions. Measured batched query cost dominates.

The coarse estimate covers the first full-video pass. The fine estimate assumes
all footage is scanned at 2 fps with all 40 questions. A three-round pipeline
total cannot be established from these two samples: it depends on how much
footage and how many questions survive each round. Round 2 and candidate
confirmation have not been timed. Source download, new compilation, model
restarts and feature-cache I/O are also outside the warm scan estimates.

## Validation and stopping point

The readiness and shared-encoding estimate tests passed in both Python 3.12
environments. Source/sample hashes, result structure, settings and estimate
calculations were checked. All 44 Windows package versions match the inventory
captured before setup and benchmarking. No Windows venv files were installed
or upgraded, and benchmark kernel/module caches were kept outside that venv.

Stage 0b and the requested comparison are complete. Stop here: no other Stage 1
model checks, source indexing, needs generation or project edits were performed.

New files are dual licensed MIT OR Apache-2.0 under the repository licenses.
