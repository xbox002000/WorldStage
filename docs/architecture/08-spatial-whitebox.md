# 08 Spatial whitebox

Code: `render/whitebox.py`; the plan it reads is `contracts/spatial.py` / `narrative/spatial.py`.

**Problem.** A video model conditioned on depth or masks keeps blocking and camera consistent across shots. The
SpatialPlan already knows every box, person and camera, but nothing turned it into control images.

**Options.**
1. Blender whitebox (lights, posed RGB previs). It needs a ~300 MB install.
2. A numpy ray-cast of the plan's boxes.

**Decision: option 2 now, as the `whitebox` provider of `spatial.control`.**

For each staged camera it produces:
- `depth`: 8-bit, near is white;
- `mask`: a flat colour per object and person;
- `legend`: colour → id.

The output is byte-identical for the same plan. Glass (windows) is transparent. A cafe camera takes about 0.4–1.2 s
at 270×480.

Blender remains the planned second provider: it would register with the same interface and add `pose` and an RGB
previs. Nothing else changes.

**Why.** It proves the boundary (SpatialPlan → control material → visual provider) today, with no install and no GPU.

**Tradeoffs.**
- People are boxes, so there is no pose.
- There is no lighting, so the output is not a previs image.
- Depth is planar (distance along the view axis), which is what depth-conditioned models expect.

**Rules.**
- A plan with a blocked sight line (`valid = false`) sends no control. It records `SPATIAL_ERROR` against the shot
  instead.
- When control images are sent, the shot's requirement gains the `depth` feature, so only providers that accept
  depth are chosen.
- The control images' hashes go into the shot's RenderRequest.
