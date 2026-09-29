# Spatial plan

Written 2026-09-29. Code: `contracts/spatial.py`, `narrative/layouts.py`, `narrative/spatial.py`.

## Where it sits

```text
SceneSpec (what happened)  →  SpatialPlan (how it happens in space)  →  SpatialBackend (Blender / 2D / three.js)
                                                                      →  control material → VisualBackend
```

The plan is backend-neutral JSON in metres, hashed and pinned to the SceneSpec it stages (`scene_hash`).
Re-staging changes how a scene is filmed, never its story. World, Story and SceneSpec know nothing about Blender.

## Contents

- **Layouts**: white-box floor plans for the five places, made only of boxes, with named anchors (seats,
  standing spots, a street spot outside the cafe window, a perch).
  - Cafe: 10 × 8 m, a street window, three tables, a counter.
  - Park: benches and three trees that block sight.
  - Office: four desks.
  - Apartment: sofa and table.
  - Station: a pillar and a bench.
- **Blocking rules**:
  - Principals face each other at a table or a bench pair. They sit for quiet acts and stand for loud ones.
  - A lone act puts the actor by the prop.
  - Witnesses take the first free spot with a clear view of the actor (they noticed the act in the world).
  - The parrot sits on its perch.
- **Cameras**: a wide shot, a two-shot across the pair's axis, an over-the-shoulder single, and an insert on the
  prop.
  - Each camera must see its subjects. If a position is blocked, the compiler tries the other side, the corners,
    rings around the action, and finally a high angle.
- **Sight QA**: every required line (witness → actor, camera → subject) is tested against the boxes, and windows
  do not block. A plan with any failed line is `valid = false` and must not go to a video backend.

On the 14 daily picks of one Experiment C world, all 14 plans are valid. Before witnesses chose spots with a clear
view, 4 failed, because park trees stood in the way.

## Not done, and why

- **The Blender backend (white-box previs → RGB, depth, mask).**
  - It needs Blender installed: a download of about 300 MB, which the user has to allow.
  - No video backend can use the control material yet: the free tier has video quota 0, and the GTX 1080 cannot
    run Wan 2.2.
  - The plan format is ready for it.
- **A 2D backend.** Feeding the plan to the existing cast renderer would make scenes watchable at $0 now. That is a
  smaller step than Blender.
