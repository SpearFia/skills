# Stage 1: grounding accuracy, bounded context and timestamp alignment

Completed 2026-10-30. All **45 query/source/context combinations** completed in
Ubuntu with the pinned model, FlashAttention 2 and causal-conv1d. No context
above 32,768 was used. No features were saved to disk. **Stopped before Stage 2.**

The numerical gate is complete; creator judgment of the contact sheets is
still required. These scores are model confidence, not measured accuracy.

## Review artifacts

- [Open the contact-sheet gallery](D:/SpearFia/library/jev/stage1-2026-10-30/review.html):
  nine sheets, confidence plots, all query metrics and source-video timestamp links.
- [Burned-timecode alignment sheet](D:/SpearFia/library/jev/stage1-2026-10-30/alignment.jpg).
- [Full per-query measurements](stage1-measurements.md): max, mean, p95,
  seconds above 0.50, time and peak allocated/reserved VRAM for every query.
- [Raw probabilities and records](stage1-results.json), [input manifest](stage1-inputs.json).
- [Selected-frame alignment map](stage1-alignment-inputs.json).

Each query row in a contact sheet shows three strongest non-adjacent score
cells, with both input frames per cell. Low-scoring rows are still shown for
inspection; they are not labeled as accepted matches. The sheets show source
pictures, and state the model's actual resized geometry in the header.
The 0.50 line is a diagnostic starting threshold, not a validated acceptance rule.

## Inputs

