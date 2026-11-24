# SPDX-License-Identifier: GPL-3.0-or-later
# HyperRender Studio - Deep Scene Bottleneck & Shader Auditor

import json
import bpy
from mathutils import Vector
from bpy_extras.object_utils import world_to_camera_view


def is_object_in_camera_frustum(scene, cam_obj, obj, margin=0.18):
    """Check if any corner of an object's world bounding box falls inside the camera frustum."""
    if not cam_obj or cam_obj.type != 'CAMERA':
        return True
    if not hasattr(obj, "bound_box") or not obj.bound_box:
        return True

    mat = obj.matrix_world
    corners = [mat @ Vector(corner) for corner in obj.bound_box]
    # Also test center point
    center = sum(corners, Vector((0.0, 0.0, 0.0))) / 8.0
    test_points = corners + [center]

    min_x, max_x = 1e9, -1e9
    min_y, max_y = 1e9, -1e9
    any_in_front = False

    for pt in test_points:
        ndc = world_to_camera_view(scene, cam_obj, pt)
        if ndc.z > 0.0:
            any_in_front = True
        min_x = min(min_x, ndc.x)
        max_x = max(max_x, ndc.x)
        min_y = min(min_y, ndc.y)
        max_y = max(max_y, ndc.y)

    if not any_in_front:
        return False

    # Check AABB overlap with [-margin, 1+margin] in normalized camera coordinates
    if max_x < -margin or min_x > (1.0 + margin):
        return False
    if max_y < -margin or min_y > (1.0 + margin):
        return False

    return True


def estimate_object_screen_size(scene, cam_obj, obj):
    """Return normalized screen-space coverage (0.0 to 1.0+) of an object from active camera."""
    if not cam_obj or cam_obj.type != 'CAMERA' or not getattr(obj, "bound_box", None):
        return 1.0
    mat = obj.matrix_world
    ndc_pts = [world_to_camera_view(scene, cam_obj, mat @ Vector(c)) for c in obj.bound_box]
    in_front = [p for p in ndc_pts if p.z > 0.0]
    if not in_front:
        return 0.0
    xs = [p.x for p in in_front]
    ys = [p.y for p in in_front]
    span_x = max(0.0, min(1.5, max(xs)) - max(-0.5, min(xs)))
    span_y = max(0.0, min(1.5, max(ys)) - max(-0.5, min(ys)))
    return max(span_x, span_y)


