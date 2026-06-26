# GitHub Tool Launcher
# APP_VERSION: v1.8.0

from __future__ import annotations

import datetime as _dt
import ctypes
import json
import locale
import os
import re
import shlex
import shutil
import subprocess
import sys
import threading
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path
from typing import Any

import tkinter as tk
import tkinter.font as tkfont
from tkinter import colorchooser, filedialog, messagebox, ttk

APP_NAME = "GitHub Tool Launcher"
APP_VERSION = "v1.8.0"

RUN_METHODS = [
    ("auto", "自動"),
    ("python", "python"),
    ("pythonw", "pythonw"),
    ("bat", "bat/cmd"),
    ("exe", "exe"),
    ("command", "任意コマンド"),
]
RUN_METHOD_LABELS = {key: label for key, label in RUN_METHODS}
RUN_METHOD_KEYS = {label: key for key, label in RUN_METHODS}

DEFAULT_LABEL_SETTINGS: dict[str, dict[str, str]] = {
    "1": {"foreground": "#ffffff", "background": "#d32f2f"},
    "2": {"foreground": "#ffffff", "background": "#f57c00"},
    "3": {"foreground": "#222222", "background": "#fbc02d"},
    "4": {"foreground": "#ffffff", "background": "#388e3c"},
    "5": {"foreground": "#ffffff", "background": "#1976d2"},
    "6": {"foreground": "#ffffff", "background": "#7b1fa2"},
    "7": {"foreground": "#ffffff", "background": "#5d4037"},
    "8": {"foreground": "#222222", "background": "#cfd8dc"},
    "9": {"foreground": "#ffffff", "background": "#455a64"},
}

DEFAULT_CONFIG: dict[str, Any] = {
    "github_user_id": "",
    "development_root": r"C:\Documents\GitHub",
    "window_geometry": "",
    "font_size": 10,
    "labels": DEFAULT_LABEL_SETTINGS,
}

DEFAULT_TOOLS: list[dict[str, Any]] = []

WINDOW_DEFAULT_SIZE = (1180, 680)
WINDOW_MIN_SIZE = (900, 520)

JSON_LOAD_WARNINGS: list[str] = []
INVALID_REPOSITORY_CHARS = set('<>:"/\\|?*')
INVALID_PATH_CHARS = set('<>:"|?*')


TOOL_FIELD_DEFAULTS: dict[str, str] = {
    "title": "",
    "repository": "",
    "script": "",
    "category": "",
    "tags": "",
    "run_method": "auto",
    "custom_command": "",
    "last_run_at": "",
    "last_update_at": "",
    "last_update_status": "",
    "label": "",
}


def get_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def get_resource_path(*parts: str) -> Path:
    """Return an external resource path, or the PyInstaller onefile extraction path."""
    base_candidates: list[Path] = [get_base_dir()]
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        base_candidates.append(Path(meipass))
    for base in base_candidates:
        path = base.joinpath(*parts)
        if path.exists():
            return path
    return base_candidates[0].joinpath(*parts)


BASE_DIR = get_base_dir()
CONFIG_PATH = BASE_DIR / "github-tool-launcher_config.json"
TOOLS_PATH = BASE_DIR / "github-tool-launcher_tools.json"
OLD_REPOSITORY_DIR = BASE_DIR / "_repository"
REPOSITORY_DIR = BASE_DIR / "_repository_実行環境"
RUNTIME_MARKER_NAME = "__ここは実行環境です.txt"
ICON_ICO_PATH = get_resource_path("resources", "icons", "app.ico")
WINDOW_ICON_PATH = get_resource_path("resources", "icons", "window.png")


def now_text() -> str:
    return _dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def default_copy(default: Any) -> Any:
    return json.loads(json.dumps(default, ensure_ascii=False))


def timestamp_suffix() -> str:
    return _dt.datetime.now().strftime("%Y%m%d_%H%M%S")


def backup_existing_json(path: Path, reason: str = "broken") -> Path | None:
    if not path.exists():
        return None
    for i in range(100):
        suffix = f".{reason}.{timestamp_suffix()}" + (f"_{i:02d}" if i else "")
        backup = path.with_name(path.name + suffix)
        if backup.exists():
            continue
        try:
            shutil.move(str(path), str(backup))
            JSON_LOAD_WARNINGS.append(f"{path.name} を {backup.name} に退避しました。")
            return backup
        except Exception:
            try:
                shutil.copy2(path, backup)
                JSON_LOAD_WARNINGS.append(f"{path.name} を {backup.name} にコピー退避しました。")
                return backup
            except Exception:
                return None
    return None


def load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        save_json(path, default)
        return default_copy(default)
    try:
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        return data
    except Exception as exc:
        backup_existing_json(path, "broken")
        JSON_LOAD_WARNINGS.append(f"{path.name} を読み込めませんでした: {exc}")
        return default_copy(default)


def save_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8", newline="\n") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")
    tmp.replace(path)


def has_control_char(text: str) -> bool:
    return any(ord(ch) < 32 for ch in text)


def validate_repository_name_value(value: str) -> str | None:
    name = str(value or "").strip()
    if not name:
        return "リポジトリ名が空です。"
    if name in {".", ".."}:
        return "リポジトリ名に . または .. は使えません。"
    if has_control_char(name):
        return "リポジトリ名に制御文字は使えません。"
    if any(ch in INVALID_REPOSITORY_CHARS for ch in name):
        return "リポジトリ名に / \\ : * ? \" < > | は使えません。"
    if name.endswith(".") or name.endswith(" "):
        return "リポジトリ名の末尾にピリオドや空白は使えません。"
    if re.match(r"^[A-Za-z]:", name):
        return "リポジトリ名にドライブ指定は使えません。"
    if not re.fullmatch(r"[A-Za-z0-9._-]+", name):
        return "リポジトリ名は英数字・ハイフン・アンダースコア・ピリオドのみ使えます。"
    return None


def normalize_script_path_text(value: str) -> str:
    text = str(value or "").strip().replace("\\", "/")
    parts = [part for part in text.split("/") if part not in {"", "."}]
    return "/".join(parts)


def validate_script_path_value(value: str) -> str | None:
    raw = str(value or "").strip()
    if not raw:
        return "実行スクリプトが空です。"
    if has_control_char(raw):
        return "実行スクリプトに制御文字は使えません。"
    if raw.startswith(("/", "\\")) or re.match(r"^[A-Za-z]:", raw):
        return "実行スクリプトには絶対パスを使えません。"
    if any(ch in INVALID_PATH_CHARS for ch in raw):
        return "実行スクリプトに : * ? \" < > | は使えません。"
    normalized = normalize_script_path_text(raw)
    if not normalized:
        return "実行スクリプトが空です。"
    parts = normalized.split("/")
    if any(part == ".." for part in parts):
        return "実行スクリプトに .. は使えません。"
    if any(part.endswith(".") or part.endswith(" ") for part in parts):
        return "実行スクリプトの各フォルダ/ファイル名の末尾にピリオドや空白は使えません。"
    return None


def quote_command_arg(value: str) -> str:
    text = str(value)
    if is_windows():
        return subprocess.list2cmdline([text])
    return shlex.quote(text)


def safe_path_within(base: Path, relative_text: str) -> Path:
    normalized = normalize_script_path_text(relative_text)
    candidate = (base / Path(*normalized.split("/"))).resolve(strict=False)
    root = base.resolve(strict=False)
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise ValueError("パスが許可されたフォルダの外を指しています。") from exc
    return candidate


def detect_entry_script(repo_dir: Path, repo_name: str) -> str:
    try:
        files = [p for p in repo_dir.iterdir() if p.is_file()]
    except OSError:
        return ""
    by_lower = {p.name.lower(): p for p in files}
    preferred_names = [
        f"{repo_name}.py",
        f"{repo_name}.pyw",
        "main.py",
        "app.py",
        "run.py",
        "launcher.py",
        "start.bat",
        "run.bat",
    ]
    for name in preferred_names:
        found = by_lower.get(name.lower())
        if found is not None:
            return found.name

    def eligible_python(path: Path) -> bool:
        lower = path.name.lower()
        if path.suffix.lower() not in {".py", ".pyw"}:
            return False
        if lower.startswith("build-") or lower.startswith("setup") or lower.startswith("test_"):
            return False
        return True

    gui_candidates = sorted(
        [p for p in files if eligible_python(p) and (p.stem.lower().endswith(("-gui", "_gui")) or "gui" in p.stem.lower())],
        key=lambda p: p.name.lower(),
    )
    if gui_candidates:
        return gui_candidates[0].name
    py_candidates = sorted([p for p in files if eligible_python(p)], key=lambda p: p.name.lower())
    if py_candidates:
        return py_candidates[0].name
    for ext in (".bat", ".cmd", ".exe"):
        candidates = sorted([p for p in files if p.suffix.lower() == ext], key=lambda p: p.name.lower())
        if candidates:
            return candidates[0].name
    return ""


def normalize_hex_color(value: Any, default: str) -> str:
    text = str(value or "").strip()
    if re.fullmatch(r"#[0-9a-fA-F]{6}", text):
        return text.lower()
    return default.lower()


def normalize_label_id(value: Any) -> str:
    text = str(value or "").strip()
    return text if text in DEFAULT_LABEL_SETTINGS else ""


def normalize_label_settings(raw: Any) -> dict[str, dict[str, str]]:
    result: dict[str, dict[str, str]] = {}
    source = raw if isinstance(raw, dict) else {}
    for label_id, defaults in DEFAULT_LABEL_SETTINGS.items():
        row = source.get(label_id, {}) if isinstance(source, dict) else {}
        if not isinstance(row, dict):
            row = {}
        result[label_id] = {
            "foreground": normalize_hex_color(row.get("foreground"), defaults["foreground"]),
            "background": normalize_hex_color(row.get("background"), defaults["background"]),
        }
    return result


def normalize_config(raw: Any) -> dict[str, Any]:
    config = json.loads(json.dumps(DEFAULT_CONFIG, ensure_ascii=False))
    if isinstance(raw, dict):
        config.update(raw)
    config["labels"] = normalize_label_settings(config.get("labels"))
    return config


def normalize_tool(raw: Any) -> dict[str, str] | None:
    if not isinstance(raw, dict):
        return None
    tool = dict(TOOL_FIELD_DEFAULTS)
    for key in TOOL_FIELD_DEFAULTS:
        tool[key] = str(raw.get(key, TOOL_FIELD_DEFAULTS[key])).strip()
    if tool["run_method"] not in RUN_METHOD_LABELS:
        tool["run_method"] = "auto"
    tool["label"] = normalize_label_id(tool.get("label", ""))
    if not tool["title"] and not tool["repository"] and not tool["script"]:
        return None
    return tool


def is_windows() -> bool:
    return os.name == "nt"


def open_in_file_manager(path: Path) -> None:
    if is_windows():
        os.startfile(str(path))  # type: ignore[attr-defined]
    elif sys.platform == "darwin":
        subprocess.Popen(["open", str(path)])
    else:
        subprocess.Popen(["xdg-open", str(path)])


def open_in_file_manager_select(path: Path) -> None:
    if is_windows():
        try:
            # ShellExecuteW handles Japanese paths more reliably than explorer via Popen.
            result = ctypes.windll.shell32.ShellExecuteW(
                None,
                "open",
                "explorer.exe",
                f'/select,"{str(path)}"',
                None,
                1,
            )
            if result > 32:
                return
        except Exception:
            pass
        try:
            os.startfile(str(path.parent if path.parent.exists() else path))  # type: ignore[attr-defined]
        except Exception:
            pass
    elif sys.platform == "darwin":
        subprocess.Popen(["open", "-R", str(path)])
    else:
        open_in_file_manager(path.parent if path.parent.exists() else path)


