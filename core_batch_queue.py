# SPDX-License-Identifier: GPL-3.0-or-later
# HyperRender Studio v2.0 Enterprise - Multi-Camera Batch Render Queue & Studio Telemetry Exporter

import json
import os
import tempfile
import time
import bpy
from .core_optimizer import apply_hyperrender_acceleration, restore_scene_snapshot


def execute_multi_camera_batch_queue(context, output_dir=""):
    """
    Render all queued cameras in the scene using their per-camera HyperRender Studio profiles,
    saving each rendered frame and generating a verified Studio Telemetry Report.
    """
    scene = context.scene
    props = scene.hyperrender

    if not output_dir:
        if scene.render.filepath and not scene.render.filepath.startswith("//"):
            base_out = os.path.dirname(scene.render.filepath)
        else:
            base_out = os.path.join(tempfile.gettempdir(), "HyperRender_Batch_Output")
    else:
        base_out = bpy.path.abspath(output_dir)

    os.makedirs(base_out, exist_ok=True)

    # Collect enabled cameras
    cameras = [
        obj for obj in scene.objects
        if obj.type == 'CAMERA' and getattr(obj, "hyperrender_cam", None) and obj.hyperrender_cam.use_in_queue
    ]
    if not cameras and scene.camera:
        cameras = [scene.camera]

    orig_cam = scene.camera
    orig_filepath = scene.render.filepath
    orig_res_pct = scene.render.resolution_percentage
    orig_profile = props.profile_mode

    batch_results = []
    t_batch_start = time.perf_counter()

    try:
        for idx, cam in enumerate(cameras):
            scene.camera = cam
            cam_cfg = getattr(cam, "hyperrender_cam", None)

            # Apply per-camera profile override if specified
            if cam_cfg and cam_cfg.profile_override != "SCENE_DEFAULT":
                props.profile_mode = cam_cfg.profile_override
            else:
                props.profile_mode = orig_profile

            if cam_cfg:
                scene.render.resolution_percentage = cam_cfg.resolution_scale

            # Apply HyperRender acceleration tailored to this camera's frustum & profile
            accel_info = apply_hyperrender_acceleration(context)

            safe_name = "".join(c if c.isalnum() or c in "-_" else "_" for c in cam.name)
            out_file = os.path.join(base_out, f"{idx + 1:02d}_{safe_name}_HyperRender.png")
            scene.render.filepath = out_file

            t0 = time.perf_counter()
            bpy.ops.render.render(write_still=True)
            elapsed = round(time.perf_counter() - t0, 2)

            if cam_cfg:
                cam_cfg.last_render_time = elapsed

            batch_results.append({
                "index": idx + 1,
                "camera_name": cam.name,
                "profile_used": accel_info["profile_name"],
                "samples": accel_info["samples"],
                "culled_meshes": accel_info["culled_meshes"],
                "resolution_scale": scene.render.resolution_percentage,
                "render_time_sec": elapsed,
                "output_path": out_file,
            })

    finally:
        scene.camera = orig_cam
        scene.render.filepath = orig_filepath
        scene.render.resolution_percentage = orig_res_pct
        props.profile_mode = orig_profile

    total_elapsed = round(time.perf_counter() - t_batch_start, 2)

    telemetry_report = {
        "studio_suite": "HyperRender Studio v2.0 Enterprise",
        "blender_version": ".".join(map(str, bpy.app.version)),
        "total_cameras_rendered": len(batch_results),
        "total_batch_time_sec": total_elapsed,
        "output_directory": base_out,
        "shots": batch_results,
    }

    report_json_path = os.path.join(base_out, "HyperRender_Batch_Telemetry.json")
    with open(report_json_path, "w", encoding="utf-8") as f:
        json.dump(telemetry_report, f, indent=2)

    props.last_batch_report_json = json.dumps(telemetry_report)
    props.last_batch_count = len(batch_results)
    props.last_batch_total_time = total_elapsed

    return telemetry_report