def analyze_scene_bottlenecks(context):
    """Perform a comprehensive studio audit of geometry, shaders, textures, and Cycles settings."""
    scene = context.scene
    cam = scene.camera

    total_meshes = 0
    base_polys = 0
    effective_polys = 0
    heavy_subsurf_objs = 0
    offscreen_objs = 0
    offscreen_polys = 0

    for obj in scene.objects:
        if obj.type != 'MESH' or obj.hide_render:
            continue
        total_meshes += 1
        poly_count = len(obj.data.polygons) if obj.data else 0
        base_polys += poly_count

        # Calculate Subdivision multiplier
        subsurf_mult = 1
        for mod in obj.modifiers:
            if mod.type in {'SUBSURF', 'MULTIRES'} and mod.show_render:
                lvl = getattr(mod, "render_levels", 0)
                if lvl > 0:
                    subsurf_mult *= (4 ** lvl)
                if lvl >= 3:
                    heavy_subsurf_objs += 1

        obj_eff_polys = poly_count * subsurf_mult
        effective_polys += obj_eff_polys

        if cam and not is_object_in_camera_frustum(scene, cam, obj, margin=0.20):
            offscreen_objs += 1
            offscreen_polys += obj_eff_polys

    # Scan Materials for Transmission/Glass, Volume, and Subsurface
    has_transmission = False
    has_volume = False
    has_sss = False
    material_count = 0

    for mat in bpy.data.materials:
        if not mat.use_nodes or not mat.node_tree:
            continue
        material_count += 1
        for node in mat.node_tree.nodes:
            if node.type in {'BSDF_GLASS', 'BSDF_REFRACTION'}:
                has_transmission = True
            elif node.type in {'VOLUME_SCATTER', 'VOLUME_ABSORPTION', 'PRINCIPLED_VOLUME'}:
                has_volume = True
            elif node.type == 'BSDF_PRINCIPLED':
                # Check Transmission Weight & Subsurface Weight sockets across Blender 4.x / 5.x
                for sock_name in ('Transmission Weight', 'Transmission'):
                    if sock_name in node.inputs:
                        val = node.inputs[sock_name].default_value
                        if (isinstance(val, (int, float)) and val > 0.02) or node.inputs[sock_name].is_linked:
                            has_transmission = True
                for sock_name in ('Subsurface Weight', 'Subsurface'):
                    if sock_name in node.inputs:
                        val = node.inputs[sock_name].default_value
                        if (isinstance(val, (int, float)) and val > 0.02) or node.inputs[sock_name].is_linked:
                            has_sss = True

    # Scan World for Volumetric Scatter
    if scene.world and scene.world.use_nodes and scene.world.node_tree:
        for node in scene.world.node_tree.nodes:
            if node.type in {'VOLUME_SCATTER', 'PRINCIPLED_VOLUME'}:
                has_volume = True

    # Scan Textures for VRAM footprint
    total_textures = 0
    oversized_textures = 0  # >= 4096px
    vram_bytes = 0

    for img in bpy.data.images:
        if img.type not in {'IMAGE', 'UV_TEST'} or img.users == 0:
            continue
        w, h = img.size[0], img.size[1]
        if w <= 0 or h <= 0:
            continue
        total_textures += 1
        bytes_per_pixel = 16 if img.is_float else 4
        vram_bytes += (w * h * bytes_per_pixel)
        if max(w, h) >= 4096:
            oversized_textures += 1

    vram_mb = round(vram_bytes / (1024 * 1024), 1)

    # Evaluate Current Cycles Settings Waste
    c = scene.cycles if hasattr(scene, "cycles") else None
    current_samples = c.samples if c else 1024
    current_bounces = c.max_bounces if c else 12
    caustics_on = bool(c and (c.caustics_reflective or c.caustics_refractive))

    # Calculate Bottleneck Severity Score (0 = Fully Optimized, 100 = Severe Waste)
    waste_score = 0
    warnings = []

    if current_samples > 256:
        waste_score += min(45, int((current_samples - 128) / 25))
        warnings.append(f"High Sample Count ({current_samples} samples) -> Can drop to 64 with Multi-Pass")
    if current_bounces > 6:
        waste_score += 20
        warnings.append(f"Excessive Light Bounces ({current_bounces} max bounces) -> Wasting GPU ray depth")
    if caustics_on and not has_transmission:
        waste_score += 15
        warnings.append("Caustics enabled without refractive glass -> Pure raytracing overhead")
    if offscreen_objs > 0:
        waste_score += 10
        warnings.append(f"{offscreen_objs} off-screen meshes ({offscreen_polys:,} polys) outside camera frustum")
    if heavy_subsurf_objs > 0:
        waste_score += 10
        warnings.append(f"{heavy_subsurf_objs} meshes using heavy Subdivision (Level 3+)")
    if oversized_textures > 0:
        warnings.append(f"{oversized_textures} ultra-res (4K/8K+) textures (~{vram_mb} MB VRAM)")

    waste_score = min(99, max(5, waste_score))

    # Estimate theoretical speedup % when applying HyperRender 90
    sample_ratio = max(1.0, min(16.0, current_samples / 64.0))
    bounce_factor = 1.35 if current_bounces >= 8 else 1.1
    cull_factor = 1.25 if offscreen_objs > 0 else 1.05
    est_multiplier = round(sample_ratio * bounce_factor * cull_factor, 1)
    est_reduction_pct = round((1.0 - (1.0 / max(1.1, est_multiplier))) * 100.0, 1)
    est_reduction_pct = min(94.5, max(55.0, est_reduction_pct))

    report = {
        "total_meshes": total_meshes,
        "base_polys": base_polys,
        "effective_polys": effective_polys,
        "heavy_subsurf_objs": heavy_subsurf_objs,
        "offscreen_objs": offscreen_objs,
        "offscreen_polys": offscreen_polys,
        "has_transmission": has_transmission,
        "has_volume": has_volume,
        "has_sss": has_sss,
        "total_textures": total_textures,
        "oversized_textures": oversized_textures,
        "vram_mb": vram_mb,
        "current_samples": current_samples,
        "current_bounces": current_bounces,
        "waste_score": waste_score,
        "est_multiplier": est_multiplier,
        "est_reduction_pct": est_reduction_pct,
        "warnings": warnings,
    }

    scene.hyperrender.audit_report_json = json.dumps(report)
    scene.hyperrender.has_audit = True
    return report
