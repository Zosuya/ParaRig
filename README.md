[English](README.md) | [繁體中文](README.zh-TW.md)

# ParaRig

![ParaRig](docs/images/featured-image.png)

A Blender add-on (Python package) that auto-generates draggable slider rigs and Drivers from a simple list, so you don't have to hand-build Empties, constraints, and driver expressions every time you want a Live2D-style parameter panel for your character.

Fill in a list of sliders — name, group, control style (vertical/horizontal drag), target (Shape Key / custom property / bone location), value range — and click **Generate** to get:

1. A visual slider control per entry: a flat 2D rectangular track + a draggable circular handle, grouped inside a resizable/movable "Frame" per group, laid out on a fixed-size grid.
2. A driver on the target property that maps the handle's drag position linearly to `[min_val, max_val]`.

## Installation

1. Edit > Preferences > Add-ons > Install, select the `para_rig` folder (zipped) or point Blender at it directly, then enable it.
2. Open the N-panel in the 3D Viewport, go to the **ParaRig** tab.

## Usage

1. Add slider entries with the `+` button, filling in each one's group, control style, target type/object, and value range.
2. Click **Generate Slider Rig**. Sliders are grouped by their `group` field — one Frame per group — and everything is placed in a dedicated "ParaRig" collection. Re-running Generate after editing the list is non-destructive: it updates in place instead of resetting handle positions or Frame transforms you've adjusted.
3. Drag a slider's circular handle along its locked axis to drive the bound value.
4. Click **Clear Generated Sliders** to remove everything and start over.

## Status

Actively evolving. Licensed under GPL-3.0-or-later — see [`LICENSE`](LICENSE).
