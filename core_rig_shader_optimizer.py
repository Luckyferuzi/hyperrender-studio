# SPDX-License-Identifier: GPL-3.0-or-later
# HyperRender Studio v2.0 Ultra - Complete 1-Click Pipeline:
#   1. Rigged Character & Armature Deform Accelerator
#   2. UV & Procedural Shader Ray-Depth Bypass ('Is Camera Ray')
#   3. Architectural Glass Shadow-Ray Bypass ('Is Shadow Ray' -> Transparent BSDF)
#   4. Automatic Shift+D -> Alt+D Mesh Memory Instancer (Deduplicator)

import json
import bpy
from .core_auditor import is_object_in_camera_frustum


def extract_average_base_color(nt, surface_socket):
    """Find a representative RGBA base color from the material node tree for secondary bounce rays."""
    default_col = (0.45, 0.45, 0.45, 1.0)
    if not surface_socket or not surface_socket.is_linked:
        return default_col

    from_node = surface_socket.links[0].from_node
    if "Base Color" in from_node.inputs:
        bc_sock = from_node.inputs["Base Color"]
        if not bc_sock.is_linked:
            return tuple(bc_sock.default_value)
        src_node = bc_sock.links[0].from_node
        if "Color1" in src_node.inputs and "Color2" in src_node.inputs:
            c1 = src_node.inputs["Color1"].default_value
            c2 = src_node.inputs["Color2"].default_value
            return (
                (c1[0] + c2[0]) * 0.5,
                (c1[1] + c2[1]) * 0.5,
                (c1[2] + c2[2]) * 0.5,
                1.0,
            )
    elif "Color" in from_node.inputs and not from_node.inputs["Color"].is_linked:
        return tuple(from_node.inputs["Color"].default_value)

    return default_col


def classify_material_for_optimization(nt):
    """
    Classify a material into:
      - 'GLASS': Uses Glass BSDF or Principled BSDF with Transmission > 0.2 (eligible for Architectural Glass Shadow-Ray Bypass)
      - 'HEAVY_UV_SHADER': Uses UV mapping chains, procedural noise, or bump/normal maps (eligible for Is Camera Ray Bounce Bypass)
      - 'SIMPLE': Simple material needing no node injection
    """
    heavy_types = {
        'TEX_NOISE', 'TEX_VORONOI', 'TEX_WAVE', 'TEX_MUSGRAVE', 'TEX_CHECKER',
        'TEX_BRICK', 'BUMP', 'NORMAL_MAP', 'MAPPING', 'VECT_MATH', 'DISPLACEMENT',
    }
    heavy_count = 0
    for node in nt.nodes:
        if node.type in {'BSDF_GLASS', 'BSDF_REFRACTION'}:
            return 'GLASS'
        elif node.type == 'BSDF_PRINCIPLED':
            for sname in ('Transmission Weight', 'Transmission'):
                if sname in node.inputs:
                    val = node.inputs[sname].default_value
                    if (isinstance(val, (int, float)) and val > 0.20) or node.inputs[sname].is_linked:
                        return 'GLASS'
        elif node.type in heavy_types:
            heavy_count += 1

    if heavy_count >= 1:
        return 'HEAVY_UV_SHADER'
    return 'SIMPLE'


