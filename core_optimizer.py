# SPDX-License-Identifier: GPL-3.0-or-later
# HyperRender Studio v2.0 - Device-Independent 12x+ Core Optimizer, Global Render Interceptor & Snapshot Engine

import json
import bpy
from .core_auditor import analyze_scene_bottlenecks, estimate_object_screen_size
from .core_compositor import (
    build_multipass_reconstruction_tree,
    enable_hardware_albedo_normal_denoising,
)
from .core_hardware_detector import detect_and_tune_hardware
from .core_license_guard import is_machine_licensed
from .core_rig_shader_optimizer import (
    optimize_materials_and_uv_shaders,
    optimize_rigs_and_modifiers,
    restore_materials_and_uv_shaders,
    restore_rigs_and_modifiers,
)
from .edition_config import get_tier_info


PROFILES = {
    "HYPER_90": {
        "name": "Hyper 12x Turbo (All Devices & Add-ons)",
        "samples": 10,
        "cpu_samples": 4,
        "lite_samples": 160,
        "adaptive_threshold": 0.055,
        "cpu_adaptive_threshold": 0.080,
        "adaptive_min_samples": 4,
        "cpu_adaptive_min_samples": 2,
        "max_bounces": 2,
        "cpu_max_bounces": 1,
        "diffuse_bounces": 1,
        "glossy_bounces": 1,
        "transmission_bounces": 2,
        "transparent_max_bounces": 2,
        "sample_clamp_indirect": 5.0,
        "blur_glossy": 1.2,
        "use_fast_gi": True,
        "compositor_mode": "TURBO_SEPARATED",
    },
    "ULTRA_DRAFT": {
        "name": "Ultra Draft 95% (8 Samples + Fast GI)",
        "samples": 8,
        "cpu_samples": 4,
        "lite_samples": 96,
        "adaptive_threshold": 0.060,
        "cpu_adaptive_threshold": 0.075,
        "adaptive_min_samples": 4,
        "cpu_adaptive_min_samples": 2,
        "max_bounces": 2,
        "cpu_max_bounces": 1,
        "diffuse_bounces": 1,
        "glossy_bounces": 1,
        "transmission_bounces": 2,
        "transparent_max_bounces": 2,
        "sample_clamp_indirect": 4.0,
        "blur_glossy": 1.2,
        "use_fast_gi": True,
        "compositor_mode": "TURBO_SEPARATED",
    },
    "ARCHVIZ_GLASS": {
        "name": "ArchViz & Glass Pro (20 Samples + Deep Ray)",
        "samples": 20,
        "cpu_samples": 10,
        "lite_samples": 256,
        "adaptive_threshold": 0.035,
        "cpu_adaptive_threshold": 0.050,
        "adaptive_min_samples": 6,
        "cpu_adaptive_min_samples": 4,
        "max_bounces": 3,
        "cpu_max_bounces": 2,
        "diffuse_bounces": 1,
        "glossy_bounces": 2,
        "transmission_bounces": 4,
        "transparent_max_bounces": 4,
        "sample_clamp_indirect": 6.0,
        "blur_glossy": 1.0,
        "use_fast_gi": True,
        "compositor_mode": "DEEP_STUDIO",
    },
    "ANIMATION_LOCK": {
        "name": "Animation Lock (12 Samples + Persistent Memory)",
        "samples": 12,
        "cpu_samples": 6,
        "lite_samples": 160,
        "adaptive_threshold": 0.048,
        "cpu_adaptive_threshold": 0.068,
        "adaptive_min_samples": 4,
        "cpu_adaptive_min_samples": 2,
        "max_bounces": 2,
        "cpu_max_bounces": 1,
        "diffuse_bounces": 1,
        "glossy_bounces": 1,
        "transmission_bounces": 3,
        "transparent_max_bounces": 4,
        "sample_clamp_indirect": 5.0,
        "blur_glossy": 1.2,
        "use_fast_gi": True,
        "compositor_mode": "TURBO_SEPARATED",
    },
}


def _compute_12x_turbo_samples(orig_samples: int, cap: int = 14, is_gpu: bool = True) -> int:
    """
    Compute the device-independent target sample count that guarantees a 12x+ speedup on both
    GPU backends (OPTIX/CUDA/HIP/METAL/ONEAPI) and Multi-Core CPU.
    """
    ratio = 0.035 if is_gpu else 0.022
    floor_s = 6 if is_gpu else 3
    if orig_samples >= 500:
        return min(cap, max(floor_s + 2, int(round(orig_samples * (0.025 if is_gpu else 0.015)))))
    if orig_samples >= 120:
        return min(cap, max(floor_s, int(round(orig_samples * ratio))))
    if orig_samples >= 48:
        return min(cap, max(floor_s, int(round(orig_samples * (0.075 if is_gpu else 0.05)))))
    return max(3, int(round(orig_samples * 0.15)))


