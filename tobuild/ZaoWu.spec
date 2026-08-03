# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for building the ZaoWu desktop application (onedir).

Run via tobuild/build.bat (or manually):

    cd D:\Git\ZaoWu
    .venv\Scripts\python -m PyInstaller tobuild\ZaoWu.spec --noconfirm --clean

Produces a one-folder Windows bundle in <repo>/dist/ZaoWu/:
  - ZaoWu.exe           (windowed entry point, pywebview shell)
  - _internal/          (Python runtime + bundled code/data)
    - ZaoWu/dist/       (frontend Vue build)
    - plugins/          (built-in plugins)
    - agent_modules/    (agent core + skills)
  - settings.json etc.  (NOT bundled: runtime data lives next to the exe,
                         located by zaowu_paths.get_project_root())
"""
import os
from PyInstaller.building.build_main import Analysis, PYZ, EXE, COLLECT
from PyInstaller.utils.hooks import collect_submodules, copy_metadata

# The spec lives in tobuild/; all source paths are relative to the repo root.
# NOTE: PyInstaller injects SPECPATH as the spec file's *directory*.
REPO_ROOT = os.path.abspath(os.path.join(SPECPATH, '..'))

# Collect every submodule for packages that are imported dynamically.
hiddenimports = (
    # PyWebView Windows backend and metadata helpers
    ['webview', 'webview.platforms.winforms', 'pkg_resources']
    + collect_submodules('routes')
    + collect_submodules('services')
    + collect_submodules('workflow_engine')
    + collect_submodules('plugin_system')
    + collect_submodules('agent_modules')
    + collect_submodules('pycrdt')
    + collect_submodules('pycrdt_websocket')
    + collect_submodules('pycrdt_store')
    + collect_submodules('hypercorn')
    + collect_submodules('quart')
    + collect_submodules('requests')
    + collect_submodules('git')
    + collect_submodules('yaml')
    + collect_submodules('aiosqlite')
    + collect_submodules('send2trash')
    + collect_submodules('y_py')
    + collect_submodules('httpx')
    + collect_submodules('charset_normalizer')
)

datas = [
    # Frontend build (must run `npm run build` in ZaoWu/ first)
    (os.path.join(REPO_ROOT, 'ZaoWu', 'dist'), 'ZaoWu/dist'),
    # Built-in plugins and agent skills are loaded at runtime from
    # _internal/ by zaowu_paths.get_*_dir() — must be bundled.
    (os.path.join(REPO_ROOT, 'plugins'), 'plugins'),
    (os.path.join(REPO_ROOT, 'agent_modules'), 'agent_modules'),
]

# Some packages read their distribution metadata at runtime.
datas += copy_metadata('quart')
datas += copy_metadata('hypercorn')
datas += copy_metadata('pywebview')
datas += copy_metadata('pycrdt')
datas += copy_metadata('pycrdt-websocket')
datas += copy_metadata('pycrdt-store')

a = Analysis(
    [os.path.join(REPO_ROOT, 'main.py')],
    pathex=[REPO_ROOT],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # tkinter is not used (UI runs in WebView2); hello_world plugin is a dev
    # sample and must not ship. Reducing both shrinks the bundle.
    excludes=['tkinter', 'plugins.hello_world'],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=None,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=None)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='ZaoWu',
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
    icon=os.path.join(REPO_ROOT, 'ZaoWu', 'public', 'favicon.ico'),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='ZaoWu',
)
