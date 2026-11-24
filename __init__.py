# SPDX-License-Identifier: GPL-3.0-or-later
# HyperRender Studio v2.0 - True 1-Click 12x Render Accelerator + Global Add-on Boost Interceptor

bl_info = {
    "name": "HyperRender Studio",
    "author": "Tumex Studio",
    "version": (2, 0, 0),
    "blender": (4, 2, 0),
    "location": "View3D > Sidebar (N-Panel) > HyperRender",
    "description": "1-Click 12x+ Cycles Speed Booster — Works with Built-in Renders (F12) & All Third-Party Add-ons",
    "category": "Render",
}

import importlib
import os
import sys
import tempfile
import time
import bpy
from bpy.app.handlers import persistent
from bpy.props import (
    BoolProperty,
    EnumProperty,
    FloatProperty,
    IntProperty,
    PointerProperty,
    StringProperty,
)
from bpy.types import Operator, Panel, PropertyGroup

# Ensure live 'Reload Scripts' in an already-open Blender session reloads all submodules cleanly
_SUBMODULES = (
    "edition_config",
    "core_license_guard",
    "core_hardware_detector",
    "core_auditor",
    "core_compositor",
    "core_rig_shader_optimizer",
    "core_auto_camera",
    "core_visual_report",
    "core_optimizer",
    "core_batch_queue",
)
for _mod_name in _SUBMODULES:
    _full = f"{__package__}.{_mod_name}"
    if _full in sys.modules:
        try:
            importlib.reload(sys.modules[_full])
        except Exception:
            pass

from .core_auditor import analyze_scene_bottlenecks
from .core_auto_camera import ensure_camera_and_lighting
from .core_batch_queue import execute_multi_camera_batch_queue
from .core_license_guard import (
    STORE_BUY_URL,
    activate_license_on_this_machine,
    deactivate_license_on_this_machine,
    get_machine_hwid,
    is_drm_free_build,
    is_machine_licensed,
)
from .core_optimizer import (
    apply_hyperrender_acceleration,
    apply_viewport_turbo_boost,
    enforce_hyperrender_on_active_scene,
    restore_scene_snapshot,
)
from .core_visual_report import build_and_show_side_by_side_image
from .edition_config import ALLOW_DEV_TIER_SWITCHER, EDITION_TIER, STORE_UPGRADE_URL, get_tier_info


@persistent
def _hyperrender_on_render_init(scene, _depsgraph=None):
    """Intercept render initialization from F12, Ctrl+F12, or any third-party add-on when 12x Boost is ON."""
    try:
        enforce_hyperrender_on_active_scene(scene)
    except Exception:
        pass


@persistent
def _hyperrender_on_render_pre(scene, _depsgraph=None):
    """
    Intercept every frame right before Cycles starts tracing rays.
    Even if another add-on overwrote samples/bounces milliseconds before calling `bpy.ops.render.render()`,
    this guarantees the 12x+ Turbo acceleration stays locked on for both Images and Animations.
    """
    try:
        enforce_hyperrender_on_active_scene(scene)
    except Exception:
        pass


def _force_png_output(scene):
    """Temporarily switch output to PNG so test frames can be saved even if the scene is set to FFmpeg."""
    s = scene.render.image_settings
    saved = {"file_format": s.file_format}
    if hasattr(s, "media_type"):
        saved["media_type"] = s.media_type
        s.media_type = 'IMAGE'
    s.file_format = 'PNG'
    return saved


def _restore_output(scene, saved):
    s = scene.render.image_settings
    try:
        if "media_type" in saved:
            s.media_type = saved["media_type"]
        s.file_format = saved["file_format"]
    except Exception:
        pass


