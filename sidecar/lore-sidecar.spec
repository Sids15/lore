# PyInstaller spec for the Lore sidecar (one-folder build).
#
# Build:  pyinstaller lore-sidecar.spec
# Output: dist/lore-sidecar/lore-sidecar(.exe) + bundled libraries.
#
# The heavy native dependencies (lancedb, onnxruntime, fastembed, the tree-sitter
# grammar packages) ship compiled extensions and data files that PyInstaller's
# static analysis misses, so we collect them explicitly.

from PyInstaller.utils.hooks import (
    collect_all,
    collect_data_files,
    collect_dynamic_libs,
    collect_submodules,
)

datas = []
binaries = []
hiddenimports = []

# Packages with data files / dynamic libs / dynamic imports that need full collection.
for pkg in (
    "uvicorn",
    "fastapi",
    "pydantic",
    "pydantic_core",
    "lancedb",
    "onnxruntime",
    "fastembed",
    "tokenizers",
    "huggingface_hub",
):
    pkg_datas, pkg_binaries, pkg_hidden = collect_all(pkg)
    datas += pkg_datas
    binaries += pkg_binaries
    hiddenimports += pkg_hidden

# tree-sitter core + the compiled grammar packages (each ships a .pyd/.so).
hiddenimports += ["tree_sitter"]
for grammar in (
    "tree_sitter_python",
    "tree_sitter_javascript",
    "tree_sitter_typescript",
    "tree_sitter_rust",
):
    binaries += collect_dynamic_libs(grammar)
    datas += collect_data_files(grammar)
    hiddenimports.append(grammar)

# Our own app package, and uvicorn's dynamically-imported workers/protocols.
hiddenimports += collect_submodules("app")
hiddenimports += collect_submodules("uvicorn")


a = Analysis(
    ["run.py"],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["pytest", "tkinter"],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="lore-sidecar",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,  # no console window when launched by the Tauri shell
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="lore-sidecar",
)
