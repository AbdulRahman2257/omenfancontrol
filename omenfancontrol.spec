# omenfancontrol.spec
# PyInstaller spec for omenfancontrol.
# Builds two self-contained binaries sharing a single _internal directory:
#   omenfancontrol-gui    — PyQt6 dashboard, runs as user
#   omenfancontrol-daemon — hardware monitor, runs as root via systemd
#
# Usage:
#   pyinstaller omenfancontrol.spec --clean --noconfirm

block_cipher = None

# GUI bundles PyQt6 and all panel modules.
# The daemon is excluded to keep the GUI binary lean.
gui = Analysis(
    ["main.py"],
    pathex=["."],
    binaries=[],
    datas=[
        ("gui/styles/dark.qss", "gui/styles"),
        ("config.py",           "."),
        ("models.py",           "."),
        ("thresholds.py",       "."),
    ],
    hiddenimports=[
        "PyQt6.QtCore",
        "PyQt6.QtGui",
        "PyQt6.QtWidgets",
        "gui.panels.metrics",
        "gui.panels.graphs",
        "gui.panels.controls",
        "gui.ipc_client",
        "gui.main_window",
        "gui.tray",
        "gui.notifier",
        "gui.theme",
    ],
    excludes=["tests"],
)

# Daemon excludes PyQt6 entirely — it has no GUI.
# Fan control and power profiles go through kernel interfaces directly.
daemon = Analysis(
    ["daemon/daemon.py"],
    pathex=["."],
    binaries=[],
    datas=[
        ("config.py",     "."),
        ("models.py",     "."),
        ("thresholds.py", "."),
    ],
    hiddenimports=[
        "daemon.reader",
        "daemon.alerter",
        "daemon.commander",
        "daemon.ipc_server",
    ],
    excludes=["PyQt6", "tests"],
)

# Shared libraries (e.g. Python stdlib) are deduplicated into _internal/
# so the tarball is not bloated with two copies of the same files.
MERGE(
    (gui,    "omenfancontrol-gui",    "omenfancontrol-gui"),
    (daemon, "omenfancontrol-daemon", "omenfancontrol-daemon"),
)

gui_pyz = PYZ(gui.pure, gui.zipped_data, cipher=block_cipher)

gui_exe = EXE(
    gui_pyz,
    gui.scripts,
    [],
    exclude_binaries=True,
    name="omenfancontrol-gui",
    debug=False,
    strip=False,
    upx=True,
    console=False,
)

daemon_pyz = PYZ(daemon.pure, daemon.zipped_data, cipher=block_cipher)

daemon_exe = EXE(
    daemon_pyz,
    daemon.scripts,
    [],
    exclude_binaries=True,
    name="omenfancontrol-daemon",
    debug=False,
    strip=False,
    upx=True,
    console=True,
)

coll = COLLECT(
    gui_exe,
    gui.binaries,
    gui.zipfiles,
    gui.datas,
    daemon_exe,
    daemon.binaries,
    daemon.zipfiles,
    daemon.datas,
    strip=False,
    upx=True,
    name="omenfancontrol",
)