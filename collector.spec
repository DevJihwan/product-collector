# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec file for Musinsa/Naver SmartStore Collector
Build command: python -m PyInstaller --clean collector.spec
"""

import sys
from pathlib import Path

block_cipher = None

# Project root
PROJECT_ROOT = Path(SPECPATH)

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
    name='ProductCollector',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,  # GUI app - no console window
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,  # Add icon path if available: 'assets/icon.ico'
)