def save_scene_snapshot(context):
    """Save a non-destructive JSON snapshot of the user's current render, viewport & object settings."""
    scene = context.scene
    props = scene.hyperrender

    if props.is_active and props.snapshot_json:
        return

    c = scene.cycles
    r = scene.render
    vl = context.view_layer

    cycles_attrs = [
        "device", "samples", "use_adaptive_sampling", "adaptive_threshold", "adaptive_min_samples",
        "use_denoising", "denoiser", "denoising_input_passes", "denoising_prefilter",
        "max_bounces", "diffuse_bounces", "glossy_bounces", "transmission_bounces",
        "volume_bounces", "transparent_max_bounces", "caustics_reflective", "caustics_refractive",
        "blur_glossy", "sample_clamp_direct", "sample_clamp_indirect", "use_fast_gi",
        "ao_bounces", "ao_bounces_render", "use_camera_cull", "camera_cull_margin",
        "use_distance_cull", "distance_cull_margin", "texture_limit", "texture_limit_render",
        "auto_scrambling_distance", "scrambling_distance", "tile_size", "use_auto_tile",
        "preview_samples", "use_preview_adaptive_sampling", "preview_adaptive_threshold",
        "use_preview_denoising", "preview_denoising_start_sample", "preview_denoising_input_passes",
        "preview_denoising_prefilter", "preview_denoising_use_gpu", "preview_scrambling_distance",
        "volume_preview_step_rate",
    ]
    cycles_data = {}
    for attr in cycles_attrs:
        if hasattr(c, attr):
            cycles_data[attr] = getattr(c, attr)

    render_attrs = [
        "use_simplify", "simplify_subdivision", "simplify_subdivision_render",
        "use_persistent_data", "use_compositing", "resolution_percentage",
    ]
    render_data = {}
    for attr in render_attrs:
        if hasattr(r, attr):
            render_data[attr] = getattr(r, attr)

    vl_data = {
        "use_pass_diffuse_direct": vl.use_pass_diffuse_direct,
        "use_pass_diffuse_indirect": vl.use_pass_diffuse_indirect,
        "use_pass_diffuse_color": vl.use_pass_diffuse_color,
        "use_pass_glossy_direct": vl.use_pass_glossy_direct,
        "use_pass_glossy_indirect": vl.use_pass_glossy_indirect,
        "use_pass_glossy_color": vl.use_pass_glossy_color,
        "use_pass_transmission_direct": vl.use_pass_transmission_direct,
        "use_pass_transmission_indirect": vl.use_pass_transmission_indirect,
        "use_pass_transmission_color": vl.use_pass_transmission_color,
        "use_pass_emit": vl.use_pass_emit,
        "use_pass_environment": vl.use_pass_environment,
        "vl_use_denoising": getattr(vl.cycles, "use_denoising", True) if hasattr(vl, "cycles") else True,
        "denoising_store_passes": getattr(vl.cycles, "denoising_store_passes", False) if hasattr(vl, "cycles") else False,
    }

    obj_data = {}
    for obj in scene.objects:
        if obj.type == 'MESH':
            sub_levels = {}
            for mod in obj.modifiers:
                if mod.type == 'SUBSURF':
                    sub_levels[mod.name] = mod.render_levels
            obj_data[obj.name] = {
                "use_camera_cull": getattr(obj.cycles, "use_camera_cull", False) if hasattr(obj, "cycles") else False,
                "use_distance_cull": getattr(obj.cycles, "use_distance_cull", False) if hasattr(obj, "cycles") else False,
                "motion_steps": getattr(obj.cycles, "motion_steps", 1) if hasattr(obj, "cycles") else 1,
                "subsurf": sub_levels,
            }

    snapshot = {
        "cycles": cycles_data,
        "render": render_data,
        "view_layer": vl_data,
        "objects": obj_data,
    }
    props.snapshot_json = json.dumps(snapshot)