def shell_execute_open_windows(path: Path, parameters: str | None = None, directory: Path | None = None, show: int = 1) -> bool:
    if not is_windows():
        return False
    try:
        result = ctypes.windll.shell32.ShellExecuteW(
            None,
            "open",
            str(path),
            parameters,
            str(directory) if directory is not None else None,
            show,
        )
        return result > 32
    except Exception:
        return False


def windows_minimized_console_kwargs() -> dict[str, Any]:
    if not is_windows():
        return {}
    kwargs: dict[str, Any] = {}
    creationflags = getattr(subprocess, "CREATE_NEW_CONSOLE", 0)
    if creationflags:
        kwargs["creationflags"] = creationflags
    try:
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startupinfo.wShowWindow = 6  # SW_MINIMIZE
        kwargs["startupinfo"] = startupinfo
    except Exception:
        pass
    return kwargs


def windows_hidden_launcher_kwargs() -> dict[str, Any]:
    """Hide only the short-lived launcher process.

    Do not pass STARTF_USESHOWWINDOW/SW_HIDE here.  Those values can leak into
    a Python GUI process and hide the actual tool window.
    """
    if not is_windows():
        return {}
    kwargs: dict[str, Any] = {}
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    if creationflags:
        kwargs["creationflags"] = creationflags
    return kwargs


def windows_executable(name: str) -> str:
    found = shutil.which(name)
    return found or name


def launch_windows_minimized_console(command_args: list[str], cwd: Path) -> None:
    """Run command in a minimized cmd window without minimizing the child GUI.

    Directly passing SW_MINIMIZE to python.exe can make Tk/PySide windows start
    minimized.  This launches a minimized cmd wrapper instead, then runs the
    target command normally inside it.
    """
    inner = subprocess.list2cmdline([str(arg) for arg in command_args])
    start_command = f'start "" /min cmd.exe /c {inner}'
    subprocess.Popen(
        ["cmd.exe", "/c", start_command],
        cwd=str(cwd),
        **windows_hidden_launcher_kwargs(),
    )


def migrate_old_repository_dir() -> None:
    if OLD_REPOSITORY_DIR.exists() and not REPOSITORY_DIR.exists():
        try:
            OLD_REPOSITORY_DIR.rename(REPOSITORY_DIR)
        except OSError:
            REPOSITORY_DIR.mkdir(parents=True, exist_ok=True)
            try:
                items = list(OLD_REPOSITORY_DIR.iterdir())
            except OSError:
                items = []
            for item in items:
                dest = REPOSITORY_DIR / item.name
                if dest.exists():
                    continue
                try:
                    shutil.move(str(item), str(dest))
                except OSError:
                    pass


def windows_no_console_kwargs() -> dict[str, Any]:
    if not is_windows():
        return {}
    kwargs: dict[str, Any] = {}
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    if creationflags:
        kwargs["creationflags"] = creationflags
    try:
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startupinfo.wShowWindow = 0
        kwargs["startupinfo"] = startupinfo
    except Exception:
        pass
    return kwargs


def is_geometry_on_screen(root: tk.Tk, geometry: str) -> bool:
    m = re.match(r"^(\d+)x(\d+)([+-]\d+)([+-]\d+)$", geometry)
    if not m:
        return False
    width = int(m.group(1))
    height = int(m.group(2))
    x = int(m.group(3))
    y = int(m.group(4))
    screen_w = root.winfo_screenwidth()
    screen_h = root.winfo_screenheight()
    if width < 300 or height < 240:
        return False
    if x > screen_w - 80 or y > screen_h - 80:
        return False
    if x + width < 80 or y + height < 80:
        return False
    return True


