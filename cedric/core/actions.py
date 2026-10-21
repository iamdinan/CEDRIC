"""Action execution and application resolution for Cedric."""

import os
import shutil
import subprocess
import webbrowser
import logging
import winreg
from pathlib import Path
from typing import Optional, Dict, Any

try:
    import win32gui
    import win32con
    import win32process
    HAS_WIN32 = True
except ImportError:
    HAS_WIN32 = False

logger = logging.getLogger("cedric.actions")


def resolve_chrome_path(custom_path: Optional[str] = None) -> Optional[str]:
    """Finds Google Chrome executable path."""
    if custom_path and os.path.isfile(custom_path):
        return custom_path

    # Registry check: App Paths
    for root in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
        try:
            with winreg.OpenKey(root, r"Software\Microsoft\Windows\CurrentVersion\App Paths\chrome.exe") as k:
                val, _ = winreg.QueryValueEx(k, "")
                if val and os.path.isfile(val):
                    return val
        except OSError:
            pass

    # shutil.which
    which_path = shutil.which("chrome")
    if which_path and os.path.isfile(which_path):
        return which_path

    # Standard default paths
    candidates = [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
    ]
    for c in candidates:
        if os.path.isfile(c):
            return c

    return None


def resolve_lnk_target(lnk_path: str) -> Optional[str]:
    """Resolves target path from a Windows .lnk file using PowerShell or COM."""
    if not os.path.isfile(lnk_path):
        return None
    try:
        cmd = [
            "powershell",
            "-NoProfile",
            "-Command",
            f"$s = (New-Object -ComObject WScript.Shell).CreateShortcut('{lnk_path}'); Write-Output $s.TargetPath"
        ]
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=3)
        target = res.stdout.strip()
        if target and os.path.exists(target):
            return target
    except Exception as e:
        logger.debug(f"Failed to resolve shortcut {lnk_path}: {e}")
    return None


def resolve_exe_path(app_name: str, configured_paths: Optional[Dict[str, str]] = None) -> Optional[str]:
    """Resolves executable path for an application in order:
    1. settings.yaml configured path
    2. shutil.which
    3. registry App Paths
    4. Start Menu .lnk shortcuts
    5. shell:AppsFolder / Common locations
    """
    app_key = app_name.lower().replace(" ", "").replace("_", "")
    
    # 1. Configured paths
    if configured_paths:
        for k, v in configured_paths.items():
            norm_k = k.lower().replace(" ", "").replace("_", "")
            if norm_k == app_key or app_key in norm_k:
                if v and os.path.isfile(os.path.expandvars(v)):
                    return os.path.expandvars(v)

    # 2. shutil.which
    candidate = shutil.which(app_name)
    if candidate and os.path.isfile(candidate):
        return candidate
    candidate = shutil.which(f"{app_name}.exe")
    if candidate and os.path.isfile(candidate):
        return candidate

    # 3. Registry App Paths
    for root in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        for name in [f"{app_name}.exe", f"{app_key}.exe", app_name]:
            try:
                with winreg.OpenKey(root, rf"Software\Microsoft\Windows\CurrentVersion\App Paths\{name}") as k:
                    val, _ = winreg.QueryValueEx(k, "")
                    if val and os.path.isfile(os.path.expandvars(val)):
                        return os.path.expandvars(val)
            except OSError:
                pass

    # 4. Start Menu shortcuts (.lnk)
    start_menu_dirs = [
        os.path.expandvars(r"%APPDATA%\Microsoft\Windows\Start Menu\Programs"),
        os.path.expandvars(r"%ALLUSERSPROFILE%\Microsoft\Windows\Start Menu\Programs"),
    ]
    for d in start_menu_dirs:
        if not os.path.isdir(d):
            continue
        for root_dir, _, files in os.walk(d):
            for f in files:
                if f.lower().endswith(".lnk"):
                    name_without_ext = f[:-4].lower().replace(" ", "").replace("_", "")
                    if app_key in name_without_ext:
                        target = resolve_lnk_target(os.path.join(root_dir, f))
                        if target and os.path.isfile(target):
                            return target

    # 5. Common user AppData local programs search
    local_programs = os.path.expandvars(r"%LOCALAPPDATA%\Programs")
    if os.path.isdir(local_programs):
        for root_dir, _, files in os.walk(local_programs):
            for f in files:
                if f.lower().endswith(".exe"):
                    if app_key in f.lower().replace(" ", "").replace("_", ""):
                        full_p = os.path.join(root_dir, f)
                        if os.path.isfile(full_p):
                            return full_p

    return None


def focus_window_by_process_name(process_name: str) -> bool:
    """Attempts to find and focus a window belonging to the named process."""
    if not HAS_WIN32:
        return False

    target_hwnds = []

    def enum_cb(hwnd, _):
        if win32gui.IsWindowVisible(hwnd):
            title = win32gui.GetWindowText(hwnd)
            if title:
                _, pid = win32process.GetWindowThreadProcessId(hwnd)
                try:
                    import psutil
                    proc = psutil.Process(pid)
                    if process_name.lower() in proc.name().lower():
                        target_hwnds.append(hwnd)
                except Exception:
                    pass

    try:
        win32gui.EnumWindows(enum_cb, None)
        if target_hwnds:
            hwnd = target_hwnds[0]
            win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
            win32gui.SetForegroundWindow(hwnd)
            logger.info(f"Focused existing window for {process_name} (hwnd={hwnd})")
            return True
    except Exception as e:
        logger.debug(f"Window focus attempt failed: {e}")
    return False


def execute_action(action_spec: Dict[str, Any], configured_paths: Optional[Dict[str, str]] = None) -> bool:
    """Executes a command action based on its type: url, exe, uri, shell, special."""
    action_type = action_spec.get("type", "").lower()
    target = action_spec.get("target", "")
    name = action_spec.get("name", target)

    logger.info(f"Executing action: id={action_spec.get('id')}, type={action_type}, target={target}")

    try:
        if action_type == "url":
            browser = action_spec.get("browser", "").lower()
            chrome_path = resolve_chrome_path(configured_paths.get("chrome") if configured_paths else None)
            if browser == "chrome" and chrome_path:
                # Launching chrome.exe <url> reuses existing window with a new tab
                subprocess.Popen([chrome_path, target], shell=False)
                return True
            else:
                webbrowser.open(target)
                return True

        elif action_type == "exe":
            # Check if running and can be focused
            exe_base = os.path.splitext(os.path.basename(target))[0]
            if focus_window_by_process_name(exe_base):
                return True

            resolved = resolve_exe_path(target, configured_paths)
            if not resolved:
                logger.error(f"Could not resolve executable path for '{target}' (name: {name})")
                return False

            logger.info(f"Launching executable: {resolved}")
            subprocess.Popen([resolved], shell=False)
            return True

        elif action_type == "uri":
            try:
                os.startfile(target)
                return True
            except OSError as e:
                logger.warning(f"Failed to start URI '{target}': {e}")
                # Check fallback exe if provided (e.g. spotify)
                fallback = action_spec.get("fallback_exe")
                if fallback:
                    logger.info(f"Attempting fallback executable for URI: {fallback}")
                    resolved = resolve_exe_path(fallback, configured_paths)
                    if resolved:
                        subprocess.Popen([resolved], shell=False)
                        return True
                return False

        elif action_type == "shell":
            subprocess.Popen(target, shell=True)
            return True

        elif action_type == "special":
            # Special actions handled by the caller/orchestrator
            return True

        else:
            logger.error(f"Unknown action type: {action_type}")
            return False

    except Exception as e:
        logger.error(f"Error executing action {name}: {e}", exc_info=True)
        return False