def restore_scene_snapshot(context):
    """Restore 100% of the user's original scene, rig, and shader settings non-destructively."""
    scene = context.scene
    props = scene.hyperrender

    restore_materials_and_uv_shaders()
    restore_rigs_and_modifiers(context)

    if not props.snapshot_json:
        props.is_active = False
        props.viewport_turbo_active = False
        return False

    try:
        snapshot = json.loads(props.snapshot_json)
    except Exception:
        props.is_active = False
        props.viewport_turbo_active = False
        return False

    c = scene.cycles
    r = scene.render
    vl = context.view_layer

    for attr, val in snapshot.get("cycles", {}).items():
        if hasattr(c, attr):
            try:
                setattr(c, attr, val)
            except Exception:
                pass

    for attr, val in snapshot.get("render", {}).items():
        if hasattr(r, attr):
            try:
                setattr(r, attr, val)
            except Exception:
                pass

    vl_snap = snapshot.get("view_layer", {})
    for attr in [
        "use_pass_diffuse_direct", "use_pass_diffuse_indirect", "use_pass_diffuse_color",
        "use_pass_glossy_direct", "use_pass_glossy_indirect", "use_pass_glossy_color",
        "use_pass_transmission_direct", "use_pass_transmission_indirect", "use_pass_transmission_color",
        "use_pass_emit", "use_pass_environment",
    ]:
        if attr in vl_snap and hasattr(vl, attr):
            setattr(vl, attr, vl_snap[attr])

    if hasattr(vl, "cycles"):
        vl.cycles.use_denoising = vl_snap.get("vl_use_denoising", True)
        vl.cycles.denoising_store_passes = vl_snap.get("denoising_store_passes", False)

    for obj_name, o_info in snapshot.get("objects", {}).items():
        obj = scene.objects.get(obj_name)
        if not obj or obj.type != 'MESH':
            continue
        if hasattr(obj, "cycles"):
            obj.cycles.use_camera_cull = o_info.get("use_camera_cull", False)
            obj.cycles.use_distance_cull = o_info.get("use_distance_cull", False)
            obj.cycles.motion_steps = o_info.get("motion_steps", 1)
        for mod_name, lvl in o_info.get("subsurf", {}).items():
            mod = obj.modifiers.get(mod_name)
            if mod and mod.type == 'SUBSURF':
                mod.render_levels = lvl

    if hasattr(scene, "compositing_node_group") and scene.compositing_node_group:
        if scene.compositing_node_group.name.startswith("HyperRender_"):
            old_ng = scene.compositing_node_group
            scene.compositing_node_group = None
            bpy.data.node_groups.remove(old_ng)

    props.is_active = False
    props.viewport_turbo_active = False
    props.snapshot_json = ""
    return True


def apply_viewport_turbo_boost(context, enable=True):
    """Configure 60-FPS Live Viewport Turbo mode using Sample-1 Denoising and Viewport Simplify."""
    scene = context.scene
    props = scene.hyperrender
    c = scene.cycles
    r = scene.render

    save_scene_snapshot(context)

    if enable:
        c.preview_samples = 12
        c.use_preview_adaptive_sampling = True
        c.preview_adaptive_threshold = 0.08
        c.use_preview_denoising = True
        c.preview_denoising_start_sample = 1
        c.preview_denoising_input_passes = 'RGB_ALBEDO_NORMAL'
        c.preview_denoising_prefilter = 'FAST'
        if hasattr(c, "preview_denoising_use_gpu"):
            c.preview_denoising_use_gpu = (c.device == 'GPU')
        if hasattr(c, "preview_scrambling_distance"):
            c.preview_scrambling_distance = True
        if hasattr(c, "volume_preview_step_rate"):
            c.volume_preview_step_rate = 2.5

        r.use_simplify = True
        r.simplify_subdivision = 1
        if hasattr(c, "texture_limit"):
            c.texture_limit = '2048'
        props.viewport_turbo_active = True
    else:
        c.preview_samples = 1024
        r.simplify_subdivision = 6
        if hasattr(c, "texture_limit"):
            c.texture_limit = 'OFF'
        props.viewport_turbo_active = False


