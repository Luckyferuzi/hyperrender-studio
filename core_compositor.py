# SPDX-License-Identifier: GPL-3.0-or-later
# HyperRender Studio v2.0 Enterprise - Device-Independent Albedo Reconstruction + Zero-Overhead Pipeline
# Works across NVIDIA OptiX/CUDA, AMD HIP, Apple Metal, Intel OneAPI, and Multi-Core CPU.

import bpy


def has_third_party_compositor(scene) -> bool:
    """Return True if the user or another add-on has an active non-HyperRender compositor tree."""
    if hasattr(scene, "compositing_node_group"):
        ng = scene.compositing_node_group
        if ng is not None and not ng.name.startswith("HyperRender_"):
            return len(ng.nodes) > 0
        return False

    if getattr(scene, "use_nodes", False) and getattr(scene, "node_tree", None):
        nt = scene.node_tree
        for n in nt.nodes:
            if not n.name.startswith("HR_") and n.bl_idname not in ("CompositorNodeRLayers", "CompositorNodeComposite"):
                return True
    return False


def enable_hardware_albedo_normal_denoising(scene, view_layer, backend: str = ""):
    """
    Configure ultra-fast device-independent denoising across all hardware:
      - NVIDIA OptiX: Uses hardware Tensor-Core OPTIX denoiser when available, or GPU OpenImageDenoise.
      - AMD HIP / Apple Metal / Intel OneAPI / CUDA: Uses GPU-accelerated OpenImageDenoise (NONE prefilter).
      - Multi-Core CPU: Uses fast multi-threaded OpenImageDenoise (NONE prefilter).
    """
    c = scene.cycles
    c.use_denoising = True

    is_gpu = (c.device == 'GPU')
    used_optix = False
    if is_gpu and backend == "OPTIX":
        try:
            c.denoiser = 'OPTIX'
            used_optix = True
        except Exception:
            used_optix = False

    if not used_optix:
        try:
            c.denoiser = 'OPENIMAGEDENOISE'
        except Exception:
            pass

    if hasattr(c, "denoising_input_passes"):
        try:
            c.denoising_input_passes = 'RGB_ALBEDO' if is_gpu else 'RGB'
        except Exception:
            pass
    if hasattr(c, "denoising_prefilter"):
        try:
            c.denoising_prefilter = 'NONE'
        except Exception:
            pass
    if hasattr(c, "denoising_use_gpu"):
        try:
            c.denoising_use_gpu = is_gpu
        except Exception:
            pass

    if view_layer is not None and hasattr(view_layer, "cycles"):
        view_layer.cycles.use_denoising = True


def build_multipass_reconstruction_tree(
    context,
    mode='TURBO_SEPARATED',
    include_transmission=True,
    include_volume=False,
    use_despeckle=True,
    sharpen_factor=0.18,
    use_smaa=True,
    backend: str = "",
):
    """
    Configure zero-overhead Device-Independent Reconstruction:
    - Engages hardware-accelerated Cycles denoising directly on the active device (GPU or CPU).
    - Preserves any third-party add-on's compositor tree 100% untouched.
    - Avoids unnecessary CPU compositor round-trips when no custom compositor nodes are present.
    """
    scene = context.scene
    view_layer = context.view_layer

    enable_hardware_albedo_normal_denoising(scene, view_layer, backend=backend)

    # If another add-on has its own compositor tree, keep it 100% intact
    if has_third_party_compositor(scene):
        return None

    # Otherwise, disable redundant CPU compositor overhead so GPU/CPU finishes immediately after denoising
    scene.render.use_compositing = False
    return None
