# SPDX-License-Identifier: GPL-3.0-or-later
# HyperRender Studio - Automatic Camera & Studio Lighting Setup for Raw Model Files

import math
import bpy
from mathutils import Vector


def ensure_camera_and_lighting(context):
    """
    If the opened .blend file has no active Camera (or no Lights), automatically create
    a Camera snapped to the user's current 3D Viewport view (or auto-framed on the model)
    and ensure illumination exists so 1-Click Render NEVER fails.
    """
    scene = context.scene
    created_cam = False
    created_lights = False

    # 1. Ensure an active Camera exists
    if not scene.camera:
        existing_cams = [o for o in scene.objects if o.type == 'CAMERA']
        if existing_cams:
            scene.camera = existing_cams[0]
        else:
            cam_data = bpy.data.cameras.new("HyperRender_AutoCam")
            cam_data.lens = 50.0
            cam_obj = bpy.data.objects.new("HyperRender_AutoCam", cam_data)
            scene.collection.objects.link(cam_obj)
            scene.camera = cam_obj
            cam_obj["hr_auto_created"] = True
            created_cam = True

            # Try to match the user's active 3D Viewport perspective first
            matched_viewport = False
            if context.screen:
                for area in context.screen.areas:
                    if area.type == 'VIEW_3D':
                        for space in area.spaces:
                            if space.type == 'VIEW_3D' and space.region_3d:
                                r3d = space.region_3d
                                view_mat = r3d.view_matrix.inverted()
                                cam_obj.matrix_world = view_mat
                                matched_viewport = True
                                break
                    if matched_viewport:
                        break

            # Fallback: Auto-frame the bounding box of all visible meshes
            if not matched_viewport:
                min_co = Vector((1e9, 1e9, 1e9))
                max_co = Vector((-1e9, -1e9, -1e9))
                has_mesh = False
                for obj in scene.objects:
                    if obj.type == 'MESH' and not obj.hide_render and obj.bound_box:
                        has_mesh = True
                        for corner in obj.bound_box:
                            w_co = obj.matrix_world @ Vector(corner)
                            min_co.x = min(min_co.x, w_co.x)
                            min_co.y = min(min_co.y, w_co.y)
                            min_co.z = min(min_co.z, w_co.z)
                            max_co.x = max(max_co.x, w_co.x)
                            max_co.y = max(max_co.y, w_co.y)
                            max_co.z = max(max_co.z, w_co.z)

                if has_mesh:
                    center = (min_co + max_co) * 0.5
                    size = max(1.0, (max_co - min_co).length)
                    dist = size * 1.35
                    cam_obj.location = center + Vector((dist * 0.65, -dist * 0.85, dist * 0.45))
                    direction = center - cam_obj.location
                    rot_quat = direction.to_track_quat('-Z', 'Y')
                    cam_obj.rotation_euler = rot_quat.to_euler()
                    cam_data.clip_end = max(1000.0, dist * 10.0)
                else:
                    cam_obj.location = (0.0, -5.0, 2.0)
                    cam_obj.rotation_euler = (math.radians(70.0), 0.0, 0.0)

    # 2. Ensure scene has illumination (if 0 lights and dark/empty world)
    lights = [o for o in scene.objects if o.type == 'LIGHT' and not o.hide_render]
    if not lights:
        cam_loc = scene.camera.location if scene.camera else Vector((0.0, -5.0, 3.0))
        key_data = bpy.data.lights.new("HR_AutoSun", 'SUN')
        key_data.energy = 3.5
        key_data.angle = math.radians(12.0)
        key_obj = bpy.data.objects.new("HR_AutoSun", key_data)
        scene.collection.objects.link(key_obj)
        key_obj.location = cam_loc + Vector((4.0, -2.0, 8.0))
        key_obj.rotation_euler = (math.radians(45.0), math.radians(15.0), math.radians(30.0))
        key_obj["hr_auto_created"] = True
        created_lights = True

    return created_cam, created_lights