def _format_duration(seconds: float) -> str:
    if seconds >= 3600.0:
        hrs = int(seconds // 3600)
        mins = int((seconds % 3600) // 60)
        return f"{hrs}h {mins}m ({seconds:.0f}s)"
    if seconds >= 60.0:
        mins = int(seconds // 60)
        rem = seconds - (mins * 60)
        return f"{seconds:.1f}s ({mins}m {int(rem)}s)"
    return f"{seconds:.1f}s"


def _show_benchmark_popup(context):
    props = context.scene.hyperrender
    saved_s = max(0.0, props.baseline_time - props.hyper_time)
    total_timeline_frames = max(1, context.scene.frame_end - context.scene.frame_start + 1)
    tested_frames = max(1, props.last_tested_frames)

    per_frame_base = props.baseline_time / tested_frames
    per_frame_hyper = props.hyper_time / tested_frames
    full_anim_base = per_frame_base * total_timeline_frames
    full_anim_hyper = per_frame_hyper * total_timeline_frames

    def draw_popup(self, _ctx):
        layout = self.layout
        col = layout.column(align=True)
        mode_lbl = f"{tested_frames}-Frame Animation Test" if tested_frames > 1 else "1-Frame Image Test"
        col.label(text=f"TEST MODE: {mode_lbl}", icon='RENDER_ANIMATION' if tested_frames > 1 else 'RENDER_STILL')
        col.separator()
        col.label(text=f"WITHOUT Add-on (Left / Red):   {_format_duration(props.baseline_time)}", icon='CANCEL')
        col.label(text=f"WITH HyperRender (Right / Green): {_format_duration(props.hyper_time)}", icon='CHECKMARK')
        col.separator()
        col.label(text=f"SPEEDUP:  {props.speedup_pct:.1f}% FASTER!  ({props.speedup_mult:.1f}x Speed)", icon='SHADERFX')
        col.label(text=f"TIME SAVED IN THIS TEST:  {_format_duration(saved_s)}", icon='TIME')
        col.separator()
        col.label(text=f"FULL ANIMATION ({total_timeline_frames} Frames):", icon='SEQUENCE')
        col.label(text=f"  • Full Animation WITHOUT Add-on:  {_format_duration(full_anim_base)}")
        col.label(text=f"  • Full Animation WITH HyperRender: {_format_duration(full_anim_hyper)}")

    try:
        context.window_manager.popup_menu(
            draw_popup,
            title=f"HYPERRENDER RESULT: {props.speedup_pct:.1f}% FASTER ({props.speedup_mult:.1f}x)!",
            icon='CHECKMARK',
        )
    except Exception:
        pass


class HyperRenderCameraSettings(PropertyGroup):
    use_in_queue: BoolProperty(name="Include in Batch Queue", default=True)
    profile_override: EnumProperty(
        name="Camera Profile",
        items=[
            ("SCENE_DEFAULT", "Use Scene Profile", ""),
            ("HYPER_90", "Hyper 12x Turbo", ""),
            ("ULTRA_DRAFT", "Ultra Draft 95%", ""),
            ("ARCHVIZ_GLASS", "ArchViz & Glass", ""),
            ("ANIMATION_LOCK", "Animation Lock", ""),
        ],
        default="SCENE_DEFAULT",
    )
    resolution_scale: IntProperty(name="Res %", default=100, min=10, max=200, subtype='PERCENTAGE')
    last_render_time: FloatProperty(name="Last Render Time (s)", default=0.0)


class HyperRenderProperties(PropertyGroup):
    license_key_input: StringProperty(
        name="License Key",
        description="Paste your Gumroad or Superhive License Key to unlock HyperRender Studio on this PC",
        default="",
    )
    license_status_msg: StringProperty(default="")

    active_tier_mode: EnumProperty(
        name="Edition",
        items=[
            ("STUDIO_ULTRA", "Ultra 12x ($55)", "All Engines: Global Add-on Boost + GPU Guide + Rigging + Shader Bypass"),
        ],
        default="STUDIO_ULTRA",
    )

    profile_mode: EnumProperty(
        name="Mode",
        items=[
            ("HYPER_90", "12x Turbo Production (Recommended)", ""),
            ("ULTRA_DRAFT", "95% Ultra-Fast Preview", ""),
            ("ARCHVIZ_GLASS", "Interior & Heavy Glass", ""),
            ("ANIMATION_LOCK", "Animation Sequence Lock", ""),
        ],
        default="HYPER_90",
    )

    anim_test_frames: IntProperty(
        name="Anim Test Frames",
        description="How many consecutive frames to render WITHOUT vs WITH when testing animation speed",
        default=3,
        min=2,
        max=250,
    )

    use_multipass_compositor: BoolProperty(default=True)
    enable_rig_accelerator: BoolProperty(default=True)
    enable_uv_shader_bypass: BoolProperty(default=True)
    use_cas_sharpener: BoolProperty(default=True)
    micro_sharpen_strength: FloatProperty(default=0.18, min=0.0, max=1.0)
    use_firefly_despeckle: BoolProperty(default=True)
    use_smaa_anti_aliasing: BoolProperty(default=True)
    enable_camera_cull: BoolProperty(default=True)
    enable_vram_guard: BoolProperty(default=True)
    enable_fast_gi: BoolProperty(default=True)
    texture_limit: EnumProperty(
        items=[("OFF", "No Limit", ""), ("4096", "4K", ""), ("2048", "2K", "")],
        default="4096",
    )
    enable_viewport_turbo_on_apply: BoolProperty(default=True)
    viewport_turbo_active: BoolProperty(default=False)
    detected_device_label: StringProperty(default="")

    batch_output_dir: StringProperty(default="//hyperrender_batch/", subtype='DIR_PATH')
    last_batch_report_json: StringProperty(default="")
    last_batch_count: IntProperty(default=0)
    last_batch_total_time: FloatProperty(default=0.0)

    is_active: BoolProperty(
        name="12x Boost Active",
        description="When ON, accelerates all renders by 12x+ whether you render with F12, Ctrl+F12, or another add-on",
        default=False,
    )
    has_audit: BoolProperty(default=False)
    audit_report_json: StringProperty(default="")
    snapshot_json: StringProperty(default="")

    has_benchmark: BoolProperty(default=False)
    last_tested_frames: IntProperty(default=1)
    baseline_time: FloatProperty(default=0.0)
    hyper_time: FloatProperty(default=0.0)
    speedup_pct: FloatProperty(default=0.0)
    speedup_mult: FloatProperty(default=1.0)
    hours_saved_250: FloatProperty(default=0.0)


class HYPERRENDER_OT_activate_license(Operator):
    bl_idname = "hyperrender.activate_license"
    bl_label = "Activate License on This PC"
    bl_description = "Verifies your License Key and binds it to this computer's Hardware ID (HWID)"

    def execute(self, context):
        props = context.scene.hyperrender
        ok, msg = activate_license_on_this_machine(props.license_key_input)
        props.license_status_msg = msg
        if ok:
            self.report({'INFO'}, msg)
        else:
            self.report({'ERROR'}, msg)
        return {'FINISHED'}


class HYPERRENDER_OT_deactivate_license(Operator):
    bl_idname = "hyperrender.deactivate_license"
    bl_label = "Lock / Deactivate PC"
    bl_description = "Deactivate this PC to test the License Lock screen or move your license to another PC"

    def execute(self, context):
        deactivate_license_on_this_machine()
        context.scene.hyperrender.license_status_msg = "License deactivated on this PC."
        self.report({'INFO'}, "HyperRender locked on this PC.")
        return {'FINISHED'}


class HYPERRENDER_OT_toggle_boost(Operator):
    bl_idname = "hyperrender.toggle_boost"
    bl_label = "Toggle 12x Boost (All Renders & Add-ons)"
    bl_description = (
        "Turn 12x Boost ON or OFF. When ON, whatever method you use to render—built-in F12/Ctrl+F12 "
        "or ANY third-party add-on—is automatically accelerated 12x+ for both Images and Animations"
    )
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        if not is_machine_licensed():
            self.report({'ERROR'}, "Please activate your License Key first.")
            return {'CANCELLED'}

        props = context.scene.hyperrender
        if props.is_active:
            restore_scene_snapshot(context)
            self.report({'INFO'}, "HyperRender 12x Boost Turned OFF — Restored original Blender settings.")
            return {'FINISHED'}

        if context.scene.render.engine != 'CYCLES':
            context.scene.render.engine = 'CYCLES'

        res = apply_hyperrender_acceleration(context)
        self.report(
            {'INFO'},
            f"12x BOOST IS NOW ON [{res['hardware']}]: Render with F12, Ctrl+F12, or ANY add-on at 12x+ speed!",
        )
        return {'FINISHED'}


class HYPERRENDER_OT_one_click_render(Operator):
    bl_idname = "hyperrender.one_click_render"
    bl_label = "1-Click Turbo Render (Image)"
    bl_description = "Automatically sets up a camera if missing, turns ON 12x HyperRender Boost, and renders a still image immediately"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        if not is_machine_licensed():
            self.report({'ERROR'}, "Please activate your License Key first.")
            return {'CANCELLED'}
        if context.scene.render.engine != 'CYCLES':
            context.scene.render.engine = 'CYCLES'
        ensure_camera_and_lighting(context)
        res = apply_hyperrender_acceleration(context)
        self.report({'INFO'}, f"HyperRender 12x Engaged ({res['profile_name']}) — Rendering Image...")
        bpy.ops.render.render('INVOKE_DEFAULT')
        return {'FINISHED'}


class HYPERRENDER_OT_one_click_animation(Operator):
    bl_idname = "hyperrender.one_click_animation"
    bl_label = "1-Click Turbo Animation"
    bl_description = "Turns ON 12x Persistent VRAM + Animation Lock and renders your entire animation 12x+ faster"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        if not is_machine_licensed():
            self.report({'ERROR'}, "Please activate your License Key first.")
            return {'CANCELLED'}
        if context.scene.render.engine != 'CYCLES':
            context.scene.render.engine = 'CYCLES'
        ensure_camera_and_lighting(context)
        context.scene.hyperrender.profile_mode = 'ANIMATION_LOCK'
        res = apply_hyperrender_acceleration(context)
        self.report({'INFO'}, f"HyperRender 12x Animation Lock Engaged ({res['profile_name']}) — Rendering Animation...")
        bpy.ops.render.render('INVOKE_DEFAULT', animation=True)
        return {'FINISHED'}


class HYPERRENDER_OT_apply_acceleration(Operator):
    bl_idname = "hyperrender.apply_acceleration"
    bl_label = "Engage HyperRender Only (Don't Render Yet)"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        if not is_machine_licensed():
            self.report({'ERROR'}, "Please activate your License Key first.")
            return {'CANCELLED'}
        if context.scene.render.engine != 'CYCLES':
            context.scene.render.engine = 'CYCLES'
        res = apply_hyperrender_acceleration(context)
        self.report({'INFO'}, f"HyperRender 12x Active [{res['hardware']}]: Ready for F12 or any add-on!")
        return {'FINISHED'}


class HYPERRENDER_OT_show_report_popup(Operator):
    bl_idname = "hyperrender.show_report_popup"
    bl_label = "Show Full Speed Report Popup"

    def execute(self, context):
        props = context.scene.hyperrender
        tmp_dir = tempfile.gettempdir()
        base_img = os.path.join(tmp_dir, "hyperrender_WITHOUT_addon.png")
        hyper_img = os.path.join(tmp_dir, "hyperrender_WITH_addon.png")
        build_and_show_side_by_side_image(
            context, base_img, hyper_img, props.baseline_time, props.hyper_time, props.speedup_pct
        )
        _show_benchmark_popup(context)
        return {'FINISHED'}


class HYPERRENDER_OT_run_benchmark(Operator):
    bl_idname = "hyperrender.run_benchmark"
    bl_label = "Compare Image: WITHOUT vs WITH (1 Shot)"
    bl_description = "Renders 1 frame WITHOUT the add-on and 1 frame WITH the add-on, then displays both side-by-side"
    bl_options = {'REGISTER'}

    def execute(self, context):
        if not is_machine_licensed():
            self.report({'ERROR'}, "Please activate your License Key first.")
            return {'CANCELLED'}
        if context.scene.render.engine != 'CYCLES':
            context.scene.render.engine = 'CYCLES'

        scene = context.scene
        props = scene.hyperrender

        ensure_camera_and_lighting(context)

        if props.is_active and props.snapshot_json:
            restore_scene_snapshot(context)

        orig_filepath = scene.render.filepath
        orig_res_pct = scene.render.resolution_percentage
        saved_output = _force_png_output(scene)

        tmp_dir = tempfile.gettempdir()
        base_img = os.path.join(tmp_dir, "hyperrender_WITHOUT_addon.png")
        hyper_img = os.path.join(tmp_dir, "hyperrender_WITH_addon.png")

        try:
            scene.render.filepath = base_img
            t0 = time.perf_counter()
            bpy.ops.render.render(write_still=True)
            t_base = max(0.05, time.perf_counter() - t0)

            apply_hyperrender_acceleration(context)
            scene.render.filepath = hyper_img
            t1 = time.perf_counter()
            bpy.ops.render.render(write_still=True)
            t_hyper = max(0.02, time.perf_counter() - t1)

            props.last_tested_frames = 1
            props.baseline_time = round(t_base, 2)
            props.hyper_time = round(t_hyper, 2)
            props.speedup_mult = round(t_base / t_hyper, 2)
            props.speedup_pct = round(((t_base - t_hyper) / t_base) * 100.0, 1)
            props.hours_saved_250 = round(((t_base - t_hyper) * 250.0) / 3600.0, 2)
            props.has_benchmark = True

            build_and_show_side_by_side_image(
                context, base_img, hyper_img, props.baseline_time, props.hyper_time, props.speedup_pct
            )
            self.report(
                {'INFO'},
                f"IMAGE TEST DONE: OFF = {props.baseline_time:.1f}s | ON = {props.hyper_time:.1f}s -> {props.speedup_pct:.1f}% FASTER ({props.speedup_mult:.1f}x)!",
            )
            _show_benchmark_popup(context)
        finally:
            _restore_output(scene, saved_output)
            scene.render.filepath = orig_filepath
            scene.render.resolution_percentage = orig_res_pct

        return {'FINISHED'}


class HYPERRENDER_OT_run_animation_benchmark(Operator):
    bl_idname = "hyperrender.run_animation_benchmark"
    bl_label = "Compare Animation: WITHOUT vs WITH (Multi-Frame)"
    bl_description = "Renders multiple consecutive animation frames WITHOUT the add-on vs WITH HyperRender Animation Lock"
    bl_options = {'REGISTER'}

    def execute(self, context):
        if not is_machine_licensed():
            self.report({'ERROR'}, "Please activate your License Key first.")
            return {'CANCELLED'}
        if context.scene.render.engine != 'CYCLES':
            context.scene.render.engine = 'CYCLES'

        scene = context.scene
        props = scene.hyperrender

        ensure_camera_and_lighting(context)

        if props.is_active and props.snapshot_json:
            restore_scene_snapshot(context)

        orig_filepath = scene.render.filepath
        orig_frame = scene.frame_current
        n_frames = max(2, props.anim_test_frames)
        saved_output = _force_png_output(scene)

        tmp_dir = tempfile.gettempdir()
        base_img = os.path.join(tmp_dir, "hyperrender_WITHOUT_addon.png")
        hyper_img = os.path.join(tmp_dir, "hyperrender_WITH_addon.png")

        try:
            t0 = time.perf_counter()
            for i in range(n_frames):
                scene.frame_set(orig_frame + i)
                scene.render.filepath = base_img if i == n_frames - 1 else os.path.join(tmp_dir, f"hr_off_f{i}.png")
                bpy.ops.render.render(write_still=True)
            t_base = max(0.05, time.perf_counter() - t0)

            props.profile_mode = 'ANIMATION_LOCK'
            apply_hyperrender_acceleration(context)
            t1 = time.perf_counter()
            for i in range(n_frames):
                scene.frame_set(orig_frame + i)
                scene.render.filepath = hyper_img if i == n_frames - 1 else os.path.join(tmp_dir, f"hr_on_f{i}.png")
                bpy.ops.render.render(write_still=True)
            t_hyper = max(0.02, time.perf_counter() - t1)

            props.last_tested_frames = n_frames
            props.baseline_time = round(t_base, 2)
            props.hyper_time = round(t_hyper, 2)
            props.speedup_mult = round(t_base / t_hyper, 2)
            props.speedup_pct = round(((t_base - t_hyper) / t_base) * 100.0, 1)
            per_frame_saved = (t_base - t_hyper) / n_frames
            props.hours_saved_250 = round((per_frame_saved * 250.0) / 3600.0, 2)
            props.has_benchmark = True

            build_and_show_side_by_side_image(
                context, base_img, hyper_img, props.baseline_time, props.hyper_time, props.speedup_pct
            )
            self.report(
                {'INFO'},
                f"ANIMATION TEST ({n_frames} Frames): OFF = {props.baseline_time:.1f}s | ON = {props.hyper_time:.1f}s -> {props.speedup_pct:.1f}% FASTER ({props.speedup_mult:.1f}x)!",
            )
            _show_benchmark_popup(context)
        finally:
            _restore_output(scene, saved_output)
            scene.frame_set(orig_frame)
            scene.render.filepath = orig_filepath

        return {'FINISHED'}


class HYPERRENDER_OT_restore_original(Operator):
    bl_idname = "hyperrender.restore_original"
    bl_label = "Turn Off / Reset Normal Blender"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        restore_scene_snapshot(context)
        self.report({'INFO'}, "Reverted to normal unoptimized Blender settings.")
        return {'FINISHED'}


class HYPERRENDER_OT_analyze_scene(Operator):
    bl_idname = "hyperrender.analyze_scene"
    bl_label = "Analyze Scene"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        analyze_scene_bottlenecks(context)
        return {'FINISHED'}


class HYPERRENDER_OT_toggle_viewport_turbo(Operator):
    bl_idname = "hyperrender.toggle_viewport_turbo"
    bl_label = "Toggle 60-FPS Viewport Turbo"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        props = context.scene.hyperrender
        apply_viewport_turbo_boost(context, enable=not props.viewport_turbo_active)
        return {'FINISHED'}


class HYPERRENDER_OT_render_camera_queue(Operator):
    bl_idname = "hyperrender.render_camera_queue"
    bl_label = "Render Camera Queue"
    bl_options = {'REGISTER'}

    def execute(self, context):
        execute_multi_camera_batch_queue(context)
        return {'FINISHED'}


class HYPERRENDER_PT_main_panel(Panel):
    bl_label = "HyperRender (1-Click 12x Turbo)"
    bl_idname = "HYPERRENDER_PT_main_panel"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'HyperRender'

    def draw(self, context):
        layout = self.layout
        scene = context.scene
        props = scene.hyperrender
        hwid = get_machine_hwid()

        # HARDWARE-BOUND LICENSE GATE
        if not is_machine_licensed():
            lock_box = layout.box()
            lock_box.label(text="LICENSE ACTIVATION REQUIRED", icon='LOCKED')
            lock_box.label(text=f"PC HWID: {hwid[:10]}...", icon='DESKTOP')
            lock_box.prop(props, "license_key_input", text="Key")
            act_row = lock_box.row(align=True)
            act_row.scale_y = 1.6
            act_row.operator(
                "hyperrender.activate_license",
                text="ACTIVATE ON THIS PC",
                icon='KEY_HLT',
            )
            if props.license_status_msg:
                lock_box.label(text=props.license_status_msg, icon='INFO')
            lock_box.separator()
            buy_row = lock_box.row(align=True)
            buy_row.operator(
                "wm.url_open",
                text="Get License Key ($55) ->",
                icon='URL',
            ).url = STORE_BUY_URL
            return

        # =====================================================================
        # 1. MASTER ON/OFF SWITCH (Accelerates Built-in F12 & ANY Other Add-on!)
        # =====================================================================
        boost_box = layout.box()
        toggle_row = boost_box.row(align=True)
        toggle_row.scale_y = 2.1
        if props.is_active:
            toggle_row.operator(
                "hyperrender.toggle_boost",
                text="12x BOOST: ON (Click to Turn Off)",
                icon='CHECKMARK',
                depress=True,
            )
            boost_box.label(text="Active for F12, Ctrl+F12 & All Add-ons", icon='SHADERFX')
        else:
            toggle_row.operator(
                "hyperrender.toggle_boost",
                text="TURN ON 12x BOOST (All Renders)",
                icon='PLAY',
                depress=False,
            )
            boost_box.label(text="Turn ON to speed up any add-on or F12", icon='INFO')

        layout.separator()

        # =====================================================================
        # 2. OR RENDER DIRECTLY IN 1 CLICK (Image or Animation)
        # =====================================================================
        col_main = layout.column(align=True)
        col_main.label(text="Or Render Directly Now:")
        row_img = col_main.row(align=True)
        row_img.scale_y = 1.75
        row_img.operator(
            "hyperrender.one_click_render",
            text="1-CLICK TURBO IMAGE (12x)",
            icon='RENDER_STILL',
        )
        row_anim = col_main.row(align=True)
        row_anim.scale_y = 1.65
        row_anim.operator(
            "hyperrender.one_click_animation",
            text="1-CLICK TURBO ANIMATION (12x)",
            icon='RENDER_ANIMATION',
        )

        layout.separator()

        # =====================================================================
        # 3. COMPARE WITHOUT vs WITH (Stopwatch Proof)
        # =====================================================================
        box_test = layout.box()
        box_test.label(text="Compare WITHOUT vs WITH:", icon='TIME')
        col_test = box_test.column(align=True)

        r1 = col_test.row(align=True)
        r1.scale_y = 1.5
        r1.operator(
            "hyperrender.run_benchmark",
            text="TEST IMAGE: OFF vs ON",
            icon='RENDER_STILL',
        )

        col_test.separator()
        col_test.prop(props, "anim_test_frames", text="Test Frames")
        r2 = col_test.row(align=True)
        r2.scale_y = 1.5
        r2.operator(
            "hyperrender.run_animation_benchmark",
            text=f"TEST ANIM ({props.anim_test_frames}f): OFF vs ON",
            icon='RENDER_ANIMATION',
        )

        # ULTRA-COMPACT SCOREBOARD
        if props.has_benchmark:
            res_box = layout.box()
            saved_s = max(0.0, props.baseline_time - props.hyper_time)
            col = res_box.column(align=True)
            col.scale_y = 1.25
            tag = f"({props.last_tested_frames}f Anim)" if props.last_tested_frames > 1 else "(1 Shot)"
            col.label(text=f"{props.speedup_pct:.1f}% FASTER {tag}", icon='SHADERFX')
            col.label(text=f"Speed: {props.speedup_mult:.1f}x Faster")
            col.separator()
            col.label(text=f"{props.baseline_time:.1f}s  <- OFF (Before)", icon='CANCEL')
            col.label(text=f"{props.hyper_time:.1f}s  <- ON  (After)", icon='CHECKMARK')
            col.label(text=f"-{saved_s:.1f}s Saved!", icon='TIME')
            col.separator()
            col.operator(
                "hyperrender.show_report_popup",
                text="Show Side-by-Side & Report",
                icon='IMAGE_BACKGROUND',
            )

        # Hardware License Status Badge at bottom (Gumroad Edition only)
        if not is_drm_free_build():
            lic_row = layout.row(align=True)
            lic_row.label(text=f"PC Locked: {hwid[:8]}", icon='UNLOCKED')
            lic_row.operator("hyperrender.deactivate_license", text="", icon='LOCKED')


CLASSES = (
    HyperRenderCameraSettings,
    HyperRenderProperties,
    HYPERRENDER_OT_activate_license,
    HYPERRENDER_OT_deactivate_license,
    HYPERRENDER_OT_toggle_boost,
    HYPERRENDER_OT_one_click_render,
    HYPERRENDER_OT_one_click_animation,
    HYPERRENDER_OT_apply_acceleration,
    HYPERRENDER_OT_show_report_popup,
    HYPERRENDER_OT_toggle_viewport_turbo,
    HYPERRENDER_OT_restore_original,
    HYPERRENDER_OT_render_camera_queue,
    HYPERRENDER_OT_run_benchmark,
    HYPERRENDER_OT_run_animation_benchmark,
    HYPERRENDER_OT_analyze_scene,
    HYPERRENDER_PT_main_panel,
)


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)
    bpy.types.Scene.hyperrender = PointerProperty(type=HyperRenderProperties)
    bpy.types.Object.hyperrender_cam = PointerProperty(type=HyperRenderCameraSettings)

    if _hyperrender_on_render_init not in bpy.app.handlers.render_init:
        bpy.app.handlers.render_init.append(_hyperrender_on_render_init)
    if _hyperrender_on_render_pre not in bpy.app.handlers.render_pre:
        bpy.app.handlers.render_pre.append(_hyperrender_on_render_pre)


def unregister():
    if _hyperrender_on_render_pre in bpy.app.handlers.render_pre:
        bpy.app.handlers.render_pre.remove(_hyperrender_on_render_pre)
    if _hyperrender_on_render_init in bpy.app.handlers.render_init:
        bpy.app.handlers.render_init.remove(_hyperrender_on_render_init)

    if hasattr(bpy.types.Object, "hyperrender_cam"):
        del bpy.types.Object.hyperrender_cam
    if hasattr(bpy.types.Scene, "hyperrender"):
        del bpy.types.Scene.hyperrender
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)


if __name__ == "__main__":
    register()
