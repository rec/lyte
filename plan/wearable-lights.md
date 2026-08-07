# Wearable Twinkly Dots Plan

Issue #3: build a front-and-side-visible wearable from 200 Twinkly Generation
Dots. The unmodified factory string splits into two 100-dot paths at its tee;
the power/control unit sits at the rear of the belt. The wearer is approximately
175 cm and 73 kg.

## Constraints

- The controller, power supply, cable strain relief, and the first few
  centimetres of each branch stay at the rear belt.
- Dots should be visible from the front and side. Do not intentionally place
  illuminated dots on the back.
- The layout must remain comfortable to walk, raise both arms, bend at the
  waist, and sit down. Route each path over clothing or a harness, never as a
  load-bearing garment seam.
- The factory tee and both 100-dot strands remain unmodified. The plan concerns
  only how the supplied string is attached to the garment and how its existing
  output indices map to the wearer.

## Dot Allocation

Use two mirror-image paths of exactly 100 dots. This makes routing from the
rear belt tidy, keeps left/right effects balanced, and makes the two physical
paths independently diagnosable.

| Region | Left path | Right path | Total |
| --- | ---: | ---: | ---: |
| Arm, wrist to shoulder | 28 | 28 | 56 |
| Leg, ankle to hip | 32 | 32 | 64 |
| Side body, hip to underarm | 16 | 16 | 32 |
| Front chest spiral | 24 | 24 | 48 |
| Total | 100 | 100 | 200 |

The counts are starting values, not an assertion about the physical pitch of a
particular Dot string. Fit the garment while preserving the regional totals;
use the small gaps between regions for slack and strain relief rather than
compressing dots into joints.

## Physical Layout

### Arms: 28 dots per arm

Start at the wrist and run toward the shoulder on the outside/front-facing
surface of the arm. Use two loose, shallow helical passes around the forearm
and upper arm rather than one straight line. Keep the elbow itself clear and
place the nearest dots several centimetres above and below the bend. The
outside of the arm is visible from both front and side and avoids an obvious
dark line when the arms hang naturally.

### Legs: 32 dots per leg

Start above the ankle, go up the outer-front shin, cross gently to the
front/outer thigh, and end at the hip. Keep the knee clear in the same way as
the elbow. This path should be attached to trousers, leggings, or a harness
with enough slack for a full knee bend. Avoid the rear calf and rear thigh.

### Side body: 16 dots per side

Run from the belt-side hip upward along the side seam to the underarm, biased
slightly toward the front. This is the connective visual line between leg,
torso, and arm while still reading clearly to a side audience.

### Chest: 48 dots total

The two 24-dot chest tails continue from the left and right side-body paths.
Together they form one front-facing double-entry spiral centered at the solar
plexus. Begin wide, near the lower ribs, curve inward across the chest, and
alternate the two sides visually as the spiral tightens. The final dots should
end close to the solar plexus, leaving slack rather than putting tension on the
centre of the chest.

This is not a single electrically consecutive spiral. It is two physical
half-spirals whose coordinates make it behave as one spiral for animations.

## Physical Index Order

Name the paths `left` and `right`, independent of cable colour. Mark both the
controller end and every boundary with heat-shrink or tags during construction.

| Path index range | Region | Direction |
| --- | --- | --- |
| `0..27` | arm | wrist to shoulder |
| `28..59` | leg | ankle to hip |
| `60..75` | side body | hip to underarm |
| `76..99` | chest half-spiral | outer ribs to solar plexus |

The actual path order may need changing if cable length or connector placement
requires it. That is acceptable, but it must change only this physical map, not
the geometric coordinates or animation-facing selectors.

## Addressable Wearable Layout

Represent each dot once as a layout point with both physical delivery and
body-relative geometry:

```text
WearablePoint
  output_index: int       # actual Twinkly frame index, 0..199
  path: "left" | "right"
  path_index: int         # 0..99 within the physical path
  region: arm | leg | side | chest
  side: left | right | center
  x, y, z: float          # metres, relative to the body coordinate frame
  limb_position: float    # 0.0 at distal/lower end, 1.0 at proximal/upper end
```

Set the body origin at the wearer's estimated centre of gravity in a neutral
standing pose. Use `x` for wearer-left to wearer-right, `y` for feet to head,
and `z` for back to front. Capture coordinates after the garment is fitted;
they need only be consistent enough for sorting and smooth gradients, not a
precise anatomical scan.

All requested ways of addressing lights then come from this one map:

| Effect space | Selection or ordering |
| --- | --- |
| Vertical | sort or sample by `y`; reverse by negating the coordinate or reversing the ordering |
| Horizontal | sort or sample by `x` |
| Limb / body region | filter by `region` and optionally `side` |
| Centre-of-gravity distance | `sqrt(x*x + y*y + z*z)` |
| Spiral | polar angle and radius in the chest plane, derived from `x`, `y`, and `z` |
| Physical diagnostics | `output_index`, `path`, or `path_index` |

No animation should encode the 200 physical indices itself. Animations consume
the coordinate map or named selectors, and one output adapter converts the
result to Twinkly frame order. This keeps a later re-fit or rewiring local to
the layout data.

## Build And Calibration Sequence

1. Identify the factory output-index order of the two 100-dot paths with a
   chasing-index diagnostic, without modifying the string.
2. Make a temporary harness with the four regional counts above, starting with
   the controller at the rear belt.
3. Fit one path at a time, test every dot with a chasing-index diagnostic, and
   label the regional boundaries.
4. Test arm raise, elbow/knee bend, walk, sit, and cable snag resistance with
   the power off.
5. Record a row for every physical dot in a layout data file. Start from the
   100-per-path ranges above, then measure or estimate its `x`, `y`, `z` in a
   neutral standing pose.
6. Upload the corresponding Twinkly 3D layout only if it is useful for the
   Twinkly app. Lyte's own layout data remains authoritative because it also
   carries path, region, and selector metadata.
7. Verify four simple effects before writing show animations: bottom-to-top
   chase, left-to-right chase, one-region-at-a-time colour fill, and expanding
   / contracting centre-of-gravity rings.

## Implementation Order

1. Add an immutable generic layout-point model and layout container outside the
   Twinkly protocol code.
2. Add selectors and coordinate projections for `vertical`, `horizontal`,
   `region`, and radial distance.
3. Add a wearable layout data file containing the 200 fitted points and a
   Twinkly output-index mapping.
4. Add preview support so the same data can be inspected in a front and side
   view before it is sent to the string.
5. Add the four calibration animations above and verify them on the worn
   garment.
6. Add show-file support for naming a layout once animation graphs are able to
   construct and play through the current show-file parser.

## Acceptance Criteria

- Exactly 200 points map one-to-one to the Twinkly output frame.
- Each physical path has exactly 100 recorded points.
- Every point has a region, side, and body-relative coordinate.
- Vertical, horizontal, region, and radial effects are computed from the same
  layout data.
- A change to cable routing or string index order requires changing only the
  physical mapping, not animation code.
- The four calibration effects visibly agree with the intended garment layout.

## Additional work beyond the prompt

None.
