# SPDX-License-Identifier: GPL-3.0-or-later
# HyperRender Studio v2.0 - Visual Side-by-Side Before vs. After Image Builder

import os
import bpy


def build_and_show_side_by_side_image(context, base_img_path: str, hyper_img_path: str, t_base: float, t_hyper: float, speedup_pct: float):
    """
    Loads the WITHOUT and WITH rendered PNGs, creates a stitched Side-by-Side
    Before (Left, Red Bar) vs. After (Right, Green Bar) comparison image inside
    bpy.data.images, and displays it immediately in Blender's Image/Render Editor.
    """
    if not (os.path.exists(base_img_path) and os.path.exists(hyper_img_path)):
        return None

    try:
        img_off = bpy.data.images.load(base_img_path, check_existing=False)
        img_off.name = f"1_WITHOUT_Addon_{t_base:.1f}s"
        img_on = bpy.data.images.load(hyper_img_path, check_existing=False)
        img_on.name = f"2_WITH_HyperRender_{t_hyper:.1f}s"

        w, h = img_off.size[0], img_off.size[1]
        if w <= 0 or h <= 0 or img_on.size[0] != w or img_on.size[1] != h:
            return img_on

        import numpy as np

        arr_off = np.empty(w * h * 4, dtype=np.float32)
        arr_on = np.empty(w * h * 4, dtype=np.float32)
        img_off.pixels.foreach_get(arr_off)
        img_on.pixels.foreach_get(arr_on)

        arr_off = arr_off.reshape((h, w, 4))
        arr_on = arr_on.reshape((h, w, 4))

        # Add a 28px colored banner at the top of each side:
        # Left (WITHOUT Add-on) = Red indicator bar
        # Right (WITH HyperRender) = Bright Green indicator bar
        bar_h = min(32, max(12, h // 28))
        arr_off[h - bar_h : h, :, 0] = 0.85
        arr_off[h - bar_h : h, :, 1] = 0.15
        arr_off[h - bar_h : h, :, 2] = 0.15
        arr_off[h - bar_h : h, :, 3] = 1.0

        arr_on[h - bar_h : h, :, 0] = 0.12
        arr_on[h - bar_h : h, :, 1] = 0.80
        arr_on[h - bar_h : h, :, 2] = 0.30
        arr_on[h - bar_h : h, :, 3] = 1.0

        # 8px white/dark divider in the center
        div_w = 8
        div = np.ones((h, div_w, 4), dtype=np.float32)
        div[:, :, 0] = 0.95
        div[:, :, 1] = 0.85
        div[:, :, 2] = 0.20
        div[:, :, 3] = 1.0

        combined = np.concatenate([arr_off, div, arr_on], axis=1)
        total_w = w * 2 + div_w

        comp_name = f"BEFORE_{t_base:.1f}s_vs_AFTER_{t_hyper:.1f}s_({speedup_pct:.1f}%_FASTER)"
        for old_img in list(bpy.data.images):
            if old_img.name.startswith("BEFORE_"):
                bpy.data.images.remove(old_img)

        comp_img = bpy.data.images.new(name=comp_name, width=total_w, height=h, alpha=True)
        comp_img.pixels.foreach_set(combined.ravel())
        comp_img.update()

        # Open the Render View window and switch any IMAGE_EDITOR space to show our Side-by-Side image!
        try:
            bpy.ops.render.view_show('INVOKE_DEFAULT')
        except Exception:
            pass

        for window in context.window_manager.windows:
            for area in window.screen.areas:
                if area.type == 'IMAGE_EDITOR':
                    for space in area.spaces:
                        if space.type == 'IMAGE_EDITOR':
                            space.image = comp_img

        return comp_img
    except Exception:
        return None
