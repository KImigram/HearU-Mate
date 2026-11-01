from pathlib import Path

from PyInstaller.utils.hooks import collect_all, copy_metadata


project_root = Path(SPECPATH).resolve().parent

datas = [
    (str(project_root / "assets"), "assets"),
    (str(project_root / "desktop" / "styles.qss"), "desktop"),
]
binaries = []
hiddenimports = [
    "soundcard.mediafoundation",
    "multiprocessing.popen_spawn_win32",
]

for package in ("sherpa_onnx", "soundcard"):
    package_datas, package_binaries, package_hidden = collect_all(package)
    datas += package_datas
    binaries += package_binaries
    hiddenimports += package_hidden

for distribution in (
    "sherpa-onnx",
    "SoundCard",
    "openai",
    "httpx",
    "httpcore",
):
    try:
        datas += copy_metadata(distribution)
    except Exception:
        pass

a = Analysis(
    [str(project_root / "packaging" / "entrypoint.py")],
    pathex=[str(project_root)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "matplotlib",
        "onnx",
        "pandas",
        "scipy",
        "tensorflow",
        "tkinter",
        "torch",
    ],
    noarchive=False,
    optimize=1,
)

# The Codex host PATH contains Poppler's ICU 78 DLLs. PyInstaller may resolve
# Qt6Core's generic `icuuc.dll` import to that incompatible copy and bundle it,
# which shadows the Windows ICU DLL and causes WinError 127 at startup.
incompatible_host_icu = {"icuuc.dll", "icudt78.dll"}
a.binaries = type(a.binaries)(
    item
    for item in a.binaries
    if Path(item[0]).name.lower() not in incompatible_host_icu
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="HearU Mate",
    icon=str(project_root / "assets" / "hearu_mate.ico"),
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

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="HearU Mate",
)
