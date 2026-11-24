# SPDX-License-Identifier: GPL-3.0-or-later
# HyperRender Studio v2.0 - Storefront License & Activation Guard

import hashlib
import hmac
import json
import os
import platform
import urllib.parse
import urllib.request
import uuid
import bpy
from .edition_config import STORE_DISTRIBUTION

GUMROAD_PRODUCT_PERMALINK = "hyperrender"
MAX_MACHINES_PER_KEY = 2
STORE_BUY_URL = "https://tumexstudio.gumroad.com/l/hyperrender"

# One-way SHA-256 digest of private studio testing key (never stored in plaintext)
_OWNER_KEY_SHA256 = {
    "a83f10a3b96317dc4f9e2a49bf80cb1588d7c587c11c4043bc1a1041d675b91a",
}


def is_drm_free_build() -> bool:
    """Return True when packaged for Superhive (Blender Market), where external license servers are disallowed."""
    return STORE_DISTRIBUTION == "SUPERHIVE"


def get_machine_hwid() -> str:
    """Compute a deterministic 16-character Hardware Machine ID (HWID) unique to this computer."""
    raw = f"{uuid.getnode()}|{platform.node()}|{platform.machine()}|{platform.processor()}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16].upper()


def _get_license_file_path() -> str:
    cfg_dir = bpy.utils.user_resource('CONFIG')
    os.makedirs(cfg_dir, exist_ok=True)
    return os.path.join(cfg_dir, "tumex_hyperrender_license.json")


def _compute_local_binding_token(license_key: str, hwid: str) -> str:
    payload = f"{license_key.strip().upper()}::{hwid.strip().upper()}::HR_V2_LOCAL".encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _is_owner_testing_key(key_str: str) -> bool:
    digest = hashlib.sha256(key_str.strip().encode("utf-8")).hexdigest()
    return digest in _OWNER_KEY_SHA256


def _verify_gumroad_key_online(key_str: str) -> tuple[bool, str]:
    """
    Verify a Gumroad License Key via Gumroad's official v2 Licenses API.
    Enforces MAX_MACHINES_PER_KEY (2 PCs max per purchase) so one buyer cannot share their key publicly.
    """
    clean_key = key_str.strip()
    if len(clean_key) < 12 or "-" not in clean_key:
        return False, "Invalid license key format."

    url = "https://api.gumroad.com/v2/licenses/verify"
    data = urllib.parse.urlencode({
        "product_permalink": GUMROAD_PRODUCT_PERMALINK,
        "license_key": clean_key,
        "increment_uses_count": "true",
    }).encode("utf-8")

    try:
        req = urllib.request.Request(url, data=data, method="POST")
        with urllib.request.urlopen(req, timeout=6.0) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
            if payload.get("success"):
                purchase = payload.get("purchase", {})
                if purchase.get("refunded") or purchase.get("chargebacked"):
                    return False, "This license key has been refunded or cancelled."
                uses = int(payload.get("uses", 1))
                if uses > MAX_MACHINES_PER_KEY:
                    return (
                        False,
                        f"Key limit reached ({uses}/{MAX_MACHINES_PER_KEY} PCs used).",
                    )
                return True, f"Verified via Gumroad ({uses}/{MAX_MACHINES_PER_KEY} PC activations used)."
            return False, payload.get("message", "License key not recognized.")
    except urllib.error.HTTPError as e:
        try:
            err_body = json.loads(e.read().decode("utf-8"))
            return False, err_body.get("message", "Invalid Gumroad license key.")
        except Exception:
            return False, "Invalid license key."
    except Exception:
        return False, "Could not verify key online. Please check your internet connection."


def is_machine_licensed() -> bool:
    """
    - In the Superhive build, returns True immediately (no external server required).
    - In the Gumroad build, checks local HWID-bound activation file created after Gumroad verification.
    """
    if is_drm_free_build():
        return True

    lic_path = _get_license_file_path()
    if not os.path.exists(lic_path):
        return False

    try:
        with open(lic_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        saved_key = data.get("license_key", "")
        saved_hwid = data.get("hwid", "")
        saved_sig = data.get("signature", "")

        current_hwid = get_machine_hwid()
        if saved_hwid != current_hwid or not saved_key or not saved_sig:
            return False

        expected_sig = _compute_local_binding_token(saved_key, current_hwid)
        return hmac.compare_digest(saved_sig, expected_sig)
    except Exception:
        return False


def activate_license_on_this_machine(raw_key: str) -> tuple[bool, str]:
    """
    Validate the user's Gumroad license key online and bind activation to this computer's HWID.
    """
    if is_drm_free_build():
        return True, "Superhive edition is already unlocked."

    clean_key = raw_key.strip()
    if not clean_key:
        return False, "Please enter your Gumroad License Key first."

    if _is_owner_testing_key(clean_key):
        ok, msg = True, "Studio license activated on this PC!"
    else:
        ok, msg = _verify_gumroad_key_online(clean_key)

    if not ok:
        return False, msg

    hwid = get_machine_hwid()
    sig = _compute_local_binding_token(clean_key, hwid)
    lic_path = _get_license_file_path()
    with open(lic_path, "w", encoding="utf-8") as f:
        json.dump(
            {
                "product": "HyperRender Studio v2.0",
                "license_key": clean_key.upper(),
                "hwid": hwid,
                "signature": sig,
            },
            f,
            indent=2,
        )
    return True, msg


def deactivate_license_on_this_machine():
    """Remove the local activation file."""
    lic_path = _get_license_file_path()
    if os.path.exists(lic_path):
        try:
            os.remove(lic_path)
        except Exception:
            pass
