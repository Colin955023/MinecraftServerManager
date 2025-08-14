#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
PyInstaller 打包配置檔案
用於將 Minecraft 伺服器管理器打包成 .exe 檔案和依賴資料夾結構
"""

# -*- mode: python ; coding: utf-8 -*-

import os
from pathlib import Path

# 取得專案根目錄
# 在 PyInstaller 環境中 __file__ 不可用，使用當前工作目錄
project_root = Path(os.getcwd())

block_cipher = None

a = Analysis(
    ['minecraft_server_manager.py'],  # 主程式入口點
    pathex=[str(project_root)],  # 添加專案根目錄到搜尋路徑
    binaries=[],
    datas=[
        # 包含必要的資料檔案和目錄
        ('src', 'src'),  # 完整包含 src 目錄
        ('assets', 'assets'),  # 包含 assets 資料夾（如果存在）
        ('README.md', '.'),  # 說明文件
        ('LICENSE', '.'),  # 授權檔案
        ('COPYING.md', '.'),  # 版權說明
        ('requirements.txt', '.'),  # 依賴清單
    ],
    hiddenimports=[
        # 標準函式庫 - 核心模組
        'tkinter',
        'tkinter.ttk',
        'tkinter.messagebox',
        'tkinter.filedialog',
        'tkinter.scrolledtext',
        'json',
        'os',
        'sys',
        'pathlib',
        'tempfile',
        'shutil',
        'subprocess',
        'threading',
        'queue',
        'time',
        'datetime',
        'traceback',
        'zipfile',
        'glob',
        'weakref',
        'webbrowser',
        'ctypes',
        'urllib.parse',
        'concurrent.futures',
        're',
        'enum',
        'contextlib',
        'importlib',
        # 第三方套件 - 網路和資料處理
        'requests',
        'urllib3',
        'lxml',
        'lxml.etree',
        'toml',
        'psutil',
        # 第三方套件 - GUI 框架
        'customtkinter',
        'darkdetect',
        # 可選依賴 (如果存在)
        'aiohttp',
        'packaging',
        'rich',
        # XML 處理
        'xml.etree.ElementTree',
        # 資料類型和工具
        'dataclasses',
        'typing',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # 排除不必要的模組以減少檔案大小
        'matplotlib',
        'numpy',
        'pandas',
        'scipy',
        'PIL',
        'pygame',
        'cv2',
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

# 過濾掉 None 值的 datas
a.datas = [data for data in a.datas if data is not None]

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,  # 重要：將二進位檔案分離到資料夾中
    name='MinecraftServerManager',
    debug=False,  # 設為 True 可啟用除錯模式
    bootloader_ignore_signals=False,
    strip=False,  # Windows 上通常設為 False
    upx=True,  # 啟用 UPX 壓縮以減少檔案大小
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,  # 隱藏控制台視窗，提供更好的使用者體驗
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='assets/icon.ico',
    version='assets/version_info.txt'
)

# 建立分散式打包結構（exe + 依賴資料夾）
coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='MinecraftServerManager'  # 輸出資料夾名稱
)
