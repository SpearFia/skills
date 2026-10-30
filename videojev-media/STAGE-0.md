# VideoJev media search: Stage 0

Status: **pending; blocked on creator-installed WSL**. Recorded 2026-10-30.
The README demo has not run. Stage 1 has not started.

## Scope and isolation

- Build plan: `D:\SpearFia\plans\videojev-media-search-build-plan.md`.
- Worktree: `C:\dev\spearfia\skills-videojev`.
- Branch: `feat/videojev-media`.
- Base: `origin/feat/media-search-sources`, commit
  `86ce40c0a8871a32a6562749171f6b62fb347218`.
- PR [SpearFia/skills#4](https://github.com/SpearFia/skills/pull/4) was open
  when the base was selected.
- Stage 0 changes reach only this report and `config.json` in `videojev-media/`.
  There are no changed callers, fixtures, exports or shared media-search code.
  The model's remote code was downloaded for inspection, without executing it.
- The original skills checkout, Gemini pilot, Spear Fia checkout and cwi-003
  project received no file edits. No project media or model weights were downloaded.
  No push, PR creation or merge was performed.

## Machine checks

| Check | Observed result |
| --- | --- |
| GPU | NVIDIA GeForce RTX 5070 Ti |
| Driver | 610.88 |
| VRAM total | 16,303 MiB |
| VRAM free at check | 14,730 MiB |
| C: free at check | 74,161,098,752 bytes, about 69.1 GiB |
| Windows Python | 3.11 and 3.14; no 3.12 |
| WSL | Both `wsl --status` and `wsl --list --verbose` report not installed |
| Tools | git, gh, ffmpeg, ffprobe and uv available |
| Inference runs | 0 |

Free VRAM is a snapshot; ComfyUI job state was not checked. No VRAM floor,
context limit, inference time or feature size has been measured yet.
`config.json` starts pipeline context at 32,768 as the plan requests;
the upstream demo uses 8,192. Neither is a validated machine limit.

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
  Retain FlashAttention 2 for the runtime check.
- `read_video()` decodes the complete input with PyAV, so later rounds must
  receive sampled windows. Its frame cap can lower fps; later code must check it.
- Grounding's decoder always produces a span, even for all-negative scores.
  Later stages must decode `probabilities` themselves as the plan specifies.

## Resume Stage 0

The build plan section 4 explicitly says: "The creator runs `wsl --install`."
Installing WSL changes Windows, so this step is reserved for the creator.
In an elevated PowerShell window, run:

```powershell
wsl --install -d Ubuntu
```

Restart if requested and finish Ubuntu's first-run username/password setup.
Then resume Stage 0 here. The remaining work is:

1. Verify WSL2 Ubuntu and CUDA visibility; create a Python 3.12 venv in the
   Linux filesystem. Keep environment/model caches on C: via WSL storage.
2. Install the upstream inference stack: PyTorch 2.8 / CUDA 12.8, Triton 3.4,
   `transformers==5.14.1`, `av==18.1.0`, `flash-linear-attention==0.4.2`,
   `fla-core==0.4.2`, FlashAttention 2, causal-conv1d, accelerate, safetensors,
   numpy and pillow. Record the resolved runtime versions after installation.
3. Check ComfyUI is idle and add the required free-VRAM guard before model
   execution. Use the pinned revisions for both processor and model code.
4. Run the pinned README's 10-second spaghetti demo, with grounding and choice
   questions, BF16, `cuda:0`, FlashAttention 2, 2 fps and context 8,192.
5. Record actual outputs, load/inference times and peak VRAM, then report
   the Stage 0 gate. Stop there before Stage 1.

The gate remains pending until that demo succeeds on this GPU. RTX 5070 Ti
compatibility and memory fit are unverified; no substitute model is authorized.

## Validation completed

- Parsed the config and checked all four revisions are exact 40-character hashes.
- Verified all six code comparisons and every recorded SHA-256 hash.
- Markdownlint passed with zero issues. Git whitespace checks passed.
- Confirmed the worktree has no changes outside `videojev-media/` against its base.

## License

New files in this directory are dual licensed under MIT OR Apache-2.0;
see the repository's `LICENSE-MIT` and `LICENSE-APACHE`.