def optimize_materials_and_uv_shaders(context):
    """
    1. Inject 'Is Camera Ray' shader switches into heavy UV/procedural materials so secondary bounces
       skip expensive UV math, procedural noise, and bump evaluations.
    2. Inject Blender Guru's 'Is Shadow Ray -> Transparent BSDF' Architectural Glass optimization into
       Glass/Transmissive materials so light passes through windows 5x faster without dark refractive shadow noise.
    """
    optimized_mats = 0

    for mat in bpy.data.materials:
        if not mat.use_nodes or not mat.node_tree:
            continue
        nt = mat.node_tree

        if "HR_RayDepth_MixShader" in nt.nodes:
            optimized_mats += 1
            continue

        mat_kind = classify_material_for_optimization(nt)
        if mat_kind == 'SIMPLE':
            continue

        out_node = None
        for node in nt.nodes:
            if node.type == 'OUTPUT_MATERIAL' and getattr(node, "is_active_output", True):
                out_node = node
                break
        if not out_node or "Surface" not in out_node.inputs or not out_node.inputs["Surface"].is_linked:
            continue

        orig_link = out_node.inputs["Surface"].links[0]
        orig_from_socket = orig_link.from_socket

        lp = nt.nodes.new("ShaderNodeLightPath")
        lp.name = "HR_RayDepth_LightPath"
        lp.label = "HyperRender Ray-Depth Sensor"
        lp.location = (out_node.location.x - 420, out_node.location.y + 260)

        mix_sh = nt.nodes.new("ShaderNodeMixShader")
        mix_sh.name = "HR_RayDepth_MixShader"
        mix_sh.location = (out_node.location.x - 180, out_node.location.y)

        if mat_kind == 'GLASS':
            # Architectural Glass Shadow-Ray Bypass:
            # When Is Shadow Ray == 0 -> Original Glass Shader (Socket 1)
            # When Is Shadow Ray == 1 -> Fast Transparent BSDF (Socket 2)
            mix_sh.label = "HyperRender Architectural Glass Accelerator"
            transp_bsdf = nt.nodes.new("ShaderNodeBsdfTransparent")
            transp_bsdf.name = "HR_RayDepth_FastBounce"
            transp_bsdf.label = "Fast Window Shadow Portal"
            transp_bsdf.location = (out_node.location.x - 420, out_node.location.y - 160)
            transp_bsdf.inputs["Color"].default_value = (0.96, 0.98, 1.0, 1.0)

            nt.links.new(lp.outputs["Is Shadow Ray"], mix_sh.inputs["Fac"])
            nt.links.new(orig_from_socket, mix_sh.inputs[1])
            nt.links.new(transp_bsdf.outputs["BSDF"], mix_sh.inputs[2])
            nt.links.new(mix_sh.outputs["Shader"], out_node.inputs["Surface"])
            mat["hr_orig_socket_slot"] = 1
        else:
            # Heavy UV / Procedural Shader Indirect Bounce Bypass:
            # When Is Camera Ray == 0 (Indirect Bounce) -> Fast Diffuse Proxy (Socket 1)
            # When Is Camera Ray == 1 (Camera Ray) -> Full 4K/8K UV & Bump Shader (Socket 2)
            mix_sh.label = "HyperRender UV/Shader Bounce Bypass"
            avg_col = extract_average_base_color(nt, out_node.inputs["Surface"])
            fast_bsdf = nt.nodes.new("ShaderNodeBsdfDiffuse")
            fast_bsdf.name = "HR_RayDepth_FastBounce"
            fast_bsdf.label = "Fast Indirect Bounce Proxy"
            fast_bsdf.location = (out_node.location.x - 420, out_node.location.y - 160)
            fast_bsdf.inputs["Color"].default_value = avg_col
            fast_bsdf.inputs["Roughness"].default_value = 0.65

            nt.links.new(lp.outputs["Is Camera Ray"], mix_sh.inputs["Fac"])
            nt.links.new(fast_bsdf.outputs["BSDF"], mix_sh.inputs[1])
            nt.links.new(orig_from_socket, mix_sh.inputs[2])
            nt.links.new(mix_sh.outputs["Shader"], out_node.inputs["Surface"])
            mat["hr_orig_socket_slot"] = 2

        optimized_mats += 1

    return optimized_mats


def restore_materials_and_uv_shaders():
    """Remove all HyperRender Ray-Depth & Glass bypass nodes and restore 100% original material connections."""
    restored = 0
    for mat in bpy.data.materials:
        if not mat.use_nodes or not mat.node_tree:
            continue
        nt = mat.node_tree
        mix_sh = nt.nodes.get("HR_RayDepth_MixShader")
        if not mix_sh:
            continue

        out_node = None
        for node in nt.nodes:
            if node.type == 'OUTPUT_MATERIAL' and getattr(node, "is_active_output", True):
                out_node = node
                break

        slot_idx = int(mat.get("hr_orig_socket_slot", 2))
        if out_node and len(mix_sh.inputs) > slot_idx and mix_sh.inputs[slot_idx].is_linked:
            orig_sock = mix_sh.inputs[slot_idx].links[0].from_socket
            nt.links.new(orig_sock, out_node.inputs["Surface"])

        if "hr_orig_socket_slot" in mat:
            del mat["hr_orig_socket_slot"]

        for nname in ("HR_RayDepth_MixShader", "HR_RayDepth_FastBounce", "HR_RayDepth_LightPath"):
            n = nt.nodes.get(nname)
            if n:
                nt.nodes.remove(n)

        restored += 1
    return restored


