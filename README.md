# HyperRender Studio Enterprise — Scene Auditor, Ray Reconstruction & Batch Render Pipeline

**HyperRender Studio Enterprise** (`v2.0.0`) is a high-performance Python optimization and rendering pipeline add-on for **Blender 4.2+ / 5.x** (Cycles & EEVEE Next). It provides automated hardware telemetry, scene bottleneck auditing, shader/rig optimization, multi-pass denoising & Contrast Adaptive Sharpening (CAS) compositing, smart auto-camera framing, and unattended batch render queuing.

---

## Core Architecture & Modules

| Module | File | Description |
| :--- | :--- | :--- |
| **Scene Performance Auditor** | `core_auditor.py`, `core_visual_report.py` | Analyzes polygon density, subdivision levels, texture memory footprint, light bounces, and shader complexity; exports visual audit diagnostics. |
| **Render & Viewport Optimizer** | `core_optimizer.py`, `core_rig_shader_optimizer.py` | Dynamically tunes Cycles/EEVEE sampling, adaptive threshold, BVH/light tree parameters, and simplifies heavy armatures & shader trees for 60-FPS viewport playback. |
| **Hardware Telemetry Detector** | `core_hardware_detector.py` | Detects GPU compute backends (CUDA, Optix, HIP, Metal, OneAPI) and CPU thread topology to auto-configure optimal tile and memory settings. |
| **Multi-Pass CAS Compositor** | `core_compositor.py` | Builds automated post-processing node networks combining OpenImageDenoise / Optix denoising with Contrast Adaptive Sharpening (CAS) and glare control. |
| **Auto-Camera & Batch Queue** | `core_auto_camera.py`, `core_batch_queue.py` | Bounding-box raycast camera framing and multi-camera/multi-scene batch render queue manager. |

---

## Technical Stack
* **Language:** Python 3.11+
* **APIs:** Blender Python API (`bpy`, `mathutils`, Cycles/EEVEE Render Engine APIs, Compositor Node API)
* **Blender Compatibility:** Blender `4.2.0+` and `5.x`
* **License:** GPL-3.0-or-later

---

## Installation
1. Clone this repository or package the `hyperrender_studio` directory as a `.zip` archive.
2. In Blender, navigate to **Edit → Preferences → Add-ons → Install from Disk...**
3. Select the archive and enable **HyperRender Studio Enterprise**.

---

## Author
**Khalifa Feruzi Kahamba** (`@Luckyferuzi`)
BSc. Software Engineering
[GitHub Portfolio](https://github.com/Luckyferuzi)
