# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path

block_cipher = None

added_files = [
    ('downloader_app/ui/resources', 'downloader_app/ui/resources'),
    ('downloader_app/resources', 'downloader_app/resources'),
    ('resources', 'resources'),
    ('app-logo.png', '.'),
    ('app-logo.ico', '.'),
]

a = Analysis(
    ['downloader_app/main.py'],
    pathex=['.'],
    binaries=[],
    datas=added_files,
    hiddenimports=[
        'PyQt6',
        'PyQt6.QtCore',
        'PyQt6.QtGui',
        'PyQt6.QtWidgets',
        'PyQt6.QtSvg',
        'PyQt6.QtMultimedia',
        'PyQt6.QtMultimediaWidgets',
        'requests',
        'yt_dlp',
        'yt_dlp.extractor',
        'edge_tts',
        'imageio_ffmpeg',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
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
    name='ChkeaPikheat',
    icon=['app-logo.ico'],
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
