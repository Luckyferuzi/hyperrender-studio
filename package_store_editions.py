import os
import shutil
import zipfile

src_dir = r"c:\Users\Administrator\Desktop\blender project\trying\hyperrender_studio"
ad_kit_dir = r"c:\Users\Administrator\Desktop\blender project\trying\hyperrender_ad_kit"
dist_dir = os.path.join(src_dir, "dist_editions")
os.makedirs(dist_dir, exist_ok=True)

ed_file = os.path.join(src_dir, "edition_config.py")
with open(ed_file, "r", encoding="utf-8") as f:
    orig_ed = f.read()


def build_edition_zip(store_mode: str, zip_name: str):
    mod_ed = (
        orig_ed.replace('STORE_DISTRIBUTION = "GUMROAD"', f'STORE_DISTRIBUTION = "{store_mode}"')
        .replace('STORE_DISTRIBUTION = "SUPERHIVE"', f'STORE_DISTRIBUTION = "{store_mode}"')
    )
    with open(ed_file, "w", encoding="utf-8") as f:
        f.write(mod_ed)
    out_zip = os.path.join(ad_kit_dir, zip_name)
    with zipfile.ZipFile(out_zip, "w", zipfile.ZIP_DEFLATED) as zf:
        for fn in sorted(os.listdir(src_dir)):
            if (fn.endswith(".py") or fn.endswith(".toml")) and fn != "package_store_editions.py":
                zf.write(os.path.join(src_dir, fn), os.path.join("hyperrender_studio", fn))
    shutil.copy2(out_zip, os.path.join(dist_dir, zip_name))
    print(f"Built {zip_name} ({store_mode}): {os.path.getsize(out_zip)} bytes")


if __name__ == "__main__":
    build_edition_zip("GUMROAD", "HyperRender_Studio_v2.0_Gumroad.zip")
    build_edition_zip("SUPERHIVE", "HyperRender_Studio_v2.0_Superhive.zip")
    shutil.copy2(
        os.path.join(ad_kit_dir, "HyperRender_Studio_v2.0_Gumroad.zip"),
        os.path.join(ad_kit_dir, "HyperRender_Studio_v2.0.zip"),
    )
    shutil.copy2(
        os.path.join(ad_kit_dir, "HyperRender_Studio_v2.0_Gumroad.zip"),
        os.path.join(src_dir, "HyperRender_Studio_v2.0.zip"),
    )
