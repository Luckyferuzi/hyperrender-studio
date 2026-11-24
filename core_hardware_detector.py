# SPDX-License-Identifier: GPL-3.0-or-later
# HyperRender Studio v2.0 - Universal Auto-Hardware Detector (NVIDIA, AMD, Intel, Apple Metal & CPU)

import bpy


def detect_and_tune_hardware(context):
    """
    Automatically detect the user's compute hardware (OPTIX, CUDA, HIP, ONEAPI, METAL, or CPU)
    and apply optimal device-specific tile sizing, BVH, and memory tuning.
    Disables CPU co-rendering when a dedicated GPU backend (OPTIX/CUDA/HIP/ONEAPI) is active
    so slow CPU threads never bottleneck large GPU tiles.
    """
    scene = context.scene
    c = scene.cycles
    prefs = context.preferences

    detected_backend = "CPU"
    device_name = "Multi-Core CPU"
    is_gpu = False

    if "cycles" in prefs.addons:
        cprefs = prefs.addons["cycles"].preferences
        for dev_type in ("OPTIX", "METAL", "HIP", "ONEAPI", "CUDA"):
            try:
                cprefs.compute_device_type = dev_type
                cprefs.get_devices()
                matching = [d for d in cprefs.devices if d.type == dev_type]
                if matching:
                    # Enable ONLY the dedicated GPU device(s) of this backend; disable CPU so it doesn't bottleneck GPU!
                    for d in cprefs.devices:
                        d.use = (d.type == dev_type)
                    c.device = 'GPU'
                    detected_backend = dev_type
                    device_name = matching[0].name
                    is_gpu = True
                    break
            except Exception:
                continue

    if not is_gpu:
        c.device = 'CPU'
        detected_backend = "CPU"

    if hasattr(c, "use_auto_tile"):
        c.use_auto_tile = True

    if detected_backend in {"OPTIX", "CUDA", "HIP", "ONEAPI"}:
        if hasattr(c, "tile_size"):
            c.tile_size = 2048
    elif detected_backend == "METAL":
        if hasattr(c, "tile_size"):
            c.tile_size = 1024
    else:
        if hasattr(c, "tile_size"):
            c.tile_size = 64

    if hasattr(prefs, "system") and hasattr(prefs.system, "use_gpu_subdivision"):
        try:
            prefs.system.use_gpu_subdivision = True
        except Exception:
            pass

    return {
        "backend": detected_backend,
        "device_name": device_name,
        "is_gpu": is_gpu,
        "tile_size": getattr(c, "tile_size", 2048),
    }
