# SPDX-License-Identifier: GPL-3.0-or-later
# HyperRender Studio v2.0 - Flagship 12x Edition Configuration

EDITION_TIER = "STUDIO_ULTRA"
ALLOW_DEV_TIER_SWITCHER = False
STORE_UPGRADE_URL = "https://tumexstudio.gumroad.com/l/hyperrender"

# Set by build packager:
#   - "SUPERHIVE": 100% DRM-free, zero external API calls, unlocked out of the box (Superhive / Blender Market compliant)
#   - "GUMROAD":   Online Gumroad License Key verification (max 2 PCs per purchase key)
STORE_DISTRIBUTION = "SUPERHIVE"

TIER_METADATA = {
    "STUDIO_ULTRA": {
        "tier_key": "STUDIO_ULTRA",
        "display_name": "HyperRender Studio v2.0 (12x Turbo)",
        "badge": "12x TURBO ENGINE READY",
        "target_speedup_label": "91%+ Faster (12x+ Speed)",
        "sample_ratio": 0.056,
        "min_samples_floor": 16,
        "adaptive_threshold": 0.035,
        "adaptive_min_samples": 6,
        "max_bounces": 3,
        "diffuse_bounces": 1,
        "glossy_bounces": 2,
        "use_persistent_data": True,
        "allow_multipass": True,
        "allow_lod_simplify": True,
        "allow_ultra_engines": True,
    }
}


def get_tier_info():
    return TIER_METADATA["STUDIO_ULTRA"]