def center_window(root: tk.Tk, width: int, height: int) -> None:
    root.update_idletasks()
    x = max(0, (root.winfo_screenwidth() - width) // 2)
    y = max(0, (root.winfo_screenheight() - height) // 2)
    root.geometry(f"{width}x{height}+{x}+{y}")


def place_toplevel_on_parent(window: tk.Toplevel, parent: tk.Misc, width: int | None = None, height: int | None = None) -> None:
    """Place a toplevel centered on the current main window before it is shown."""
    try:
        parent.update_idletasks()
        window.update_idletasks()
        parent_x = parent.winfo_rootx()
        parent_y = parent.winfo_rooty()
        parent_w = max(1, parent.winfo_width())
        parent_h = max(1, parent.winfo_height())
        win_w = width or max(1, window.winfo_reqwidth(), window.winfo_width())
        win_h = height or max(1, window.winfo_reqheight(), window.winfo_height())
        screen_w = parent.winfo_screenwidth()
        screen_h = parent.winfo_screenheight()
        x = parent_x + max(0, (parent_w - win_w) // 2)
        y = parent_y + max(0, (parent_h - win_h) // 2)
        x = min(max(0, x), max(0, screen_w - win_w))
        y = min(max(0, y), max(0, screen_h - win_h))
        window.geometry(f"{win_w}x{win_h}+{x}+{y}")
    except Exception:
        pass


def show_toplevel_on_parent(
    window: tk.Toplevel,
    parent: tk.Misc,
    width: int | None = None,
    height: int | None = None,
    *,
    modal: bool = False,
) -> None:
    """Show a withdrawn dialog after its final parent-centered position has been decided."""
    place_toplevel_on_parent(window, parent, width, height)
    try:
        window.deiconify()
        window.lift(parent)
        window.focus_force()
        if modal:
            window.grab_set()
    except Exception:
        pass


def close_event_break(callback):
    def handler(_event: tk.Event | None = None) -> str:
        callback()
        return "break"
    return handler


def shorten_datetime(value: str) -> str:
    if not value:
        return ""
    return value.replace("-", "/")[5:16]


def read_text_with_fallback(path: Path) -> str:
    for encoding in ("utf-8-sig", "utf-8", "cp932"):
        try:
            return path.read_text(encoding=encoding)
        except UnicodeDecodeError:
            continue
    return path.read_text(encoding="utf-8", errors="replace")


def find_readme_md_path(repo_dir: Path) -> Path | None:
    for name in ("README.md", "readme.md"):
        path = repo_dir / name
        if path.exists() and path.is_file():
            return path
    try:
        for path in repo_dir.iterdir():
            if path.is_file() and path.name.lower() == "readme.md":
                return path
    except OSError:
        pass
    return None


def extract_first_markdown_heading(readme_path: Path) -> str:
    try:
        text = read_text_with_fallback(readme_path)
    except OSError:
        return ""
    for line in text.splitlines():
        stripped = line.strip()
        match = re.match(r"^#{1,6}\s*(.+?)\s*#*\s*$", stripped)
        if not match:
            continue
        heading = match.group(1).strip()
        if heading:
            return heading
    return ""


def title_from_readme_md(repo_dir: Path) -> str:
    readme = find_readme_md_path(repo_dir)
    if readme is None:
        return ""
    return extract_first_markdown_heading(readme)


def runtime_marker_text(tool: dict[str, str], repo_dir: Path, development_dir: Path) -> str:
    return (
        "ここは GitHub Tool Launcher の実行環境です。\n"
        "開発・編集用フォルダではありません。\n\n"
        f"タイトル: {tool.get('title', '')}\n"
        f"リポジトリ: {tool.get('repository', '')}\n"
        f"実行環境: {repo_dir}\n"
        f"開発環境: {development_dir}\n\n"
        "編集する場合は、開発環境側のフォルダを開いてください。\n"
    )


class CommandLogDialog(tk.Toplevel):
    def __init__(self, master: tk.Misc, title: str) -> None:
        super().__init__(master)
        self.withdraw()
        self.title(title)
        self.geometry("820x460")
        self.minsize(660, 340)
        self.transient(master)
        self.protocol("WM_DELETE_WINDOW", self._on_close_request)
        self.bind("<Escape>", close_event_break(self._on_close_request))
        self._running = True
        self._closed = False

        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)

        frame = ttk.Frame(self, padding=10)
        frame.grid(row=0, column=0, sticky="nsew")
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(0, weight=1)

        self.text = tk.Text(frame, wrap="word", height=18)
        self.text.grid(row=0, column=0, sticky="nsew")
        yscroll = ttk.Scrollbar(frame, orient="vertical", command=self.text.yview)
        yscroll.grid(row=0, column=1, sticky="ns")
        self.text.configure(yscrollcommand=yscroll.set)

        self.close_button = ttk.Button(frame, text="閉じる", command=self.destroy, state="disabled")
        self.close_button.grid(row=1, column=0, columnspan=2, sticky="e", pady=(8, 0))

        show_toplevel_on_parent(self, master, 820, 460)

    def append(self, message: str) -> None:
        if self._closed or not self.winfo_exists():
            return
        self.text.insert("end", message)
        self.text.see("end")

    def finish(self) -> None:
        if self._closed or not self.winfo_exists():
            return
        self._running = False
        self.close_button.configure(state="normal")

    def _on_close_request(self) -> None:
        self.destroy()

    def destroy(self) -> None:
        self._closed = True
        super().destroy()


class SettingsDialog(tk.Toplevel):
    def __init__(self, app: "GitHubToolLauncher") -> None:
        super().__init__(app.root)
        self.withdraw()
        self.app = app
        self.title("環境設定")
        self.resizable(False, False)
        self.transient(app.root)

        self.github_var = tk.StringVar(value=app.config.get("github_user_id", ""))
        self.dev_root_var = tk.StringVar(value=app.config.get("development_root", r"C:\Documents\GitHub"))

        frame = ttk.Frame(self, padding=14)
        frame.grid(row=0, column=0, sticky="nsew")
        frame.columnconfigure(1, weight=1)

        ttk.Label(frame, text="GitHubユーザID").grid(row=0, column=0, sticky="w", padx=(0, 8), pady=6)
        ttk.Entry(frame, textvariable=self.github_var, width=48).grid(row=0, column=1, columnspan=2, sticky="ew", pady=6)

        ttk.Label(frame, text="開発環境パス").grid(row=1, column=0, sticky="w", padx=(0, 8), pady=6)
        ttk.Entry(frame, textvariable=self.dev_root_var, width=48).grid(row=1, column=1, sticky="ew", pady=6)
        ttk.Button(frame, text="参照", command=self.browse_dev_root).grid(row=1, column=2, sticky="e", padx=(8, 0), pady=6)

        buttons = ttk.Frame(frame)
        buttons.grid(row=2, column=0, columnspan=3, sticky="e", pady=(12, 0))
        ttk.Button(buttons, text="保存", command=self.save).pack(side="left", padx=(0, 8))
        ttk.Button(buttons, text="キャンセル", command=self.destroy).pack(side="left")

        self.bind("<Return>", close_event_break(self.save))
        self.bind("<Escape>", close_event_break(self.destroy))
        show_toplevel_on_parent(self, app.root, modal=True)

    def browse_dev_root(self) -> None:
        initial = self.dev_root_var.get().strip() or str(BASE_DIR)
        initialdir = initial if Path(initial).exists() else str(BASE_DIR)
        path = filedialog.askdirectory(title="開発環境パスを選択", initialdir=initialdir, parent=self)
        if path:
            self.dev_root_var.set(path)

    def save(self) -> None:
        self.app.config["github_user_id"] = self.github_var.get().strip()
        self.app.config["development_root"] = self.dev_root_var.get().strip() or r"C:\Documents\GitHub"
        self.app.save_config()
        self.app.set_status("環境設定を保存しました。")
        self.destroy()


class LabelManagerDialog(tk.Toplevel):
    def __init__(self, app: "GitHubToolLauncher") -> None:
        super().__init__(app.root)
        self.withdraw()
        self.app = app
        self.title("ラベル管理")
        self.resizable(False, False)
        self.transient(app.root)
        self.protocol("WM_DELETE_WINDOW", self.close)
        self.vars: dict[str, tuple[tk.StringVar, tk.StringVar]] = {}
        self.preview_labels: dict[str, tk.Label] = {}
        self._loading = True
        self.snapshot: dict[str, dict[str, str]] = {}
        self.dirty_var = tk.StringVar()

        frame = ttk.Frame(self, padding=12)
        frame.grid(row=0, column=0, sticky="nsew")
        ttk.Label(frame, text="ラベル 1〜9 の文字色と背景色を設定します。", font=("", self.app.normalized_font_size() + 1)).grid(
            row=0, column=0, columnspan=6, sticky="w", pady=(0, 8)
        )
        ttk.Label(frame, text="ラベル").grid(row=1, column=0, sticky="w", pady=(0, 4))
        ttk.Label(frame, text="文字色").grid(row=1, column=1, sticky="w", pady=(0, 4))
        ttk.Label(frame, text="背景色").grid(row=1, column=3, sticky="w", pady=(0, 4))
        ttk.Label(frame, text="プレビュー").grid(row=1, column=5, sticky="w", pady=(0, 4))

        settings = normalize_label_settings(self.app.config.get("labels"))
        for row, label_id in enumerate(DEFAULT_LABEL_SETTINGS, start=2):
            fg_var = tk.StringVar(value=settings[label_id]["foreground"])
            bg_var = tk.StringVar(value=settings[label_id]["background"])
            self.vars[label_id] = (fg_var, bg_var)
            ttk.Label(frame, text=label_id, width=3).grid(row=row, column=0, sticky="w", pady=4)
            ttk.Entry(frame, textvariable=fg_var, width=12).grid(row=row, column=1, sticky="w", padx=(0, 8), pady=4)
            ttk.Button(frame, text="選択", command=lambda v=fg_var: self.choose_color(v)).grid(row=row, column=2, sticky="w", padx=(0, 12), pady=4)
            ttk.Entry(frame, textvariable=bg_var, width=12).grid(row=row, column=3, sticky="w", padx=(0, 8), pady=4)
            ttk.Button(frame, text="選択", command=lambda v=bg_var: self.choose_color(v)).grid(row=row, column=4, sticky="w", padx=(0, 12), pady=4)
            preview = tk.Label(frame, text=f"ラベル {label_id}", width=10, padx=10, pady=6)
            preview.grid(row=row, column=5, sticky="ew", pady=4)
            self.preview_labels[label_id] = preview
            fg_var.trace_add("write", lambda *_args, lid=label_id: self.on_color_changed(lid))
            bg_var.trace_add("write", lambda *_args, lid=label_id: self.on_color_changed(lid))
            self.update_preview(label_id)

        buttons = ttk.Frame(frame)
        buttons.grid(row=11, column=0, columnspan=6, sticky="ew", pady=(10, 0))
        ttk.Button(buttons, text="初期値に戻す", command=self.reset_defaults).pack(side="left")
        ttk.Label(buttons, textvariable=self.dirty_var, foreground="#b06000").pack(side="left", padx=(12, 0))
        ttk.Button(buttons, text="保存して閉じる", command=self.save).pack(side="right", padx=(8, 0))
        ttk.Button(buttons, text="閉じる", command=self.close).pack(side="right")

        self.snapshot = self.current_settings_for_compare()
        self._loading = False
        self.update_dirty_status()
        self.bind("<Escape>", close_event_break(self.close))
        show_toplevel_on_parent(self, app.root, modal=True)

    def on_color_changed(self, label_id: str) -> None:
        self.update_preview(label_id)
        if not self._loading:
            self.update_dirty_status()

    def current_settings_for_compare(self) -> dict[str, dict[str, str]]:
        result: dict[str, dict[str, str]] = {}
        for label_id, defaults in DEFAULT_LABEL_SETTINGS.items():
            fg_var, bg_var = self.vars[label_id]
            result[label_id] = {
                "foreground": normalize_hex_color(fg_var.get(), defaults["foreground"]),
                "background": normalize_hex_color(bg_var.get(), defaults["background"]),
            }
        return result

    def is_dirty(self) -> bool:
        return self.current_settings_for_compare() != self.snapshot

    def update_dirty_status(self) -> None:
        self.dirty_var.set("未保存の変更あり" if self.is_dirty() else "")

    def choose_color(self, var: tk.StringVar) -> None:
        current = var.get().strip() or "#ffffff"
        _rgb, color = colorchooser.askcolor(color=current, parent=self, title="色を選択")
        if color:
            var.set(color.lower())

    def update_preview(self, label_id: str) -> None:
        fg_var, bg_var = self.vars[label_id]
        defaults = DEFAULT_LABEL_SETTINGS[label_id]
        foreground = normalize_hex_color(fg_var.get(), defaults["foreground"])
        background = normalize_hex_color(bg_var.get(), defaults["background"])
        self.preview_labels[label_id].configure(foreground=foreground, background=background)

    def reset_defaults(self) -> None:
        for label_id, defaults in DEFAULT_LABEL_SETTINGS.items():
            fg_var, bg_var = self.vars[label_id]
            fg_var.set(defaults["foreground"])
            bg_var.set(defaults["background"])
        self.update_dirty_status()

    def collect_settings(self) -> dict[str, dict[str, str]] | None:
        result: dict[str, dict[str, str]] = {}
        for label_id, defaults in DEFAULT_LABEL_SETTINGS.items():
            fg_var, bg_var = self.vars[label_id]
            foreground = fg_var.get().strip()
            background = bg_var.get().strip()
            if not re.fullmatch(r"#[0-9a-fA-F]{6}", foreground):
                messagebox.showwarning("入力エラー", f"ラベル {label_id} の文字色が #RRGGBB 形式ではありません。", parent=self)
                return None
            if not re.fullmatch(r"#[0-9a-fA-F]{6}", background):
                messagebox.showwarning("入力エラー", f"ラベル {label_id} の背景色が #RRGGBB 形式ではありません。", parent=self)
                return None
            result[label_id] = {"foreground": foreground.lower(), "background": background.lower()}
        return result

    def save(self) -> bool:
        settings = self.collect_settings()
        if settings is None:
            return False
        self.app.config["labels"] = settings
        self.app.save_config()
        self.app.configure_label_tags()
        self.app.refresh_tree()
        self.snapshot = self.current_settings_for_compare()
        self.update_dirty_status()
        self.app.set_status("ラベル設定を保存しました。")
        self.destroy()
        return True

    def close(self) -> None:
        if not self.is_dirty():
            self.destroy()
            return
        answer = messagebox.askyesnocancel(
            "未保存の変更",
            "ラベル設定が保存されていません。\n保存しますか？\n\nはい: 保存して閉じる\nいいえ: 破棄して閉じる\nキャンセル: 閉じない",
            parent=self,
        )
        if answer is None:
            return
        if answer:
            self.save()
            return
        self.destroy()


class ToolManagerDialog(tk.Toplevel):
    def __init__(self, app: "GitHubToolLauncher") -> None:
        super().__init__(app.root)
        self.withdraw()
        self.app = app
        self.title("ツール管理")
        self.geometry("1040x700")
        self.minsize(900, 580)
        self.transient(app.root)

        self.current_index: int | None = None
        self.form_snapshot: dict[str, str] = {}
        self._loading_form = False
        self._suppress_select = False

        self.title_var = tk.StringVar()
        self.repo_var = tk.StringVar()
        self.script_var = tk.StringVar()
        self.category_var = tk.StringVar()
        self.tags_var = tk.StringVar()
        self.run_method_var = tk.StringVar(value=RUN_METHOD_LABELS["auto"])
        self.custom_command_var = tk.StringVar()
        self.dirty_var = tk.StringVar()

        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)

        root_frame = ttk.Frame(self, padding=12)
        root_frame.grid(row=0, column=0, sticky="nsew")
        root_frame.columnconfigure(0, weight=1)
        root_frame.rowconfigure(0, weight=1)

        self.tree = ttk.Treeview(
            root_frame,
            columns=("title", "repository", "category", "script", "run_method"),
            show="headings",
            selectmode="browse",
        )
        self.tree.heading("title", text="タイトル")
        self.tree.heading("repository", text="リポジトリ")
        self.tree.heading("category", text="カテゴリ")
        self.tree.heading("script", text="実行スクリプト")
        self.tree.heading("run_method", text="実行方法")
        self.tree.column("title", width=250, anchor="w")
        self.tree.column("repository", width=220, anchor="w")
        self.tree.column("category", width=120, anchor="w")
        self.tree.column("script", width=260, anchor="w")
        self.tree.column("run_method", width=90, anchor="w")
        self.tree.grid(row=0, column=0, sticky="nsew")
        yscroll = ttk.Scrollbar(root_frame, orient="vertical", command=self.tree.yview)
        yscroll.grid(row=0, column=1, sticky="ns")
        self.tree.configure(yscrollcommand=yscroll.set)
        self.tree.bind("<<TreeviewSelect>>", self.on_select)
        self.tree.bind("<Double-1>", lambda _e: self.fill_from_selection())

        form = ttk.LabelFrame(root_frame, text="登録内容", padding=10)
        form.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(10, 0))
        form.columnconfigure(1, weight=1)
        form.columnconfigure(3, weight=1)

        ttk.Label(form, text="タイトル").grid(row=0, column=0, sticky="w", padx=(0, 8), pady=4)
        ttk.Entry(form, textvariable=self.title_var).grid(row=0, column=1, columnspan=3, sticky="ew", pady=4)

        ttk.Label(form, text="リポジトリ名").grid(row=1, column=0, sticky="w", padx=(0, 8), pady=4)
        ttk.Entry(form, textvariable=self.repo_var).grid(row=1, column=1, sticky="ew", pady=4)
        ttk.Label(form, text="カテゴリ").grid(row=1, column=2, sticky="w", padx=(14, 8), pady=4)
        ttk.Entry(form, textvariable=self.category_var).grid(row=1, column=3, sticky="ew", pady=4)

        ttk.Label(form, text="実行スクリプト").grid(row=2, column=0, sticky="w", padx=(0, 8), pady=4)
        ttk.Entry(form, textvariable=self.script_var).grid(row=2, column=1, sticky="ew", pady=4)
        ttk.Label(form, text="タグ").grid(row=2, column=2, sticky="w", padx=(14, 8), pady=4)
        ttk.Entry(form, textvariable=self.tags_var).grid(row=2, column=3, sticky="ew", pady=4)

        ttk.Label(form, text="実行方法").grid(row=3, column=0, sticky="w", padx=(0, 8), pady=4)
        ttk.Combobox(
            form,
            textvariable=self.run_method_var,
            values=[label for _key, label in RUN_METHODS],
            state="readonly",
            width=18,
        ).grid(row=3, column=1, sticky="w", pady=4)
        ttk.Label(form, text="任意コマンド").grid(row=3, column=2, sticky="w", padx=(14, 8), pady=4)
        ttk.Entry(form, textvariable=self.custom_command_var).grid(row=3, column=3, sticky="ew", pady=4)

        hint = ttk.Label(
            form,
            text="任意コマンドでは {script} {script_q} {script_path} {script_path_q} {repo} {repo_q} {repo_dir} {repo_dir_q} が使えます。",
            foreground="#666666",
        )
        hint.grid(row=4, column=0, columnspan=4, sticky="w", pady=(4, 0))

        buttons = ttk.Frame(root_frame)
        buttons.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(10, 0))
        ttk.Button(buttons, text="追加/更新", command=self.add_or_update).pack(side="left", padx=(0, 6))
        ttk.Button(buttons, text="新規入力", command=self.clear_form).pack(side="left", padx=(0, 6))
        ttk.Button(buttons, text="元に戻す", command=self.revert_form).pack(side="left", padx=(0, 6))
        ttk.Button(buttons, text="削除", command=self.delete_selected).pack(side="left", padx=(0, 18))
        ttk.Button(buttons, text="上へ", command=lambda: self.move_selected(-1)).pack(side="left", padx=(0, 6))
        ttk.Button(buttons, text="下へ", command=lambda: self.move_selected(1)).pack(side="left", padx=(0, 6))
        ttk.Label(buttons, textvariable=self.dirty_var, foreground="#b06000").pack(side="left", padx=(12, 0))
        ttk.Button(buttons, text="閉じる", command=self.close).pack(side="right")

        for var in (
            self.title_var,
            self.repo_var,
            self.script_var,
            self.category_var,
            self.tags_var,
            self.run_method_var,
            self.custom_command_var,
        ):
            var.trace_add("write", lambda *_args: self.on_form_changed())

        self.refresh()
        self.set_blank_form()
        self.bind("<Escape>", close_event_break(self.close))
        show_toplevel_on_parent(self, app.root, 1040, 700, modal=True)

    def blank_form_values(self) -> dict[str, str]:
        return {
            "title": "",
            "repository": "",
            "script": "",
            "category": "",
            "tags": "",
            "run_method": "auto",
            "custom_command": "",
        }

    def current_form_values(self) -> dict[str, str]:
        method_label = self.run_method_var.get().strip()
        return {
            "title": self.title_var.get().strip(),
            "repository": self.repo_var.get().strip(),
            "script": self.script_var.get().strip(),
            "category": self.category_var.get().strip(),
            "tags": self.tags_var.get().strip(),
            "run_method": RUN_METHOD_KEYS.get(method_label, "auto"),
            "custom_command": self.custom_command_var.get().strip(),
        }

    def is_dirty(self) -> bool:
        return self.current_form_values() != self.form_snapshot

    def on_form_changed(self) -> None:
        if self._loading_form:
            return
        self.update_dirty_status()

    def update_dirty_status(self) -> None:
        self.dirty_var.set("未保存の変更あり" if self.is_dirty() else "")

    def set_form_values(self, values: dict[str, str], index: int | None) -> None:
        self._loading_form = True
        try:
            self.title_var.set(values.get("title", ""))
            self.repo_var.set(values.get("repository", ""))
            self.script_var.set(values.get("script", ""))
            self.category_var.set(values.get("category", ""))
            self.tags_var.set(values.get("tags", ""))
            method = values.get("run_method", "auto")
            self.run_method_var.set(RUN_METHOD_LABELS.get(method, RUN_METHOD_LABELS["auto"]))
            self.custom_command_var.set(values.get("custom_command", ""))
        finally:
            self._loading_form = False
        self.current_index = index
        self.form_snapshot = self.current_form_values()
        self.update_dirty_status()

    def set_blank_form(self) -> None:
        self.set_form_values(self.blank_form_values(), None)

    def refresh(self, select_index: int | None = None) -> None:
        self._suppress_select = True
        try:
            self.tree.delete(*self.tree.get_children())
            for i, tool in enumerate(self.app.tools):
                method = RUN_METHOD_LABELS.get(tool.get("run_method", "auto"), "自動")
                self.tree.insert(
                    "",
                    "end",
                    iid=str(i),
                    values=(tool["title"], tool["repository"], tool.get("category", ""), tool["script"], method),
                )
            if select_index is not None and 0 <= select_index < len(self.app.tools):
                self.tree.selection_set(str(select_index))
                self.tree.see(str(select_index))
            else:
                self.tree.selection_remove(self.tree.selection())
        finally:
            self._suppress_select = False

    def get_selected_index(self) -> int | None:
        selection = self.tree.selection()
        if not selection:
            return None
        try:
            return int(selection[0])
        except ValueError:
            return None

    def restore_tree_selection(self) -> None:
        self._suppress_select = True
        try:
            self.tree.selection_remove(self.tree.selection())
            if self.current_index is not None and 0 <= self.current_index < len(self.app.tools):
                self.tree.selection_set(str(self.current_index))
                self.tree.see(str(self.current_index))
        finally:
            self._suppress_select = False

    def on_select(self, _event: tk.Event | None = None) -> None:
        if self._suppress_select:
            return
        new_index = self.get_selected_index()
        if new_index == self.current_index:
            return
        if not self.confirm_unsaved_changes():
            self.restore_tree_selection()
            return
        if new_index is None or not (0 <= new_index < len(self.app.tools)):
            self.set_blank_form()
            return
        self.refresh(new_index)
        self.fill_from_index(new_index)

    def fill_from_selection(self) -> None:
        index = self.get_selected_index()
        if index is None:
            return
        if self.is_dirty() and index != self.current_index:
            if not self.confirm_unsaved_changes():
                self.restore_tree_selection()
                return
        if 0 <= index < len(self.app.tools):
            self.refresh(index)
            self.fill_from_index(index)

    def fill_from_index(self, index: int) -> None:
        if not (0 <= index < len(self.app.tools)):
            return
        self.set_form_values(self.app.tools[index], index)

    def validate_form(self) -> dict[str, str] | None:
        values = self.current_form_values()
        if not values["title"] or not values["repository"] or not values["script"]:
            messagebox.showwarning("入力不足", "タイトル、リポジトリ名、実行スクリプトを入力してください。", parent=self)
            return None
        repo_error = validate_repository_name_value(values["repository"])
        if repo_error:
            messagebox.showwarning("入力エラー", repo_error, parent=self)
            return None
        script_error = validate_script_path_value(values["script"])
        if script_error:
            messagebox.showwarning("入力エラー", script_error, parent=self)
            return None
        values["script"] = normalize_script_path_text(values["script"])
        duplicate_index = self.app.find_repository_index(values["repository"], exclude_index=self.current_index)
        if duplicate_index is not None:
            messagebox.showwarning("入力エラー", "同じリポジトリ名のツールがすでに登録されています。", parent=self)
            return None
        if values["run_method"] == "command" and not values["custom_command"]:
            messagebox.showwarning("入力不足", "任意コマンドを指定してください。", parent=self)
            return None
        return values

    def save_current_form_data(self) -> int | None:
        values = self.validate_form()
        if values is None:
            return None
        index = self.current_index
        old_meta: dict[str, str] = {}
        if index is not None and 0 <= index < len(self.app.tools):
            old_meta = {
                "last_run_at": self.app.tools[index].get("last_run_at", ""),
                "last_update_at": self.app.tools[index].get("last_update_at", ""),
                "last_update_status": self.app.tools[index].get("last_update_status", ""),
                "label": self.app.tools[index].get("label", ""),
            }
        self._loading_form = True
        try:
            self.script_var.set(values["script"])
        finally:
            self._loading_form = False
        tool = dict(TOOL_FIELD_DEFAULTS)
        tool.update(old_meta)
        tool.update(values)
        if index is None:
            self.app.tools.append(tool)
            index = len(self.app.tools) - 1
        else:
            self.app.tools[index] = tool
        self.app.save_tools()
        self.app.refresh_category_filter()
        self.app.refresh_tree()
        self.current_index = index
        self.form_snapshot = self.current_form_values()
        self.update_dirty_status()
        return index

    def confirm_unsaved_changes(self) -> bool:
        if not self.is_dirty():
            return True
        answer = messagebox.askyesnocancel(
            "未保存の変更",
            "変更内容が保存されていません。\n保存しますか？\n\nはい: 保存して続行\nいいえ: 破棄して続行\nキャンセル: 操作を中止",
            parent=self,
        )
        if answer is None:
            return False
        if answer:
            return self.save_current_form_data() is not None
        return True

    def clear_form(self) -> None:
        if not self.confirm_unsaved_changes():
            return
        self._suppress_select = True
        try:
            self.tree.selection_remove(self.tree.selection())
        finally:
            self._suppress_select = False
        self.set_blank_form()

    def revert_form(self) -> None:
        if self.current_index is None:
            self.set_blank_form()
            return
        if 0 <= self.current_index < len(self.app.tools):
            self.fill_from_index(self.current_index)

    def add_or_update(self) -> None:
        index = self.save_current_form_data()
        if index is None:
            return
        self.refresh(index)
        self.fill_from_index(index)
        self.app.set_status("ツール登録を保存しました。")

    def delete_selected(self) -> None:
        if not self.confirm_unsaved_changes():
            return
        index = self.get_selected_index()
        if index is None:
            index = self.current_index
        if index is None or not (0 <= index < len(self.app.tools)):
            return
        tool = self.app.tools[index]
        if not messagebox.askyesno("削除", f"{tool['title']} を削除しますか？\nリポジトリ本体は削除しません。", parent=self):
            return
        del self.app.tools[index]
        self.app.save_tools()
        next_index = min(index, len(self.app.tools) - 1) if self.app.tools else None
        self.refresh(next_index)
        if next_index is not None:
            self.fill_from_index(next_index)
        else:
            self.set_blank_form()
        self.app.refresh_category_filter()
        self.app.refresh_tree()
        self.app.set_status("ツール登録を削除しました。")

    def move_selected(self, delta: int) -> None:
        if not self.confirm_unsaved_changes():
            return
        index = self.get_selected_index()
        if index is None:
            index = self.current_index
        if index is None:
            return
        new_index = index + delta
        if not (0 <= new_index < len(self.app.tools)):
            return
        self.app.tools[index], self.app.tools[new_index] = self.app.tools[new_index], self.app.tools[index]
        self.app.save_tools()
        self.refresh(new_index)
        self.fill_from_index(new_index)
        self.app.refresh_tree()
        self.app.set_status("並び順を保存しました。")

    def close(self) -> None:
        if not self.confirm_unsaved_changes():
            return
        self.destroy()


