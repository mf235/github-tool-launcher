from __future__ import annotations

import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

APP_NAME = "github-tool-launcher"
APP_VERSION = "v1.9.3"
SCRIPT_NAME = "github-tool-launcher.py"
ICON_PATH = Path("resources/icons/app.ico")
WINDOW_ICON_PATH = Path("resources/icons/window.png")
ICON_SIZES = [(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]
RELEASE_STAGING_DIR = Path("_release") / APP_NAME


def ensure_multi_size_icon() -> None:
    """Re-save app.ico so it contains the standard Windows icon sizes."""
    try:
        from PIL import Image
    except ImportError as exc:
        raise SystemExit("Pillow が必要です。先に `pip install pillow` を実行してください。") from exc

    if ICON_PATH.exists():
        source = ICON_PATH
    elif WINDOW_ICON_PATH.exists():
        source = WINDOW_ICON_PATH
    else:
        raise SystemExit("resources/icons/app.ico または resources/icons/window.png が見つかりません。")

    ICON_PATH.parent.mkdir(parents=True, exist_ok=True)
    img = Image.open(source).convert("RGBA")
    img.save(ICON_PATH, format="ICO", sizes=ICON_SIZES)
    print(f"icon ok: {ICON_PATH}")


def build_exe() -> Path:
    if not Path(SCRIPT_NAME).exists():
        raise SystemExit(f"{SCRIPT_NAME} が見つかりません。")

    ensure_multi_size_icon()

    add_data_sep = ";" if os.name == "nt" else ":"
    cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--onefile",
        "--windowed",
        "--name",
        APP_NAME,
        "--icon",
        str(ICON_PATH),
        "--add-data",
        f"resources{add_data_sep}resources",
        SCRIPT_NAME,
    ]
    print("run:", " ".join(cmd))
    subprocess.run(cmd, check=True)
    exe_name = f"{APP_NAME}.exe" if os.name == "nt" else APP_NAME
    exe_path = Path("dist") / exe_name
    if not exe_path.exists():
        raise SystemExit(f"exe が見つかりません: {exe_path}")
    return exe_path


def prepare_release_staging(exe_path: Path) -> Path:
    if RELEASE_STAGING_DIR.exists():
        shutil.rmtree(RELEASE_STAGING_DIR, ignore_errors=True)
    RELEASE_STAGING_DIR.mkdir(parents=True, exist_ok=True)
    shutil.copy2(exe_path, RELEASE_STAGING_DIR / exe_path.name)
    for name in ["readme.txt"]:
        src = Path(name)
        if src.exists():
            shutil.copy2(src, RELEASE_STAGING_DIR / name)
    print(f"release staging: {RELEASE_STAGING_DIR}")
    return RELEASE_STAGING_DIR


def make_release_zip(staging_dir: Path) -> Path:
    if not staging_dir.exists():
        raise SystemExit("release staging folder not found, zipを作成できません。")
    zip_path = Path.cwd() / f"{APP_NAME}-{APP_VERSION}.zip"
    if zip_path.exists():
        zip_path.unlink()
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for path in staging_dir.rglob("*"):
            if path.is_file():
                zf.write(path, path.relative_to(staging_dir.parent))
    print(f"release zip: {zip_path}")
    return zip_path


def cleanup_generated_files(zip_path: Path) -> None:
    targets = [Path("build"), Path("dist"), Path(f"{APP_NAME}.spec"), Path("_release")]
    for target in targets:
        if target.resolve() == zip_path.resolve():
            continue
        if target.is_dir():
            shutil.rmtree(target, ignore_errors=True)
            print(f"removed: {target}")
        elif target.exists():
            target.unlink()
            print(f"removed: {target}")
    cache = Path("__pycache__")
    if cache.exists():
        shutil.rmtree(cache, ignore_errors=True)
        print(f"removed: {cache}")
    for pyc in Path.cwd().glob("*.pyc"):
        try:
            pyc.unlink()
            print(f"removed: {pyc}")
        except OSError:
            pass


def main() -> None:
    exe_path = build_exe()
    staging_dir = prepare_release_staging(exe_path)
    zip_path = make_release_zip(staging_dir)
    cleanup_generated_files(zip_path)
    print("done")


if __name__ == "__main__":
    main()
