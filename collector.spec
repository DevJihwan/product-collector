# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec file for Musinsa/Naver SmartStore Collector
Build command: python -m PyInstaller --clean collector.spec
"""

import sys
import re
from pathlib import Path

block_cipher = None

# Project root
PROJECT_ROOT = Path(SPECPATH)

# 버전 정보 읽기 (정규식으로 텍스트 파싱 → 부작용 없음)
_config_text = (PROJECT_ROOT / "config.py").read_text(encoding="utf-8")
APP_VERSION = re.search(r'^APP_VERSION\s*=\s*["\'](.+?)["\']', _config_text, re.MULTILINE).group(1)

a = Analysis(
    ['app.py'],
    pathex=[str(PROJECT_ROOT)],
    binaries=[],
    datas=[
        # Include data files
        ('data/color_mapping.json', 'data'),
    ],
    hiddenimports=[
        # CustomTkinter
        'customtkinter',
        'PIL',
        'PIL._tkinter_finder',
        # Playwright
        'playwright',
        'playwright.sync_api',
        'playwright.async_api',
        # aiohttp
        'aiohttp',
        'asyncio',
        # openpyxl
        'openpyxl',
        'openpyxl.styles',
        'openpyxl.utils',
        # Project modules
        'collectors',
        'collectors.base',
        'collectors.musinsa',
        'collectors.naver',
        'exporters',
        'exporters.excel',
        'utils',
        'utils.logger',
        'utils.color_mapping',
        'config',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # Exclude unnecessary modules to reduce size
        'matplotlib',
        'numpy',
        'pandas',
        'scipy',
        'torch',
        'tensorflow',
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name=f'ProductCollector_v{APP_VERSION}',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[
        # MSVC++ 런타임 DLL은 UPX 압축 시 손상되므로 제외
        'vcruntime140.dll',
        'vcruntime140_1.dll',
        'msvcp140.dll',
        'msvcp140_1.dll',
        'msvcp140_2.dll',
        'ucrtbase.dll',
        'api-ms-win-*.dll',
    ],
    runtime_tmpdir=None,
    console=False,  # GUI app - no console window
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,  # Add icon path if available: 'assets/icon.ico'
)