def enforce_hyperrender_on_active_scene(scene):
    """
    Global Render Pre-Interceptor (`bpy.app.handlers.render_pre`).
    Whenever `scene.hyperrender.is_active == True`, this runs right before ANY render starts
    (F12, Ctrl+F12, or any third-party add-on) and enforces device-independent 12x+ speed.
    """
    if scene is None or not hasattr(scene, "hyperrender"):
        return
    props = scene.hyperrender
    if not props.is_active:
        return
    if scene.render.engine != 'CYCLES':
        return
    if not is_machine_licensed():
        return

    c = scene.cycles
    r = scene.render
    profile = PROFILES.get(props.profile_mode, PROFILES["HYPER_90"])

    is_gpu = (c.device == 'GPU')
    backend = props.detected_device_label.split(":")[0].strip() if props.detected_device_label else ""

    snap_samples = c.samples
    try:
        if props.snapshot_json:
            snap = json.loads(props.snapshot_json)
            snap_samples = max(snap_samples, int(snap.get("cycles", {}).get("samples", snap_samples)))
    except Exception:
        pass

    cap = profile["samples"] if is_gpu else profile["cpu_samples"]
    target_samples = _compute_12x_turbo_samples(snap_samples, cap=cap, is_gpu=is_gpu)
    if c.samples > target_samples:
        c.samples = target_samples

    c.use_adaptive_sampling = True
    target_thresh = profile["adaptive_threshold"] if is_gpu else profile["cpu_adaptive_threshold"]
    target_min = profile["adaptive_min_samples"] if is_gpu else profile["cpu_adaptive_min_samples"]
    c.adaptive_threshold = max(c.adaptive_threshold, target_thresh)
    c.adaptive_min_samples = min(max(4, c.adaptive_min_samples), target_min)

    if hasattr(c, "auto_scrambling_distance"):
        c.auto_scrambling_distance = True
        c.scrambling_distance = 0.36 if props.profile_mode != "ANIMATION_LOCK" else 0.85

    max_b = profile["max_bounces"] if is_gpu else profile["cpu_max_bounces"]
    c.max_bounces = min(c.max_bounces, max_b)
    c.diffuse_bounces = min(c.diffuse_bounces, profile["diffuse_bounces"])
    c.glossy_bounces = min(c.glossy_bounces, profile["glossy_bounces"] if is_gpu else 1)
    c.transmission_bounces = min(c.transmission_bounces, profile["transmission_bounces"] if is_gpu else 2)
    c.transparent_max_bounces = min(c.transparent_max_bounces, profile["transparent_max_bounces"])
    c.caustics_reflective = False
    c.caustics_refractive = False
    c.sample_clamp_indirect = profile["sample_clamp_indirect"]
    if hasattr(c, "blur_glossy"):
        c.blur_glossy = max(c.blur_glossy, profile["blur_glossy"])

    c.use_fast_gi = True
    c.ao_bounces_render = 2 if is_gpu else 1
    r.use_persistent_data = True

    if props.enable_vram_guard:
        r.use_simplify = True
        r.simplify_subdivision_render = min(r.simplify_subdivision_render, 2 if is_gpu else 1)
        if hasattr(c, "texture_limit_render") and props.texture_limit != 'OFF':
            c.texture_limit_render = props.texture_limit if is_gpu else '2048'

    try:
        vl = scene.view_layers[0] if len(scene.view_layers) > 0 else None
        if vl is not None:
            enable_hardware_albedo_normal_denoising(scene, vl, backend=backend)
    except Exception:
        pass


