[English](README.en.md) | [繁體中文](README.md)

# ParaRig

![ParaRig](docs/images/featured-image.png)

A Blender add-on (Python package) that auto-generates draggable slider rigs and Drivers from a simple list, so you don't have to hand-build Empties, constraints, and driver expressions every time you want a Live2D-style parameter panel for your character.

Fill in a list of sliders — name, group, control style (vertical/horizontal drag), target (Shape Key / custom property / bone location), value range — and click **Generate** to get:

1. A visual slider control per entry: a flat 2D rectangular track + a draggable circular handle, grouped inside a resizable/movable "Frame" per group, laid out on a fixed-size grid.
2. A driver on the target property that maps the handle's drag position linearly to `[min_val, max_val]`.

## Installation

1. Download `para_rig-<version>.zip` from the [Releases](https://github.com/Zosuya/ParaRig/releases) page.
2. Edit > Preferences > Add-ons > Install from Disk, select the zip, then enable it.
3. Open the N-panel in the 3D Viewport, go to the **ParaRig** tab.

Requires Blender 4.2 or newer (tested on 4.5 LTS and 5.2 LTS).

## Usage

The N-panel has two pages, **Group** and **Sliders**, switched with the buttons at the top.

1. Create a group on the **Group** page (or just add a slider — a group is created automatically). A group is a container whose controls share one Frame and move/rotate/scale together, and it can be bound to follow an object or bone.
2. On the **Sliders** page, add entries with the `+` button, filling in each one's control style, target type/object, and value range.
3. Use **Edit Layout** to drag controls onto the layout grid.
4. Click **Generate Slider Rig**. Everything is placed in a dedicated "ParaRig" collection. Re-running Generate after editing the list is non-destructive: it updates in place instead of resetting handle positions or Frame transforms you've adjusted.
5. Drag a slider's circular handle along its locked axis to drive the bound value.
6. Click **Clear Generated Sliders** to remove everything and start over.

For a full walkthrough of every panel and control style, see the [Traditional Chinese README](README.md).

## ParaRig Pro

A paid **ParaRig Pro** version is also available, adding long slider variants, the polygon blend control (for mouth-shape blending), JSON import/export, quick and mirrored data fill, control duplication, one-to-many bindings, bidirectional split ranges, snap-to-ends, and more. See the feature comparison table in the document linked above.

## Status

Licensed under GPL-3.0-or-later — see [`LICENSE`](LICENSE).