class RepositoryImportDialog(tk.Toplevel):
    def __init__(self, app: "GitHubToolLauncher", github_user: str) -> None:
        super().__init__(app.root)
        self.withdraw()
        self.app = app
        self.github_user = github_user
        self.rows: list[dict[str, Any]] = []
        self.title("GitHub候補登録")
        self.geometry("980x620")
        self.minsize(820, 500)
        self.transient(app.root)

        self.filter_var = tk.StringVar()
        self.filter_var.trace_add("write", lambda *_args: self.apply_filter())
        self.status_var = tk.StringVar(value="GitHubからリポジトリ一覧を取得しています...")

        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)

        top = ttk.Frame(self, padding=(12, 12, 12, 6))
        top.grid(row=0, column=0, sticky="ew")
        top.columnconfigure(1, weight=1)
        ttk.Label(top, text=f"GitHubユーザID: {github_user}").grid(row=0, column=0, sticky="w", padx=(0, 12))
        ttk.Entry(top, textvariable=self.filter_var).grid(row=0, column=1, sticky="ew")
        ttk.Button(top, text="×", width=3, command=lambda: self.filter_var.set("")).grid(row=0, column=2, padx=(6, 0))

        body = ttk.Frame(self, padding=(12, 0, 12, 6))
        body.grid(row=1, column=0, sticky="nsew")
        body.columnconfigure(0, weight=1)
        body.rowconfigure(1, weight=1)

        header = ttk.Frame(body)
        header.grid(row=0, column=0, sticky="ew")
        header.columnconfigure(1, weight=1)
        ttk.Label(header, text="選択", width=7).grid(row=0, column=0, sticky="w")
        ttk.Label(header, text="リポジトリ", width=34).grid(row=0, column=1, sticky="w")
        ttk.Label(header, text="状態", width=12).grid(row=0, column=2, sticky="w")
        ttk.Label(header, text="説明").grid(row=0, column=3, sticky="w")

        self.canvas = tk.Canvas(body, highlightthickness=0)
        self.canvas.grid(row=1, column=0, sticky="nsew")
        yscroll = ttk.Scrollbar(body, orient="vertical", command=self.canvas.yview)
        yscroll.grid(row=1, column=1, sticky="ns")
        self.canvas.configure(yscrollcommand=yscroll.set)

        self.inner = ttk.Frame(self.canvas)
        self.inner_id = self.canvas.create_window((0, 0), window=self.inner, anchor="nw")
        self.inner.bind("<Configure>", self._update_scroll_region)
        self.canvas.bind("<Configure>", self._resize_inner)
        self._show_message_row("取得中...")

        bottom = ttk.Frame(self, padding=(12, 6, 12, 12))
        bottom.grid(row=2, column=0, sticky="ew")
        bottom.columnconfigure(0, weight=1)
        ttk.Label(bottom, textvariable=self.status_var).grid(row=0, column=0, sticky="w")
        ttk.Button(bottom, text="未登録のみ選択", command=self.select_unregistered).grid(row=0, column=1, padx=(8, 0))
        ttk.Button(bottom, text="全解除", command=self.clear_selection).grid(row=0, column=2, padx=(6, 0))
        ttk.Button(bottom, text="選択したリポジトリを登録", command=self.add_selected).grid(row=0, column=3, padx=(14, 0))
        ttk.Button(bottom, text="閉じる", command=self.destroy).grid(row=0, column=4, padx=(6, 0))

        self.bind("<Escape>", close_event_break(self.destroy))
        show_toplevel_on_parent(self, app.root, 980, 620, modal=True)

    def _update_scroll_region(self, _event: tk.Event | None = None) -> None:
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def _resize_inner(self, event: tk.Event) -> None:
        self.canvas.itemconfigure(self.inner_id, width=event.width)

    def _show_message_row(self, message: str) -> None:
        for child in self.inner.winfo_children():
            child.destroy()
        ttk.Label(self.inner, text=message, padding=12).pack(anchor="w")

    def set_error(self, message: str) -> None:
        self.rows.clear()
        self._show_message_row(message)
        self.status_var.set("取得に失敗しました。")

    def set_repositories(self, repos: list[dict[str, str]]) -> None:
        for child in self.inner.winfo_children():
            child.destroy()
        self.rows.clear()
        existing = {tool.get("repository", "").strip().lower() for tool in self.app.tools}
        for repo in repos:
            name = repo.get("name", "").strip()
            if not name or validate_repository_name_value(name):
                continue
            is_existing = name.lower() in existing
            var = tk.BooleanVar(value=False)
            row = ttk.Frame(self.inner, padding=(0, 3))
            row.columnconfigure(1, weight=0)
            row.columnconfigure(3, weight=1)
            cb = ttk.Checkbutton(row, variable=var)
            cb.grid(row=0, column=0, sticky="w", padx=(0, 8))
            if is_existing:
                cb.state(["disabled"])
            ttk.Label(row, text=name, width=34).grid(row=0, column=1, sticky="w")
            ttk.Label(row, text="登録済み" if is_existing else "未登録", width=12).grid(row=0, column=2, sticky="w")
            desc = repo.get("description", "") or ""
            ttk.Label(row, text=desc, wraplength=420).grid(row=0, column=3, sticky="w")
            row.pack(fill="x", anchor="n")
            self.rows.append({"frame": row, "var": var, "repo": repo, "existing": is_existing})
        if not self.rows:
            self._show_message_row("リポジトリが見つかりませんでした。")
        self.status_var.set(f"取得完了: {len(self.rows)}件。登録したいリポジトリにチェックを入れてください。")
        self.apply_filter()

    def apply_filter(self) -> None:
        query = self.filter_var.get().strip().lower()
        for row in self.rows:
            repo = row["repo"]
            text = f"{repo.get('name', '')} {repo.get('description', '')}".lower()
            frame = row["frame"]
            if query and query not in text:
                frame.pack_forget()
            else:
                frame.pack(fill="x", anchor="n")

    def select_unregistered(self) -> None:
        for row in self.rows:
            if not row["existing"]:
                row["var"].set(True)

    def clear_selection(self) -> None:
        for row in self.rows:
            row["var"].set(False)

    def add_selected(self) -> None:
        selected = [row for row in self.rows if row["var"].get() and not row["existing"]]
        if not selected:
            messagebox.showwarning("未選択", "登録するリポジトリにチェックを入れてください。", parent=self)
            return
        if self.app.process_running:
            messagebox.showinfo("処理中", "すでに取得処理が動いています。", parent=self)
            return
        ready = self.app.validate_update_ready(parent=self)
        if ready is None:
            return
        github_user, git_path = ready
        self.start_register_selected(selected, github_user, git_path)

    def start_register_selected(self, selected: list[dict[str, Any]], github_user: str, git_path: str) -> None:
        dialog = CommandLogDialog(self, "GitHub候補登録")
        dialog.append(f"対象数: {len(selected)}\n")
        dialog.append(f"保存先: {REPOSITORY_DIR}\n")
        dialog.append("登録時にリポジトリを取得し、README.md の最初の # 見出しをタイトルに使います。\n\n")
        self.app.process_running = True
        self.status_var.set(f"登録処理中... {len(selected)}件")
        self.app.set_status(f"GitHub候補登録中... {len(selected)}件")

        def worker() -> None:
            added_tools: list[dict[str, str]] = []
            success_count = 0
            fail_count = 0
            encoding = locale.getpreferredencoding(False) or "utf-8"
            existing = {tool.get("repository", "").strip().lower() for tool in self.app.tools}

            for pos, row in enumerate(selected, 1):
                repo = row["repo"]
                name = repo.get("name", "").strip()
                repo_error = validate_repository_name_value(name)
                if repo_error:
                    fail_count += 1
                    self.app.root.after(0, dialog.append, f"[{pos}/{len(selected)}] {name or '(empty)'}\nERROR: {repo_error}\n登録しません。\n\n")
                    continue
                if name.lower() in existing:
                    continue
                temp_tool = dict(TOOL_FIELD_DEFAULTS)
                temp_tool["repository"] = name
                cmd, action, repo_url, repo_dir = self.app.build_git_command(temp_tool, github_user, git_path)
                self.app.root.after(0, dialog.append, f"[{pos}/{len(selected)}] {name}\n")
                self.app.root.after(0, dialog.append, f"操作: {action}\nリポジトリ: {repo_url}\n保存先: {repo_dir}\n")
                if cmd is None:
                    fail_count += 1
                    self.app.root.after(0, dialog.append, "ERROR: フォルダは存在しますがGitリポジトリではありません。登録しません。\n\n")
                    continue

                code = -1
                try:
                    process = subprocess.Popen(
                        cmd,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.STDOUT,
                        text=True,
                        encoding=encoding,
                        errors="replace",
                        cwd=str(BASE_DIR),
                        **windows_no_console_kwargs(),
                    )
                    assert process.stdout is not None
                    for line in process.stdout:
                        self.app.root.after(0, dialog.append, line)
                    code = process.wait()
                except Exception as exc:
                    self.app.root.after(0, dialog.append, f"ERROR: {exc}\n")

                if code != 0:
                    fail_count += 1
                    self.app.root.after(0, dialog.append, f"失敗しました。終了コード: {code}\n登録しません。\n\n")
                    continue

                title = title_from_readme_md(repo_dir) or name
                if title != name:
                    self.app.root.after(0, dialog.append, f"README.md 見出し: {title}\n")
                else:
                    self.app.root.after(0, dialog.append, "README.md 見出しなし: リポジトリ名をタイトルにします。\n")

                script = detect_entry_script(repo_dir, name) or f"{name}.py"
                if validate_script_path_value(script):
                    script = f"{name}.py"
                if script == f"{name}.py" and not (repo_dir / script).exists():
                    self.app.root.after(0, dialog.append, f"実行スクリプト候補: {script}（自動検出なし）\n")
                else:
                    self.app.root.after(0, dialog.append, f"実行スクリプト候補: {script}\n")
                tool = dict(TOOL_FIELD_DEFAULTS)
                tool.update(
                    {
                        "title": title,
                        "repository": name,
                        "script": normalize_script_path_text(script),
                        "run_method": "auto",
                        "last_update_at": now_text(),
                        "last_update_status": "success",
                    }
                )
                self.app.ensure_runtime_marker(tool)
                added_tools.append(tool)
                existing.add(name.lower())
                success_count += 1
                self.app.root.after(0, dialog.append, "登録候補に追加しました。\n\n")

            def finish() -> None:
                self.app.process_running = False
                if added_tools:
                    self.app.tools.extend(added_tools)
                    self.app.save_tools()
                    self.app.refresh_category_filter()
                    self.app.refresh_tree()
                    self.app.set_status(f"GitHub候補から {len(added_tools)} 件登録しました。")
                    dialog.append(f"完了: 登録 {success_count} / 失敗 {fail_count}\n")
                    self.status_var.set(f"登録完了: {len(added_tools)}件")
                    dialog.finish()
                    messagebox.showinfo(
                        "登録完了",
                        f"{len(added_tools)} 件登録しました。\n実行スクリプト名は必要に応じてツール管理で調整してください。",
                        parent=self,
                    )
                    self.destroy()
                else:
                    self.app.set_status(f"GitHub候補登録完了: 登録 0 / 失敗 {fail_count}")
                    dialog.append(f"完了: 登録 0 / 失敗 {fail_count}\n")
                    self.status_var.set("登録できるリポジトリはありませんでした。")
                    dialog.finish()
                    messagebox.showinfo("登録なし", "新しく登録できるリポジトリはありませんでした。", parent=self)

            self.app.root.after(0, finish)

        threading.Thread(target=worker, daemon=True).start()