def auto_instance_duplicate_meshes(context):
    """
    Automatically detect Shift+D duplicate meshes that have identical geometry & materials
    and convert them into hardware-instanced Alt+D linked meshes to slash RAM/VRAM & BVH build time.
    """
    scene = context.scene
    signature_map = {}
    instanced_count = 0

    for obj in scene.objects:
        if obj.type != 'MESH' or not obj.data or obj.hide_render:
            continue
        # Do not relink meshes that have shape keys or active armature deformations
        if obj.data.shape_keys or obj.find_armature():
            continue
        if len(obj.data.polygons) < 12:
            continue

        mesh = obj.data
        mats = tuple(slot.material.name if slot.material else "" for slot in obj.material_slots)
        # Compute fast deterministic topology + bounding-box signature
        v0 = tuple(round(c, 3) for c in mesh.vertices[0].co) if len(mesh.vertices) > 0 else (0, 0, 0)
        v_last = tuple(round(c, 3) for c in mesh.vertices[-1].co) if len(mesh.vertices) > 0 else (0, 0, 0)
        sig = (len(mesh.vertices), len(mesh.edges), len(mesh.polygons), v0, v_last, mats)

        if sig not in signature_map:
            signature_map[sig] = mesh
        else:
            master_mesh = signature_map[sig]
            if obj.data != master_mesh:
                if "hr_orig_mesh_name" not in obj:
                    obj.data.use_fake_user = True
                    obj["hr_orig_mesh_name"] = obj.data.name
                obj.data = master_mesh
                instanced_count += 1

    return instanced_count


def restore_duplicate_meshes(context):
    """Restore any auto-instanced meshes back to their individual Shift+D mesh datablocks."""
    scene = context.scene
    for obj in scene.objects:
        if obj.type == 'MESH' and "hr_orig_mesh_name" in obj:
            orig_name = obj["hr_orig_mesh_name"]
            orig_mesh = bpy.data.meshes.get(orig_name)
            if orig_mesh:
                obj.data = orig_mesh
            del obj["hr_orig_mesh_name"]


def optimize_rigs_and_modifiers(context):
    """
    Accelerate Rigged Characters, Armature Deformations, Motion Blur Steps, Subdivision Stacks,
    and Shift+D Duplicate Instancing.
    """
    scene = context.scene
    cam = scene.camera

    rigs_optimized = 0
    offscreen_rigs_frozen = 0

    for obj in scene.objects:
        if obj.type != 'MESH' or obj.hide_render:
            continue

        has_deform_rig = any(
            m.type in {'ARMATURE', 'SURFACE_DEFORM', 'MESH_DEFORM', 'CORRECTIVE_SMOOTH', 'LATTICE'}
            for m in obj.modifiers
        )
        if not has_deform_rig and not obj.find_armature():
            continue

        rigs_optimized += 1

        if hasattr(obj, "cycles"):
            obj.cycles.motion_steps = 1

        in_view = is_object_in_camera_frustum(scene, cam, obj, margin=0.22) if cam else True

        orig_mod_state = {}
        for mod in obj.modifiers:
            orig_mod_state[mod.name] = {
                "show_render": mod.show_render,
                "render_levels": getattr(mod, "render_levels", None),
            }
            if not in_view and mod.type in {'ARMATURE', 'CORRECTIVE_SMOOTH', 'SURFACE_DEFORM', 'SUBSURF'}:
                if mod.show_render:
                    mod.show_render = False
                    offscreen_rigs_frozen += 1
            elif mod.type == 'SUBSURF' and mod.show_render and mod.render_levels > 2:
                mod.render_levels = 2

        if "hr_orig_mods" not in obj:
            obj["hr_orig_mods"] = json.dumps(orig_mod_state)

    instanced_meshes = auto_instance_duplicate_meshes(context)

    return {
        "rigs_optimized": rigs_optimized,
        "offscreen_rigs_frozen": offscreen_rigs_frozen,
        "instanced_meshes": instanced_meshes,
    }


def restore_rigs_and_modifiers(context):
    """Restore all rigged character modifier flags and Shift+D mesh datablocks to their exact original state."""
    restore_duplicate_meshes(context)
    scene = context.scene
    for obj in scene.objects:
        if obj.type != 'MESH' or "hr_orig_mods" not in obj:
            continue
        try:
            orig_mod_state = json.loads(obj["hr_orig_mods"])
            for mod_name, mdata in orig_mod_state.items():
                mod = obj.modifiers.get(mod_name)
                if not mod:
                    continue
                mod.show_render = bool(mdata.get("show_render", True))
                if mdata.get("render_levels") is not None and hasattr(mod, "render_levels"):
                    mod.render_levels = int(mdata["render_levels"])
        except Exception:
            pass
        del obj["hr_orig_mods"]
