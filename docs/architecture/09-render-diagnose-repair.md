# 09 Render → Diagnose → Repair

Code: `contracts/repair.py`, `production/shot_qa.py`, `production/shots.py`; tables `visual_failures`,
`repair_requests`.

**Problem.**
- Generative video fails in specific ways: frozen output, wrong length, identity drift.
- "Retry until it looks fine" wastes money and teaches nothing.

**Decision.**
- Every shot take is diagnosed into typed `VisualFailure`s, each with the detector and its evidence.
- Each failure code maps to targeted repair ops.
- A `RepairRequest` is recorded, together with the request it produced.
- A take that failed is marked `rejected`, so no cache ever reuses it.
- Only the failing shot is re-rendered. SceneSpec and packet never change.

**What is measured today:**
- `FORMAT_ERROR`, `DURATION_ERROR` (ffprobe);
- `FROZEN_FRAMES` and `BLACK_FRAMES` (frames sampled across the clip);
- `PROVIDER_ERROR` (failure or no file);
- `SPATIAL_ERROR` (invalid plan).

**What is vocabulary only:**
- `IDENTITY_DRIFT`, `OBJECT_CONTINUITY_ERROR`, `POSE_ERROR` and the rest.
- They need a vision inspector. The codes exist so that the inspector reports into the same records, but nothing
  may claim them without one.

**Repairs:**

| Failure | Repair |
|---|---|
| frozen, black | reseed |
| provider or format failure | next provider in the selection's fallback chain |
| wrong duration | next provider (conforming would need a provider option) |

The loop gives up after 4 attempts, and the episode is then `render_failed`.

**Found while building it.**
- ffmpeg's `freezedetect` compares neighbouring frames. It called clips with a small moving subject "frozen", because
  a 2 % subject moving 6 px a frame changes too little between two frames.
- The first replacement, the mean difference over 6 sampled frames, had the same problem on a 1920×1080 canvas.
- The detector now counts pixels that changed by more than 12 grey levels between the most different samples. A
  clip is frozen when fewer than 0.1 % moved.
- The mock provider's white marker was invisible on the near-white depth of close shots, so it now has a black
  frame.
- After both fixes, the detector matched the ground truth on all 11 takes of a full episode. Six shots needed
  5 repairs, and the episode passed the same QA as HyperFrames episodes.

**The mock's defect is deliberate and labelled.**
- `mock-clip` freezes on about 25 % of (shot, seed) pairs, standing in for image-to-video models that return no
  motion.
- The loop's value against a real model is not measured yet.
