"""Entry point for the packaged (PyInstaller) Sector build.

Launches the Streamlit app the same way ``streamlit run app/sector_app.py`` does,
but resolves the app path inside the frozen bundle and points the writable state
(autosave, the numba compile cache) at a per-user folder so a read-only install
location (e.g. Program Files) does not break startup.
"""

from __future__ import annotations

import os
import pathlib
import sys


def _bundle_base() -> pathlib.Path:
    """Folder that holds the bundled ``app`` and ``sector`` trees.

    Frozen: PyInstaller unpacks data next to the executable (``sys._MEIPASS``);
    from source: the repository root (the parent of this ``packaging`` folder).
    """
    if getattr(sys, "frozen", False):
        return pathlib.Path(getattr(sys, "_MEIPASS", os.path.dirname(sys.executable)))
    return pathlib.Path(__file__).resolve().parent.parent


def _user_data_dir() -> pathlib.Path:
    """A writable per-user folder for autosave and the numba cache."""
    base = os.environ.get("LOCALAPPDATA") or os.environ.get("XDG_DATA_HOME")
    root = pathlib.Path(base) if base else (pathlib.Path.home() / ".sector")
    return (root / "Sector") if base else root


# Sector runs on 8502 (Streamlit's default 8501 is used by BriCoS), so both can
# be open at once. Override with the SECTOR_PORT environment variable.
_DEFAULT_PORT = "8502"
_HEADLESS_ENV = "SECTOR_HEADLESS"


def _port() -> str:
    return os.environ.get("SECTOR_PORT") or _DEFAULT_PORT


def _headless() -> bool:
    """Return the explicit acceptance-smoke browser suppression setting.

    Ordinary portable launches do not set this variable and retain the normal
    browser-opening behaviour.  A set value is deliberately strict so a typo
    cannot silently change the packaged launch boundary.
    """
    value = os.environ.get(_HEADLESS_ENV)
    if value is None:
        return False
    if value != "1":
        raise ValueError(f"{_HEADLESS_ENV} must be exactly '1' when set")
    return True


def _streamlit_argv(
    app_path: str | os.PathLike[str], port: str, *, headless: bool = False
) -> list[str]:
    """The ``streamlit run`` argv the launcher runs (isolated so it is testable)."""
    return [
        "streamlit", "run", str(app_path),
        f"--server.port={port}",
        "--server.address=127.0.0.1",      # desktop app: never expose on the LAN
        "--global.developmentMode=false",
        f"--server.headless={'true' if headless else 'false'}",
        # Frozen application files never change at runtime. Watching the large
        # bundled _internal tree adds filesystem/antivirus traffic and can stall
        # reruns without providing hot-reload value.
        "--server.fileWatcherType=none",
        "--server.runOnSave=false",
        "--browser.gatherUsageStats=false",
        "--client.toolbarMode=viewer",
        "--client.showErrorDetails=type",
    ]


def main() -> None:
    print(
        "Starting Sector; the local browser will open when the interface is ready.",
        flush=True,
    )
    app = _bundle_base() / "app" / "sector_app.py"
    data = _user_data_dir()
    try:
        data.mkdir(parents=True, exist_ok=True)
    except OSError:
        data = pathlib.Path.home()          # last resort; never block startup
    # Writable locations for the autosave file and numba's on-disk compile cache
    # (both default next to read-only bundled code in a frozen build).
    os.environ.setdefault("SECTOR_AUTOSAVE_DIR", str(data))
    os.environ.setdefault("NUMBA_CACHE_DIR", str(data / "numba_cache"))

    sys.argv = _streamlit_argv(app, _port(), headless=_headless())
    from streamlit.web import cli as stcli
    sys.exit(stcli.main())


if __name__ == "__main__":
    main()
