"""Utility script to configure Cedric auto-start at Windows logon.

Can install or uninstall Cedric from the Windows Startup folder using pythonw.exe
so no terminal console window appears.

Usage:
    python scripts/setup_autostart.py --install
    python scripts/setup_autostart.py --uninstall
"""

import os
import sys
import argparse
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def get_startup_dir() -> Path:
    return Path(os.path.expandvars(r"%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup"))


def get_pythonw_path() -> Path:
    venv_pythonw = PROJECT_ROOT / ".venv" / "Scripts" / "pythonw.exe"
    if venv_pythonw.is_file():
        return venv_pythonw
    # Fallback to system pythonw
    sys_dir = Path(sys.executable).parent
    sys_pythonw = sys_dir / "pythonw.exe"
    if sys_pythonw.is_file():
        return sys_pythonw
    return Path(sys.executable)


def install_autostart() -> bool:
    startup_dir = get_startup_dir()
    if not startup_dir.is_dir():
        print(f"Error: Startup folder not found: {startup_dir}")
        return False

    vbs_path = startup_dir / "CedricAssistant.vbs"
    pythonw = get_pythonw_path()
    run_py = PROJECT_ROOT / "run.py"

    # Create small VBS launcher to execute silently in background without console window
    vbs_lines = [
        'Set WshShell = CreateObject("WScript.Shell")',
        f'WshShell.CurrentDirectory = "{PROJECT_ROOT}"',
        f'WshShell.Run chr(34) & "{pythonw}" & chr(34) & " " & chr(34) & "{run_py}" & chr(34), 0, False',
    ]
    vbs_content = "\r\n".join(vbs_lines) + "\r\n"

    try:
        with open(vbs_path, "w", encoding="utf-8") as f:
            f.write(vbs_content)
        print(f"Successfully configured Cedric auto-start: {vbs_path}")
        print(f"Target: {pythonw} {run_py}")
        return True
    except Exception as e:
        print(f"Failed to configure auto-start: {e}")
        return False


def uninstall_autostart() -> bool:
    startup_dir = get_startup_dir()
    vbs_path = startup_dir / "CedricAssistant.vbs"
    if vbs_path.is_file():
        try:
            vbs_path.unlink()
            print("Successfully removed Cedric from auto-start.")
            return True
        except Exception as e:
            print(f"Failed to remove auto-start shortcut: {e}")
            return False
    else:
        print("Cedric auto-start was not installed.")
        return True


def main():
    parser = argparse.ArgumentParser(description="Configure Cedric Auto-Start")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--install", action="store_true", help="Install Cedric into Windows Startup")
    group.add_argument("--uninstall", action="store_true", help="Remove Cedric from Windows Startup")

    args = parser.parse_args()
    if args.install:
        install_autostart()
    elif args.uninstall:
        uninstall_autostart()


if __name__ == "__main__":
    main()