| Test source | Original source window | Sampling |
| --- | --- | --- |
| [John Hunts Down Viggo](https://www.youtube.com/watch?v=s6ySzbScPvc) | 04:00–06:00 | 2 fps, 240 frames |
| [Top Down Mansion Fight](https://www.youtube.com/watch?v=tfJShk6hmqM) | 03:00–05:00 | 2 fps, 240 frames |
| [Resident Evil 4 longplay, part 2](https://www.youtube.com/watch?v=xxloZbzqVIk) | 10:00–40:00 | 0.2 fps, 360 frames |

Both John Wick proxies are 854×480. The existing `qc.crop` measured a stable
854×356 crop for the driving source; it returned no stable whole-source crop
for the fight source, so that source retained its full frame. The long source
is the same cached 480p video used in Stage 0b; this tests one 30-minute window,
not its complete 7.4-hour duration. No original project media was modified.

Queries were `A car is visible.`, `People are fighting.`, the two exact driving
phrases requested by the creator, and `A giraffe walks across a field.` as the
deliberately absent control. The driving window also contains a fight early on;
it is not a fight-negative control. The mansion's overhead interior provides
a difficult negative for cars and driving.

## Scores

All values below are **maximum cell probabilities**. Means, p95 values,
temporal coverage and full curves are supplied separately so a single peak
does not hide false positives or missed footage.

| Source | Context | Car | Fight | John Wick drives | Man in black suit drives | Absent giraffe |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Wick driving | 8,192 | 0.9825 | 0.8852 | 0.9867 | 0.9841 | 0.0258 |
| Wick driving | 16,384 | 0.9830 | 0.9586 | 0.9902 | 0.9883 | 0.0051 |
| Wick driving | 32,768 | 0.9821 | 0.9700 | 0.9900 | 0.9853 | 0.0036 |
| Wick fight | 8,192 | 0.9195 | 0.9815 | 0.7812 | 0.5684 | 0.0669 |
| Wick fight | 16,384 | 0.9252 | 0.9835 | 0.7398 | 0.4907 | 0.1203 |
| Wick fight | 32,768 | 0.2095 | 0.9857 | 0.0848 | 0.0800 | 0.0088 |
| Long gameplay | 8,192 | 0.0744 | 0.8971 | 0.1478 | 0.7971 | 0.2913 |
| Long gameplay | 16,384 | 0.0296 | 0.9657 | 0.5963 | 0.7247 | 0.0316 |
| Long gameplay | 32,768 | 0.0200 | 0.9441 | 0.0076 | 0.5752 | 0.0447 |

The main accuracy findings in the displayed samples:

- The car-positive peaks stay around 0.98 at every context. That alone would
  hide a major difference: the overhead indoor fight is scored as a car at
  0.9195/0.9252 at 8k/16k. Its maximum falls to 0.2095 at 32k. The sheets show
  the same indoor scene, without a car, at these false peaks.
- The fight-positive peaks remain high, but the amount marked above 0.50
  changes substantially. On the driving window the fight query marks 58.75 s
  at 8k, 20.75 s at 16k and 16.75 s at 32k. On the mansion window it marks
  20.75, 33.75 and 15.75 s. A high maximum does not establish good coverage.
- Even 32k has a difficult false positive: the generic driving description
  reaches 0.5752 on the long video's ornate indoor carriage/statue at about
  27:50. The corresponding named query is 0.0076 at maximum over that window.
  Multiple-choice confirmation remains necessary to test in the later pipeline.
- The giraffe query never reaches 0.50, but its 8k long-window maximum of
  0.2913 would pass the proposed 0.20 coarse-screen threshold. One easy absent
  object does not validate thresholds for visually similar wrong events.

On this small sample, **keep 32,768 as the default for accuracy review**;
8k/16k speed gains come with clear car/driving false positives. This does not
establish dataset-wide precision, recall, or the acceptance target of 80%.
Creator review is needed before choosing a lower context or tuning thresholds.

## Names test

On the real driving window, naming John Wick changes the maximum only slightly:
0.9867 vs 0.9841 at 8k, 0.9902 vs 0.9883 at 16k and 0.9900 vs 0.9853 at 32k.
At 32k both phrases mark 49 seconds above 0.50.

The name also increases wrong driving scores inside the mansion at lower
contexts: 0.7812 vs 0.5684 at 8k, and 0.7398 vs 0.4907 at 16k. Conversely it
rejects unrelated game footage more strongly at 32k (0.0076 vs 0.5752).
There is no universal names win here. Retain both query formulations in the
evidence; do not make names a blanket rule based on the positive peak alone.

## Time and memory

Queries were timed individually after one per-window warm-up. CUDA was
synchronized around each measurement. Encoding is one measured call per
window/context and can include first-use geometry/kernel overhead; it is not
a repeated warm-encoding benchmark. Preprocessing includes prompt-budget checks
and any extra resize/decode attempt. The full measurements give each query's
time and peaks; this table shows the median query time and maximum query peaks.

| Source | Context | Preprocess s | Encode s | Median query s | Peak allocated / reserved MiB |
| --- | ---: | ---: | ---: | ---: | ---: |
| Wick driving | 8,192 | 1.235 | 0.983 | 0.880 | 10,173.5 / 10,464 |
| Wick driving | 16,384 | 1.529 | 0.673 | 1.633 | 11,013.1 / 11,572 |
| Wick driving | 32,768 | 1.954 | 1.535 | 3.375 | 12,793.3 / 13,756 |
| Wick fight | 8,192 | 2.503 | 0.399 | 0.894 | 10,191.8 / 10,520 |
| Wick fight | 16,384 | 1.534 | 0.698 | 1.674 | 11,043.9 / 11,580 |
| Wick fight | 32,768 | 2.407 | 1.959 | 3.385 | 12,827.2 / 13,794 |
| Long gameplay | 8,192 | 3.420 | 0.420 | 0.937 | 10,170.7 / 10,500 |
| Long gameplay | 16,384 | 4.161 | 0.740 | 1.935 | 11,256.2 / 11,860 |
| Long gameplay | 32,768 | 3.068 | 1.700 | 3.794 | 13,132.9 / 14,174 |

Peaks are PyTorch allocator statistics, including the loaded model and in-memory
features, not full physical-GPU residency measurements. These single-question
runs have different memory demand from Stage 0b's packed 40-question calls.

## Complete-prompt budgeting

The upstream 80% video budget does not always leave enough space for grounding's
timestamp options. The initial default preprocessing could not fit complete
queries for the mansion at 8k or the long window at 8k/16k. The final run measures
native prompt lengths before encoding and reduces only the image-preprocessing
budget when necessary. Language-model context, fps and question text stay fixed;
no frames or questions are skipped and no model code is patched.

The adjusted preprocessing hints are 7,340 for the 8k mansion window, 5,440 for
the 8k long window, and 15,640 for the 16k long window. Every final native padded
prompt fits its requested language context. Actual image geometries and video
token counts are recorded for every result. The context difference changes
spatial detail as well as compute; it is not a fixed-resolution language test.

## Window timestamp alignment

A uniquely burned source timecode identifies every reference frame. Checksums
before and after the sampling filter identify the selected source picture;
checking rewritten MP4 timestamps alone would miss the bug. The reference
retains its original source origin of 240.0314583 s, including the first decoded
frame's offset. A cut at 17.25 s in that reference is then compared with the
native processor's score-cell midpoints, including odd-frame pairing.

| Sampling | Default round=near, max frame error s | round=up, max frame error s | Corrected native pair-center error s |
| --- | ---: | ---: | ---: |
| 0.2 fps | 2.498042 | 0.041167 | 0.022813 |
| 0.5 fps | 0.998542 | 0.040167 | 0.038167 |
| 2 fps | 0.249792 | 0.041667 | 0.040917 |

The corrected sampler uses `fps=F:start_time=0:round=up,trim=duration=D` and
an explicit output duration `-t D`. This removes the half-sample shift and
prevents an extra rounded tail frame. The final test windows have exactly
240/240/360 frames and durations 120/120/1800 seconds. Source offsets plus
native score times are aligned within source-frame rounding (about 42 ms),
not within a whole score cell. Shot-boundary accuracy between sparse frames is
a separate limitation. The original plan's sampling command has been corrected.

## Feature persistence decision

Feature persistence remains **off** in the plan and config. All five queries
reuse the same in-memory features for each window/context, then release them.
No `.safetensors` feature file was written and no save/reload test was run.

For the long 32k window, features would occupy 126.56 MiB before metadata;
preprocessing takes 3.07 s and encoding 1.70 s. Six such feature files would
occupy about 759 MiB for a three-hour coarse pass. Stage 0b's measured 40-query
cost was 147.67 s per window, so avoiding encoding alone saves about 1.1% of
that grounding time, before cache I/O. Avoiding both preprocessing and encoding
would save about 4.77 s per revisit, before reading the feature file.

There is no measured frequent-requery workload to justify a disk feature store
yet. Reconsider if many new single questions repeatedly target the same windows;
the present measurements do not establish a cache break-even rate.

## Validation and stopping point

Tests cover all-negative handling, separate spans, source offsets and selected
frame identity. Artifact checks cover all 45 finite score vectors, exact frame
counts/durations, fixed fps, bounded contexts, complete prompt lengths and all
ten contact-sheet files. Contact sheets and alignment labels were visually
inspected. The pinned source was verified before model execution. Windows's
environment, shared media-search code and the original approved project were
not modified. The creator's external build plan was updated for the cap,
optional feature persistence, prompt reserve and corrected sampling command.

Stage 2 has not started. Final accuracy and threshold judgments remain with
the creator reviewing the sheets. New files are MIT OR Apache-2.0.