class GitHubToolLauncher:
    def __init__(self) -> None:
        migrate_old_repository_dir()
        REPOSITORY_DIR.mkdir(parents=True, exist_ok=True)

        loaded_config = load_json(CONFIG_PATH, DEFAULT_CONFIG)
        if not isinstance(loaded_config, dict):
            backup_existing_json(CONFIG_PATH, "invalid")
            loaded_config = default_copy(DEFAULT_CONFIG)
        self.config = normalize_config(loaded_config)

        loaded_tools = load_json(TOOLS_PATH, DEFAULT_TOOLS)
        if not isinstance(loaded_tools, list):
            backup_existing_json(TOOLS_PATH, "invalid")
            loaded_tools = list(DEFAULT_TOOLS)
        self.tools = [tool for raw in loaded_tools if (tool := normalize_tool(raw)) is not None]

        self.filtered_indices: list[int] = []
        self.process_running = False

        self.root = tk.Tk()
        self.root.withdraw()
        self.root.title(APP_NAME)
        self.root.minsize(*WINDOW_MIN_SIZE)
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

        self._set_icons()
        self._build_style()
        self._build_menu()
        self._build_main_ui()
        self.restore_or_center_geometry()
        self.refresh_category_filter()
        self.refresh_tree()
        self.set_status("準備完了。")
        if JSON_LOAD_WARNINGS:
            self.set_status(" / ".join(JSON_LOAD_WARNINGS[-2:]))
        self.show_main_window()

    def _set_icons(self) -> None:
        try:
            if ICON_ICO_PATH.exists() and is_windows():
                self.root.iconbitmap(str(ICON_ICO_PATH))
        except Exception:
            pass
        try:
            if WINDOW_ICON_PATH.exists():
                self.window_icon = tk.PhotoImage(file=str(WINDOW_ICON_PATH))
                self.root.iconphoto(True, self.window_icon)
        except Exception:
            pass

    def _build_style(self) -> None:
        self.style = ttk.Style(self.root)
        try:
            self.style.theme_use("clam")
        except Exception:
            pass
        self.apply_font_size(save=False)

    def normalized_font_size(self) -> int:
        try:
            size = int(self.config.get("font_size", 10))
        except (TypeError, ValueError):
            size = 10
        return min(25, max(9, size))

    def apply_font_size(self, save: bool = True) -> None:
        size = self.normalized_font_size()
        self.config["font_size"] = size
        for name in ("TkDefaultFont", "TkTextFont", "TkFixedFont", "TkMenuFont", "TkHeadingFont", "TkIconFont", "TkTooltipFont"):
            try:
                font = tkfont.nametofont(name)
                font.configure(size=size)
            except tk.TclError:
                pass
        try:
            self.root.option_add("*Font", tkfont.nametofont("TkDefaultFont"))
        except tk.TclError:
            pass
        row_height = max(24, int(size * 2.4))
        try:
            self.style.configure("Treeview", rowheight=row_height)
            self.style.configure("Treeview.Heading", font=tkfont.nametofont("TkHeadingFont"))
        except Exception:
            pass
        if save:
            self.save_config()
            self.set_status(f"文字サイズを {size}pt に変更しました。")

    def set_font_size(self, size: int) -> None:
        self.config["font_size"] = size
        self.apply_font_size(save=True)

    def build_label_submenu(self, parent_menu: tk.Menu) -> tk.Menu:
        label_menu = tk.Menu(parent_menu, tearoff=False)
        for digit in "123456789":
            label_menu.add_command(label=digit, command=lambda d=digit: self.assign_label_to_selected(d))
        label_menu.add_separator()
        label_menu.add_command(label="解除", command=lambda: self.assign_label_to_selected("0"))
        return label_menu

    def _build_menu(self) -> None:
        menubar = tk.Menu(self.root)

        file_menu = tk.Menu(menubar, tearoff=False)
        file_menu.add_command(label="終了", command=self.on_close)
        menubar.add_cascade(label="ファイル", menu=file_menu)

        action_menu = tk.Menu(menubar, tearoff=False)
        action_menu.add_command(label="実行", command=self.run_selected_tool, accelerator="Enter")
        action_menu.add_command(label="コマンドプロンプト", command=self.open_selected_command_prompt)
        action_menu.add_separator()
        action_menu.add_command(label="実行環境", command=self.open_selected_repository_folder)
        action_menu.add_command(label="開発環境", command=self.open_selected_development_folder)
        action_menu.add_command(label="GitHub", command=self.open_selected_github_page)
        action_menu.add_command(label="README", command=self.open_selected_readme)
        action_menu.add_separator()
        action_menu.add_cascade(label="ラベル", menu=self.build_label_submenu(action_menu))
        action_menu.add_separator()
        action_menu.add_command(label="最新バージョン取得", command=self.update_selected_repository, accelerator="F5")
        action_menu.add_command(label="全取得", command=self.update_all_repositories)
        menubar.add_cascade(label="操作", menu=action_menu)

        settings_menu = tk.Menu(menubar, tearoff=False)
        settings_menu.add_command(label="環境設定", command=self.open_settings)
        settings_menu.add_command(label="ツール管理", command=self.open_tool_manager)
        settings_menu.add_command(label="GitHub候補登録", command=self.open_repository_import)
        settings_menu.add_command(label="ラベル管理", command=self.open_label_manager)
        settings_menu.add_separator()
        font_menu = tk.Menu(settings_menu, tearoff=False)
        self.font_size_var = tk.IntVar(value=self.normalized_font_size())
        for size in range(9, 26):
            font_menu.add_radiobutton(
                label=f"{size}pt",
                variable=self.font_size_var,
                value=size,
                command=lambda s=size: self.set_font_size(s),
            )
        settings_menu.add_cascade(label="文字サイズ", menu=font_menu)
        menubar.add_cascade(label="設定", menu=settings_menu)

        help_menu = tk.Menu(menubar, tearoff=False)
        help_menu.add_command(label="バージョン情報", command=self.show_about)
        menubar.add_cascade(label="ヘルプ", menu=help_menu)

        self.root.configure(menu=menubar)
        self.root.bind("<Return>", lambda _e: self.run_selected_tool())
        self.root.bind("<F5>", lambda _e: self.update_selected_repository())
        self.root.bind("<Escape>", close_event_break(self.on_close))
        self.root.bind("<Control-f>", lambda _e: self.search_entry.focus_set())
        for digit in "0123456789":
            self.root.bind(f"<KeyPress-{digit}>", self.on_label_key)

    def _build_main_ui(self) -> None:
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(1, weight=1)

        filter_frame = ttk.Frame(self.root, padding=(12, 12, 12, 6))
        filter_frame.grid(row=0, column=0, sticky="ew")
        filter_frame.columnconfigure(0, weight=1)

        self.search_var = tk.StringVar()
        self.search_var.trace_add("write", lambda *_args: self.refresh_tree())
        self.search_entry = ttk.Entry(filter_frame, textvariable=self.search_var)
        self.search_entry.grid(row=0, column=0, sticky="ew")
        ttk.Button(filter_frame, text="×", width=3, command=self.clear_search).grid(row=0, column=1, sticky="e", padx=(6, 12))

        ttk.Label(filter_frame, text="カテゴリ").grid(row=0, column=2, sticky="e", padx=(0, 6))
        self.category_filter_var = tk.StringVar(value="すべて")
        self.category_combo = ttk.Combobox(filter_frame, textvariable=self.category_filter_var, values=["すべて"], state="readonly", width=18)
        self.category_combo.grid(row=0, column=3, sticky="e")
        self.category_combo.bind("<<ComboboxSelected>>", lambda _e: self.refresh_tree())

        list_frame = ttk.Frame(self.root, padding=(12, 0, 12, 6))
        list_frame.grid(row=1, column=0, sticky="nsew")
        list_frame.columnconfigure(0, weight=1)
        list_frame.rowconfigure(0, weight=1)

        self.tree = ttk.Treeview(
            list_frame,
            columns=("title", "repository", "category", "state", "last_run", "last_update"),
            show="headings",
            selectmode="browse",
        )
        self.tree.heading("title", text="タイトル")
        self.tree.heading("repository", text="リポジトリ")
        self.tree.heading("category", text="カテゴリ")
        self.tree.heading("state", text="状態")
        self.tree.heading("last_run", text="最終実行")
        self.tree.heading("last_update", text="最終更新")
        self.tree.column("title", width=300, anchor="w")
        self.tree.column("repository", width=260, anchor="w")
        self.tree.column("category", width=120, anchor="w")
        self.tree.column("state", width=110, anchor="w")
        self.tree.column("last_run", width=110, anchor="w")
        self.tree.column("last_update", width=110, anchor="w")
        self.tree.grid(row=0, column=0, sticky="nsew")
        self.tree.bind("<Double-1>", lambda _e: self.run_selected_tool())
        self.tree.bind("<<TreeviewSelect>>", lambda _e: self.update_selection_status())

        yscroll = ttk.Scrollbar(list_frame, orient="vertical", command=self.tree.yview)
        yscroll.grid(row=0, column=1, sticky="ns")
        self.tree.configure(yscrollcommand=yscroll.set)
        self.configure_label_tags()

        self.tree.bind("<Button-3>", self.show_tree_context_menu)
        self.tree.bind("<Control-Button-1>", self.show_tree_context_menu)

        self.tree_context_menu = tk.Menu(self.root, tearoff=False)
        self.tree_context_menu.add_command(label="実行", command=self.run_selected_tool)
        self.tree_context_menu.add_command(label="コマンドプロンプト", command=self.open_selected_command_prompt)
        self.tree_context_menu.add_separator()
        self.tree_context_menu.add_command(label="実行環境", command=self.open_selected_repository_folder)
        self.tree_context_menu.add_command(label="開発環境", command=self.open_selected_development_folder)
        self.tree_context_menu.add_command(label="GitHub", command=self.open_selected_github_page)
        self.tree_context_menu.add_command(label="README", command=self.open_selected_readme)
        self.tree_context_menu.add_separator()
        self.tree_context_menu.add_cascade(label="ラベル", menu=self.build_label_submenu(self.tree_context_menu))
        self.tree_context_menu.add_separator()
        self.tree_context_menu.add_command(label="最新バージョン取得", command=self.update_selected_repository)

        self.status_var = tk.StringVar()
        status = ttk.Label(self.root, textvariable=self.status_var, anchor="w", relief="sunken", padding=(8, 3))
        status.grid(row=2, column=0, sticky="ew")

    def restore_or_center_geometry(self) -> None:
        geometry = str(self.config.get("window_geometry", ""))
        if geometry and is_geometry_on_screen(self.root, geometry):
            self.root.geometry(geometry)
        else:
            center_window(self.root, *WINDOW_DEFAULT_SIZE)

    def show_main_window(self) -> None:
        """Show the root window only after UI construction and final geometry are complete."""
        try:
            self.root.update_idletasks()
            self.root.deiconify()
            self.root.lift()
            self.root.focus_force()
        except Exception:
            pass

    def save_config(self) -> None:
        save_json(CONFIG_PATH, self.config)

    def save_tools(self) -> None:
        save_json(TOOLS_PATH, self.tools)

    def set_status(self, message: str) -> None:
        self.status_var.set(message)

    def clear_search(self) -> None:
        self.search_var.set("")
        self.search_entry.focus_set()

    def refresh_category_filter(self) -> None:
        categories = sorted({tool.get("category", "").strip() for tool in self.tools if tool.get("category", "").strip()})
        values = ["すべて"] + categories
        current = self.category_filter_var.get() if hasattr(self, "category_filter_var") else "すべて"
        self.category_combo.configure(values=values)
        if current not in values:
            self.category_filter_var.set("すべて")

    def get_tool_state_label(self, tool: dict[str, str]) -> str:
        if validate_repository_name_value(tool.get("repository", "")):
            return "設定エラー"
        repo_dir = self.repository_path_for(tool)
        last_status = tool.get("last_update_status", "")
        if last_status == "failed":
            return "取得失敗"
        if repo_dir.exists() and (repo_dir / ".git").exists():
            return "取得済み"
        if repo_dir.exists():
            return "要確認"
        return "未取得"

    def refresh_tree(self) -> None:
        old_selection_index = self.get_selected_tool_index()
        query = self.search_var.get().strip().lower() if hasattr(self, "search_var") else ""
        category_filter = self.category_filter_var.get() if hasattr(self, "category_filter_var") else "すべて"
        self.tree.delete(*self.tree.get_children())
        self.filtered_indices = []
        for index, tool in enumerate(self.tools):
            if category_filter != "すべて" and tool.get("category", "") != category_filter:
                continue
            haystack = " ".join(
                [
                    tool.get("title", ""),
                    tool.get("repository", ""),
                    tool.get("script", ""),
                    tool.get("category", ""),
                    tool.get("tags", ""),
                    tool.get("run_method", ""),
                ]
            ).lower()
            if query and query not in haystack:
                continue
            item_id = str(index)
            self.filtered_indices.append(index)
            label_id = normalize_label_id(tool.get("label", ""))
            tags = (f"label_{label_id}",) if label_id else ()
            self.tree.insert(
                "",
                "end",
                iid=item_id,
                values=(
                    tool["title"],
                    tool["repository"],
                    tool.get("category", ""),
                    self.get_tool_state_label(tool),
                    shorten_datetime(tool.get("last_run_at", "")),
                    shorten_datetime(tool.get("last_update_at", "")),
                ),
                tags=tags,
            )
        if old_selection_index is not None and str(old_selection_index) in self.tree.get_children():
            self.tree.selection_set(str(old_selection_index))
            self.tree.see(str(old_selection_index))
        elif self.filtered_indices:
            first = str(self.filtered_indices[0])
            self.tree.selection_set(first)
        self.update_selection_status()

    def update_selection_status(self) -> None:
        index = self.get_selected_tool_index()
        if index is None or not (0 <= index < len(self.tools)):
            self.set_status("ツールが選択されていません。")
            return
        tool = self.tools[index]
        method = RUN_METHOD_LABELS.get(tool.get("run_method", "auto"), "自動")
        state = self.get_tool_state_label(tool)
        self.set_status(f"選択中: {tool['title']} / {tool['repository']} / {method} / {state}")

    def show_tree_context_menu(self, event: tk.Event) -> str:
        row_id = self.tree.identify_row(event.y)
        if not row_id:
            return "break"
        self.tree.selection_set(row_id)
        self.tree.focus(row_id)
        self.update_selection_status()
        try:
            self.tree_context_menu.tk_popup(event.x_root, event.y_root)
        finally:
            self.tree_context_menu.grab_release()
        return "break"

    def get_selected_tool_index(self) -> int | None:
        if not hasattr(self, "tree"):
            return None
        selection = self.tree.selection()
        if not selection:
            return None
        try:
            return int(selection[0])
        except ValueError:
            return None

    def get_selected_tool(self) -> dict[str, str] | None:
        index = self.get_selected_tool_index()
        if index is None or not (0 <= index < len(self.tools)):
            return None
        return self.tools[index]

    def find_repository_index(self, repository: str, exclude_index: int | None = None) -> int | None:
        target = repository.strip().lower()
        for index, tool in enumerate(self.tools):
            if exclude_index is not None and index == exclude_index:
                continue
            if tool.get("repository", "").strip().lower() == target:
                return index
        return None

    def validate_repository_for_tool(self, tool: dict[str, str], parent: tk.Misc | None = None) -> bool:
        error = validate_repository_name_value(tool.get("repository", ""))
        if error:
            messagebox.showwarning("設定エラー", f"{tool.get('title', '選択中ツール')} のリポジトリ名が不正です。\n\n{error}", parent=parent or self.root)
            return False
        return True

    def validate_script_for_tool(self, tool: dict[str, str], parent: tk.Misc | None = None) -> bool:
        error = validate_script_path_value(tool.get("script", ""))
        if error:
            messagebox.showwarning("設定エラー", f"{tool.get('title', '選択中ツール')} の実行スクリプトが不正です。\n\n{error}", parent=parent or self.root)
            return False
        return True

    def validate_tool_paths(self, tool: dict[str, str], *, require_script: bool = False, parent: tk.Misc | None = None) -> bool:
        if not self.validate_repository_for_tool(tool, parent=parent):
            return False
        if require_script and not self.validate_script_for_tool(tool, parent=parent):
            return False
        return True

    def repository_path_for(self, tool: dict[str, str]) -> Path:
        repository = tool.get("repository", "").strip()
        if validate_repository_name_value(repository):
            return REPOSITORY_DIR / "__invalid_repository_name__"
        return REPOSITORY_DIR / repository

    def development_path_for(self, tool: dict[str, str]) -> Path:
        dev_root = Path(str(self.config.get("development_root", r"C:\Documents\GitHub"))).expanduser()
        repository = tool.get("repository", "").strip()
        if validate_repository_name_value(repository):
            return dev_root / "__invalid_repository_name__"
        return dev_root / repository

    def script_path_for(self, tool: dict[str, str]) -> Path:
        repo_dir = self.repository_path_for(tool)
        script = tool.get("script", "")
        if validate_script_path_value(script):
            return repo_dir / "__invalid_script_path__"
        return safe_path_within(repo_dir, script)

    def github_url_for(self, tool: dict[str, str]) -> str | None:
        github_user = str(self.config.get("github_user_id", "")).strip()
        if not github_user or validate_repository_name_value(tool.get("repository", "")):
            return None
        return f"https://github.com/{github_user}/{tool['repository']}"

    def configure_label_tags(self) -> None:
        if not hasattr(self, "tree"):
            return
        labels = normalize_label_settings(self.config.get("labels"))
        for label_id, colors in labels.items():
            try:
                self.tree.tag_configure(
                    f"label_{label_id}",
                    foreground=colors["foreground"],
                    background=colors["background"],
                )
            except tk.TclError:
                pass

    def is_text_input_widget(self, widget: tk.Misc) -> bool:
        widget_class = str(widget.winfo_class()).lower()
        return any(name in widget_class for name in ("entry", "combobox", "text", "spinbox"))

    def on_label_key(self, event: tk.Event) -> str | None:
        widget = event.widget
        if isinstance(widget, tk.Misc) and self.is_text_input_widget(widget):
            return None
        digit = str(getattr(event, "char", "") or "")
        if digit not in "0123456789":
            return None
        self.assign_label_to_selected(digit)
        return "break"

    def assign_label_to_selected(self, digit: str) -> None:
        index = self.get_selected_tool_index()
        if index is None or not (0 <= index < len(self.tools)):
            self.set_status("ラベルを設定するツールが選択されていません。")
            return
        label_id = "" if digit == "0" else digit
        self.tools[index]["label"] = label_id
        self.save_tools()
        self.refresh_tree()
        if str(index) in self.tree.get_children():
            self.tree.selection_set(str(index))
            self.tree.see(str(index))
        tool = self.tools[index]
        if label_id:
            self.set_status(f"ラベル {label_id} を設定しました: {tool['title']}")
        else:
            self.set_status(f"ラベルを解除しました: {tool['title']}")

    def open_label_manager(self) -> None:
        LabelManagerDialog(self)

    def open_settings(self) -> None:
        SettingsDialog(self)

    def open_tool_manager(self) -> None:
        ToolManagerDialog(self)

    def open_repository_import(self) -> None:
        github_user = str(self.config.get("github_user_id", "")).strip()
        if not github_user:
            messagebox.showwarning("設定不足", "GitHubユーザIDを環境設定で入力してください。", parent=self.root)
            return
        dialog = RepositoryImportDialog(self, github_user)

        def worker() -> None:
            try:
                repos = self.fetch_github_repositories(github_user)
            except Exception as exc:
                self.root.after(0, dialog.set_error, f"GitHubリポジトリ一覧を取得できませんでした。\n\n{exc}")
                return
            self.root.after(0, dialog.set_repositories, repos)

        threading.Thread(target=worker, daemon=True).start()

    def fetch_github_repositories(self, github_user: str) -> list[dict[str, str]]:
        repos: list[dict[str, str]] = []
        for page in range(1, 11):
            url = f"https://api.github.com/users/{github_user}/repos?per_page=100&page={page}&sort=updated"
            request = urllib.request.Request(
                url,
                headers={
                    "Accept": "application/vnd.github+json",
                    "User-Agent": f"{APP_NAME}/{APP_VERSION}",
                },
            )
            try:
                with urllib.request.urlopen(request, timeout=20) as response:
                    data = json.loads(response.read().decode("utf-8", errors="replace"))
            except urllib.error.HTTPError as exc:
                if exc.code == 404:
                    raise RuntimeError("GitHubユーザが見つかりません。") from exc
                if exc.code == 403:
                    raise RuntimeError("GitHub APIの制限に達した可能性があります。しばらく待ってから試してください。") from exc
                raise RuntimeError(f"GitHub API エラー: HTTP {exc.code}") from exc
            except urllib.error.URLError as exc:
                raise RuntimeError(f"通信エラー: {exc.reason}") from exc
            if not isinstance(data, list):
                break
            for item in data:
                if not isinstance(item, dict):
                    continue
                name = str(item.get("name", "")).strip()
                if not name:
                    continue
                repos.append(
                    {
                        "name": name,
                        "description": str(item.get("description") or ""),
                        "html_url": str(item.get("html_url") or f"https://github.com/{github_user}/{name}"),
                    }
                )
            if len(data) < 100:
                break
        return repos

    def show_about(self) -> None:
        messagebox.showinfo(
            "バージョン情報",
            f"{APP_NAME}\nバージョン: {APP_VERSION}\n\nGitHubリポジトリの実行用コピーを管理して起動するランチャーです。",
            parent=self.root,
        )

    def require_tool(self) -> dict[str, str] | None:
        tool = self.get_selected_tool()
        if tool is None:
            messagebox.showwarning("未選択", "ツールを選択してください。", parent=self.root)
            return None
        return tool

    def ensure_runtime_marker(self, tool: dict[str, str]) -> Path | None:
        repo_dir = self.repository_path_for(tool)
        if not repo_dir.exists():
            return None
        marker = repo_dir / RUNTIME_MARKER_NAME
        try:
            marker.write_text(runtime_marker_text(tool, repo_dir, self.development_path_for(tool)), encoding="utf-8", newline="\n")
        except OSError:
            return None
        exclude_path = repo_dir / ".git" / "info" / "exclude"
        try:
            exclude_path.parent.mkdir(parents=True, exist_ok=True)
            current = exclude_path.read_text(encoding="utf-8", errors="replace") if exclude_path.exists() else ""
            if RUNTIME_MARKER_NAME not in current:
                with exclude_path.open("a", encoding="utf-8", newline="\n") as f:
                    if current and not current.endswith("\n"):
                        f.write("\n")
                    f.write(f"# GitHub Tool Launcher runtime marker\n{RUNTIME_MARKER_NAME}\n")
        except OSError:
            pass
        return marker

    def open_selected_repository_folder(self) -> None:
        tool = self.require_tool()
        if tool is None or not self.validate_tool_paths(tool):
            return
        path = self.repository_path_for(tool)
        if not path.exists():
            messagebox.showwarning("フォルダなし", f"実行環境フォルダが見つかりません。\n\n{path}", parent=self.root)
            return
        marker = self.ensure_runtime_marker(tool)
        if marker is not None and marker.exists():
            open_in_file_manager_select(marker)
        else:
            open_in_file_manager(path)

    def open_selected_command_prompt(self) -> None:
        tool = self.require_tool()
        if tool is None or not self.validate_tool_paths(tool):
            return
        path = self.repository_path_for(tool)
        if not path.exists():
            messagebox.showwarning("フォルダなし", f"実行環境フォルダが見つかりません。\n\n{path}", parent=self.root)
            return
        try:
            if is_windows():
                kwargs: dict[str, Any] = {}
                creationflags = getattr(subprocess, "CREATE_NEW_CONSOLE", 0)
                if creationflags:
                    kwargs["creationflags"] = creationflags
                subprocess.Popen(["cmd.exe"], cwd=str(path), **kwargs)
            elif sys.platform == "darwin":
                subprocess.Popen(["open", "-a", "Terminal", str(path)])
            else:
                subprocess.Popen(["x-terminal-emulator", "--working-directory", str(path)])
            self.set_status(f"コマンドプロンプトを開きました: {tool['repository']}")
        except Exception as exc:
            messagebox.showerror("起動失敗", f"コマンドプロンプトを開けませんでした。\n\n{exc}", parent=self.root)

    def open_selected_development_folder(self) -> None:
        tool = self.require_tool()
        if tool is None or not self.validate_tool_paths(tool):
            return
        path = self.development_path_for(tool)
        if not path.exists():
            messagebox.showwarning("フォルダなし", f"開発環境フォルダが見つかりません。\n\n{path}", parent=self.root)
            return
        open_in_file_manager(path)

    def open_selected_github_page(self) -> None:
        tool = self.require_tool()
        if tool is None or not self.validate_tool_paths(tool):
            return
        url = self.github_url_for(tool)
        if not url:
            messagebox.showwarning("設定不足", "GitHubユーザIDを環境設定で入力してください。", parent=self.root)
            return
        webbrowser.open(url)
        self.set_status(f"GitHubページを開きました: {tool['repository']}")

    def find_readme_path(self, repo_dir: Path) -> Path | None:
        for name in ["README.md", "readme.md", "README.txt", "readme.txt", "README", "readme"]:
            path = repo_dir / name
            if path.exists() and path.is_file():
                return path
        return None

    def open_selected_readme(self) -> None:
        tool = self.require_tool()
        if tool is None or not self.validate_tool_paths(tool):
            return
        repo_dir = self.repository_path_for(tool)
        readme = self.find_readme_path(repo_dir) if repo_dir.exists() else None
        if readme is not None:
            open_in_file_manager(readme)
            self.set_status(f"READMEを開きました: {tool['repository']}")
            return
        url = self.github_url_for(tool)
        if not url:
            messagebox.showwarning("READMEなし", "ローカルREADMEが見つかりません。GitHubユーザIDも未設定のためWeb READMEを開けません。", parent=self.root)
            return
        webbrowser.open(url + "#readme")
        self.set_status(f"GitHub READMEを開きました: {tool['repository']}")

    def run_selected_tool(self) -> None:
        tool = self.require_tool()
        if tool is None or not self.validate_tool_paths(tool, require_script=True):
            return
        repo_dir = self.repository_path_for(tool)
        script_path = self.script_path_for(tool)
        if not repo_dir.exists():
            messagebox.showwarning(
                "未取得",
                f"実行環境リポジトリがありません。\n先に [最新バージョン取得] を実行してください。\n\n{repo_dir}",
                parent=self.root,
            )
            return
        if tool.get("run_method", "auto") != "command" and not script_path.is_file():
            messagebox.showwarning("実行ファイルなし", f"実行スクリプトが見つかりません。\n\n{script_path}", parent=self.root)
            return

        try:
            self.launch_script(tool, repo_dir, script_path)
            tool["last_run_at"] = now_text()
            self.save_tools()
            self.refresh_tree()
            self.set_status(f"実行しました: {tool['title']}")
        except Exception as exc:
            messagebox.showerror("実行失敗", f"起動できませんでした。\n\n{exc}", parent=self.root)

    def custom_command_for(self, tool: dict[str, str], repo_dir: Path, script_path: Path) -> str:
        command = tool.get("custom_command", "").strip()
        rel_script = os.path.normpath(normalize_script_path_text(tool["script"]).replace("/", os.sep))
        replacements = {
            "{script_path_q}": quote_command_arg(str(script_path)),
            "{repo_dir_q}": quote_command_arg(str(repo_dir)),
            "{script_q}": quote_command_arg(rel_script),
            "{repo_q}": quote_command_arg(tool["repository"]),
            "{script_path}": str(script_path),
            "{repo_dir}": str(repo_dir),
            "{script}": rel_script,
            "{repo}": tool["repository"],
        }
        for key, value in replacements.items():
            command = command.replace(key, value)
        return command

    def launch_script(self, tool: dict[str, str], repo_dir: Path, script_path: Path) -> None:
        ext = script_path.suffix.lower()
        rel_script = os.path.normpath(normalize_script_path_text(tool["script"]).replace("/", os.sep))
        method = tool.get("run_method", "auto")
        if method == "auto":
            if ext in {".py", ".pyw"}:
                # Launcher targets are mostly GUI tools.  Use pythonw by default so
                # a console window is not opened.  Console tools can explicitly use
                # the "python" run method.
                method = "pythonw"
            elif ext in {".bat", ".cmd"}:
                method = "bat"
            elif ext == ".exe":
                method = "exe"
            else:
                method = "open"

        if method == "command":
            command = self.custom_command_for(tool, repo_dir, script_path)
            if not command:
                raise RuntimeError("任意コマンドが空です。")
            if is_windows():
                launch_windows_minimized_console(["cmd.exe", "/c", command], repo_dir)
            else:
                subprocess.Popen(command, cwd=str(repo_dir), shell=True)
            return

        if is_windows():
            if method == "python":
                # Keep the console minimized without passing SW_MINIMIZE to python.exe,
                # because that can make a GUI tool's main window start minimized.
                launch_windows_minimized_console([windows_executable("python"), rel_script], repo_dir)
            elif method == "pythonw":
                # pythonw.exe already avoids the console window.  Do not pass
                # STARTUPINFO/SW_HIDE, because that can hide the GUI tool itself.
                subprocess.Popen([windows_executable("pythonw"), rel_script], cwd=str(repo_dir))
            elif method == "bat":
                launch_windows_minimized_console(["cmd.exe", "/c", rel_script], repo_dir)
            elif method == "exe":
                subprocess.Popen([str(script_path)], cwd=str(repo_dir))
            else:
                os.startfile(str(script_path))  # type: ignore[attr-defined]
        else:
            if method in {"python", "pythonw"}:
                subprocess.Popen([sys.executable, str(script_path)], cwd=str(repo_dir))
            elif method == "bat":
                subprocess.Popen(["sh", str(script_path)], cwd=str(repo_dir))
            else:
                subprocess.Popen([str(script_path)], cwd=str(repo_dir))

    def validate_update_ready(self, parent: tk.Misc | None = None) -> tuple[str, str] | None:
        message_parent = parent or self.root
        github_user = str(self.config.get("github_user_id", "")).strip()
        if not github_user:
            messagebox.showwarning("設定不足", "GitHubユーザIDを環境設定で入力してください。", parent=message_parent)
            return None
        git_path = shutil.which("git")
        if not git_path:
            messagebox.showerror("Gitなし", "git が見つかりません。GitをインストールするかPATHを通してください。", parent=message_parent)
            return None
        return github_user, git_path

    def build_git_command(self, tool: dict[str, str], github_user: str, git_path: str) -> tuple[list[str], str, str, Path] | tuple[None, str, str, Path]:
        repo_error = validate_repository_name_value(tool.get("repository", ""))
        repo_dir = self.repository_path_for(tool)
        repo_url = f"https://github.com/{github_user}/{tool.get('repository', '')}.git"
        if repo_error:
            return None, "invalid", repo_url, repo_dir
        if repo_dir.exists():
            if not (repo_dir / ".git").exists():
                return None, "not_git", repo_url, repo_dir
            return [git_path, "-C", str(repo_dir), "pull", "--ff-only"], "pull", repo_url, repo_dir
        REPOSITORY_DIR.mkdir(parents=True, exist_ok=True)
        return [git_path, "clone", repo_url, str(repo_dir)], "clone", repo_url, repo_dir

    def update_selected_repository(self) -> None:
        if self.process_running:
            messagebox.showinfo("処理中", "すでに取得処理が動いています。", parent=self.root)
            return
        tool = self.require_tool()
        if tool is None or not self.validate_tool_paths(tool):
            return
        ready = self.validate_update_ready()
        if ready is None:
            return
        github_user, git_path = ready
        self.update_repositories([tool], github_user, git_path, "最新バージョンを取得")

    def update_all_repositories(self) -> None:
        if self.process_running:
            messagebox.showinfo("処理中", "すでに取得処理が動いています。", parent=self.root)
            return
        if not self.tools:
            messagebox.showinfo("対象なし", "登録されているツールがありません。", parent=self.root)
            return
        ready = self.validate_update_ready()
        if ready is None:
            return
        github_user, git_path = ready
        self.update_repositories(list(self.tools), github_user, git_path, "全ツールの最新バージョンを取得")

    def update_repositories(self, tools: list[dict[str, str]], github_user: str, git_path: str, title: str) -> None:
        dialog = CommandLogDialog(self.root, title)
        dialog.append(f"対象数: {len(tools)}\n")
        dialog.append(f"保存先: {REPOSITORY_DIR}\n\n")
        self.process_running = True
        self.set_status(f"取得処理中... {len(tools)}件")

        def worker() -> None:
            success_count = 0
            fail_count = 0
            encoding = locale.getpreferredencoding(False) or "utf-8"
            for pos, tool in enumerate(tools, 1):
                cmd, action, repo_url, repo_dir = self.build_git_command(tool, github_user, git_path)
                self.root.after(0, dialog.append, f"[{pos}/{len(tools)}] {tool['title']} / {tool['repository']}\n")
                self.root.after(0, dialog.append, f"操作: {action}\nリポジトリ: {repo_url}\n保存先: {repo_dir}\n")
                if cmd is None:
                    fail_count += 1
                    tool["last_update_at"] = now_text()
                    tool["last_update_status"] = "failed"
                    if action == "invalid":
                        self.root.after(0, dialog.append, "ERROR: リポジトリ名が不正です。処理しません。\n\n")
                    else:
                        self.root.after(0, dialog.append, "ERROR: フォルダは存在しますがGitリポジトリではありません。安全のため処理しません。\n\n")
                    continue
                code = -1
                try:
                    process = subprocess.Popen(
                        cmd,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.STDOUT,
                        text=True,
                        encoding=encoding,
                        errors="replace",
                        cwd=str(BASE_DIR),
                        **windows_no_console_kwargs(),
                    )
                    assert process.stdout is not None
                    for line in process.stdout:
                        self.root.after(0, dialog.append, line)
                    code = process.wait()
                except Exception as exc:
                    self.root.after(0, dialog.append, f"ERROR: {exc}\n")
                tool["last_update_at"] = now_text()
                if code == 0:
                    success_count += 1
                    tool["last_update_status"] = "success"
                    self.ensure_runtime_marker(tool)
                    self.root.after(0, dialog.append, "完了しました。\n\n")
                else:
                    fail_count += 1
                    tool["last_update_status"] = "failed"
                    self.root.after(0, dialog.append, f"失敗しました。終了コード: {code}\n\n")

            def finish() -> None:
                self.process_running = False
                self.save_tools()
                self.refresh_tree()
                dialog.append(f"完了: 成功 {success_count} / 失敗 {fail_count}\n")
                self.set_status(f"取得処理完了: 成功 {success_count} / 失敗 {fail_count}")
                dialog.finish()

            self.root.after(0, finish)

        threading.Thread(target=worker, daemon=True).start()

    def on_close(self) -> None:
        self.config["window_geometry"] = self.root.geometry()
        self.save_config()
        self.root.destroy()

    def run(self) -> None:
        self.root.mainloop()


if __name__ == "__main__":
    GitHubToolLauncher().run()