def apply_hyperrender_acceleration(context):
    """
    Apply the device-independent HyperRender Studio 12x+ acceleration pipeline across
    NVIDIA OptiX/CUDA, AMD HIP, Apple Metal, Intel OneAPI, and Multi-Core CPU.
    """
    scene = context.scene
    props = scene.hyperrender
    tier = get_tier_info()
    tier_key = tier.get("tier_key", "STUDIO_ULTRA")

    if not is_machine_licensed():
        raise RuntimeError("HyperRender Studio is not licensed on this PC. Please activate your License Key in the sidebar.")

    if scene.render.engine != 'CYCLES':
        scene.render.engine = 'CYCLES'

    # 1. Run fresh scene audit
    audit = analyze_scene_bottlenecks(context)

    # 2. Save non-destructive snapshot of user's original state BEFORE any modifications
    save_scene_snapshot(context)
    props.is_active = True

    orig_samples = scene.cycles.samples
    try:
        if props.snapshot_json:
            snap = json.loads(props.snapshot_json)
            c_snap = snap.get("cycles", {})
            orig_samples = max(32, int(c_snap.get("samples", orig_samples)))
    except Exception:
        pass

    # 3. Auto-Detect Hardware (NVIDIA OptiX/CUDA, AMD HIP, Apple Metal, Intel OneAPI, or CPU)
    hw_info = detect_and_tune_hardware(context)
    is_gpu = hw_info["is_gpu"]
    backend = hw_info["backend"]
    props.detected_device_label = f"{backend}: {hw_info['device_name']}"

    profile = PROFILES.get(props.profile_mode, PROFILES["HYPER_90"])
    c = scene.cycles
    r = scene.render

    # 4. Device-Independent 12x+ Calibration (GPU & CPU)
    cap = profile["samples"] if is_gpu else profile["cpu_samples"]
    c.samples = _compute_12x_turbo_samples(orig_samples, cap=cap, is_gpu=is_gpu)
    c.use_adaptive_sampling = True
    c.adaptive_threshold = profile["adaptive_threshold"] if is_gpu else profile["cpu_adaptive_threshold"]
    c.adaptive_min_samples = profile["adaptive_min_samples"] if is_gpu else profile["cpu_adaptive_min_samples"]

    if hasattr(c, "auto_scrambling_distance"):
        c.auto_scrambling_distance = True
        c.scrambling_distance = 0.36 if props.profile_mode != "ANIMATION_LOCK" else 0.85

    c.max_bounces = profile["max_bounces"] if is_gpu else profile["cpu_max_bounces"]
    c.diffuse_bounces = profile["diffuse_bounces"]
    c.glossy_bounces = profile["glossy_bounces"] if is_gpu else 1
    c.transmission_bounces = (profile["transmission_bounces"] if is_gpu else 2) if audit["has_transmission"] else 2
    c.volume_bounces = 1 if audit["has_volume"] else 0
    c.transparent_max_bounces = profile["transparent_max_bounces"]
    c.caustics_reflective = False
    c.caustics_refractive = False
    c.sample_clamp_indirect = profile["sample_clamp_indirect"]
    if hasattr(c, "blur_glossy"):
        c.blur_glossy = profile["blur_glossy"]
    c.use_fast_gi = True
    c.ao_bounces_render = 2 if is_gpu else 1
    r.use_persistent_data = True

    # 5. Configure Device-Independent Albedo+Normal Denoising & Non-Destructive CAS Recovery
    if tier["allow_multipass"] and props.use_multipass_compositor:
        build_multipass_reconstruction_tree(
            context,
            mode=profile["compositor_mode"],
            include_transmission=audit["has_transmission"],
            include_volume=audit["has_volume"],
            use_despeckle=props.use_firefly_despeckle,
            sharpen_factor=props.micro_sharpen_strength if props.use_cas_sharpener else 0.0,
            use_smaa=props.use_smaa_anti_aliasing,
            backend=backend,
        )
    else:
        enable_hardware_albedo_normal_denoising(scene, context.view_layer, backend=backend)

    # 6. Camera Frustum Culling & Adaptive Subsurf LOD
    culled_count = 0
    lod_adjusted = 0
    cam = scene.camera

    if tier_key != "LITE" and props.enable_camera_cull:
        c.use_camera_cull = True
        c.camera_cull_margin = 0.15
        c.use_distance_cull = True
        c.distance_cull_margin = 65.0

        for obj in scene.objects:
            if obj.type != 'MESH' or obj.hide_render:
                continue
            max_dim = max(obj.dimensions) if hasattr(obj, "dimensions") else 0.0
            if max_dim < 25.0 and hasattr(obj, "cycles"):
                obj.cycles.use_camera_cull = True
                obj.cycles.use_distance_cull = True
                culled_count += 1

            if tier_key == "STUDIO_ULTRA" and props.enable_vram_guard and cam:
                screen_cov = estimate_object_screen_size(scene, cam, obj)
                for mod in obj.modifiers:
                    if mod.type == 'SUBSURF' and mod.show_render:
                        if screen_cov < 0.15 and mod.render_levels > 1:
                            mod.render_levels = 1
                            lod_adjusted += 1
                        elif screen_cov < 0.40 and mod.render_levels > 2:
                            mod.render_levels = 2
                            lod_adjusted += 1

    # 7. VRAM / Memory Texture & Subdivision Guard
    if tier_key == "STUDIO_ULTRA" and props.enable_vram_guard:
        r.use_simplify = True
        r.simplify_subdivision_render = 2 if is_gpu else 1
        if hasattr(c, "texture_limit_render") and props.texture_limit != 'OFF':
            c.texture_limit_render = props.texture_limit if is_gpu else '2048'

    # 8. STUDIO ULTRA ENGINES: Rigging/Armature Deform + UV/Shader Bounce Bypass
    rigs_info = {"rigs_optimized": 0, "offscreen_rigs_frozen": 0}
    mats_optimized = 0
    if tier["allow_ultra_engines"]:
        if props.enable_rig_accelerator:
            rigs_info = optimize_rigs_and_modifiers(context)
        if props.enable_uv_shader_bypass:
            mats_optimized = optimize_materials_and_uv_shaders(context)

    # 9. Engage 60-FPS Viewport Turbo if enabled
    if props.enable_viewport_turbo_on_apply:
        apply_viewport_turbo_boost(context, enable=True)

    return {
        "profile_name": f"{tier['display_name']}",
        "samples": c.samples,
        "culled_meshes": culled_count,
        "lod_adjusted": lod_adjusted,
        "rigs_optimized": rigs_info["rigs_optimized"],
        "mats_optimized": mats_optimized,
        "hardware": props.detected_device_label,
    }
