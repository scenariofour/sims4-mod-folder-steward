from pathlib import Path
import sys

project_root = Path(SPECPATH).parent
data_files = [
    (str(project_root / "locales"), "s4mod/locales"),
    (str(project_root / "folder_profiles"), "s4mod/folder_profiles"),
    (str(project_root / "schemas"), "s4mod/schemas"),
]

analysis = Analysis(
    [str(project_root / "packaging" / "gui_entry.py")],
    pathex=[str(project_root / "src")],
    binaries=[],
    datas=data_files,
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets"],
    noarchive=False,
)
pyz = PYZ(analysis.pure)
executable = EXE(
    pyz,
    analysis.scripts,
    [],
    exclude_binaries=True,
    name="S4ModSteward",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
collected = COLLECT(
    executable,
    analysis.binaries,
    analysis.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="S4ModSteward",
)

if sys.platform == "darwin":
    application = BUNDLE(
        collected,
        name="S4ModSteward.app",
        icon=None,
        bundle_identifier="org.s4mod.steward",
        version="0.1.0",
        info_plist={"NSHighResolutionCapable": True},
    )
