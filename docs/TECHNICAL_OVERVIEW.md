
# 📊 Minecraft 伺服器管理器 - 技術概覽

本專案參考 [Prism Launcher](https://github.com/PrismLauncher/PrismLauncher) 與 [MinecraftModChecker](https://github.com/MrPlayerYork/MinecraftModChecker)。

## 🏗️ 技術架構 (最新版本)

### 專案檔案結構
```
專案根目錄/
├── minecraft_server_manager.py        # 🚀 主程式入口
├── build.spec                         # 📦 PyInstaller 打包設定
├── requirements.txt                   # 📋 依賴列表
├── quick_test.py                      # 🧪 快速功能測試
├── README.md                          # 📖 專案說明
├── src/                               # 📁 核心原始碼
│   ├── __init__.py                    # Python 套件初始化
│   ├── models.py                      # 📊 資料模型定義
│   ├── version_info.py                # ℹ️ 版本資訊
│   ├── core/                          # 🧠 核心邏輯
│   │   ├── __init__.py
│   │   ├── loader_manager.py          # 🔧 載入器管理 (Fabric/Forge/Vanilla)
│   │   ├── mod_manager.py             # 🧩 模組管理與狀態切換
│   │   ├── properties_helper.py       # ⚙️ server.properties 處理
│   │   ├── server_detection.py        # 🔍 伺服器自動偵測
│   │   ├── server_manager.py          # 🖥️ 伺服器生命週期管理
│   │   └── version_manager.py         # 📝 Minecraft 版本管理
│   ├── ui/                            # 🎨 使用者介面
│   │   ├── __init__.py
│   │   ├── main_window.py               # 🏠 主視窗與導航
│   │   ├── create_server_frame.py       # ➕ 伺服器建立介面
│   │   ├── manage_server_frame.py       # 🛠️ 伺服器管理介面
│   │   ├── mod_management.py            # 🧩 模組管理介面
│   │   ├── custom_dropdown.py           # 📋 自訂下拉選單
│   │   ├── server_monitor_window.py     # 📊 伺服器監控視窗
│   │   ├── server_properties_dialog.py  # ⚙️ 屬性設定對話框
│   │   └── window_preferences_dialog.py # 🎛️ 偏好設定對話框
│   └── utils/                       # 🔧 工具函式庫
│       ├── __init__.py
│       ├── app_restart.py           # 🔄 應用程式重啟
│       ├── font_manager.py          # 🔤 字體與DPI管理
│       ├── http_utils.py            # 🌐 HTTP請求工具
│       ├── java_downloader.py       # ☕ Java 自動下載
│       ├── java_utils.py            # ☕ Java 環境管理
│       ├── log_utils.py             # 📝 日誌處理工具
│       ├── memory_utils.py          # 💾 記憶體計算工具
│       ├── runtime_paths.py         # 📂 執行時路徑管理
│       ├── server_utils.py          # 🖥️ 伺服器操作工具
│       ├── settings_manager.py      # ⚙️ 設定檔管理
│       ├── ui_utils.py              # 🎨 統一介面工具
│       ├── update_checker.py        # 🔄 更新檢查
│       └── window_manager.py        # 🪟 視窗管理工具
├── docs/                            # 📚 說明文件
│   ├── CODE_REVIEW_AND_COMPLIANCE.md  # 📋 程式碼審查報告
│   ├── CODE_SECURITY_ANALYSIS.md      # 🔒 安全性分析報告
│   ├── PLAGIARISM_DETECTION_TOOLS.md  # 🔍 抄襲檢測工具
│   ├── TECHNICAL_OVERVIEW.md          # 📊 技術概覽
│   └── USER_GUIDE.md                  # 👤 使用指南
├── scripts/                         # 📜 建置腳本
│   ├── build.bat                    # 🔨 建置可執行檔
│   ├── build_installer.bat          # 📦 建置安裝包
│   ├── cleanup.bat                  # 🧹 清理腳本
│   └── installer.iss                # 🏗️ Inno Setup 安裝腳本
└── assets/                          # 🎨 資源檔案
    ├── icon.ico                     # 🖼️ 應用程式圖示
    └── version_info.txt             # ℹ️ 版本資訊檔案
```

## 🔧 技術棧與依賴

### 核心技術
- **Python 3.7+**: 主要開發語言
- **CustomTkinter**: 現代化GUI框架
- **PyInstaller**: 可執行檔打包工具

### 第三方函式庫
```python
# 網路與HTTP處理
requests >= 2.31.0          # HTTP請求處理
urllib3 >= 2.0.0            # 底層HTTP工具
aiohttp >= 3.9.0            # 異步HTTP支援

# 系統與處理
psutil >= 5.9.0             # 系統資源監控
packaging >= 23.2           # 版本號處理

# 資料處理與解析
lxml >= 6.0.0               # XML解析 (載入器元數據)
toml >= 0.10.2              # TOML配置檔案

# 使用者介面
customtkinter >= 5.2.0      # 現代GUI框架
rich >= 13.7.0              # 豐富的終端輸出

# 開發與建置
pyinstaller >= 6.0.0       # 可執行檔打包
```

### 系統需求
- **作業系統**: Windows 10/11 (64位元)
- **Python版本**: 3.7 - 3.13
- **記憶體**: 最少 2GB RAM (建議 4GB+)
- **磁碟空間**: 最少 1GB 可用空間
- **網路**: 寬頻網際網路連線

## 📋 主要功能

### 🧩 模組管理
- 即時掃描 mods 資料夾
- 雙擊啟用/停用（.jar ↔ .jar.disabled）
- 多選、批量操作

### 🖥️ 伺服器管理
- 支援 Vanilla、Fabric、Forge
- 自動獲取版本資訊
- 即時資源監控
- 命令控制發送
- 啟動/停止伺服器
- 多伺服器同時運行

## 🎨 設計理念
- 參考 Prism Launcher，強調簡潔、即時、批量、智能
- 參考 MinecraftModChecker：報告產生
- 現代分頁介面、全繁體中文、狀態同步

## 🔗 API 整合
- Modrinth API：取得模組資訊
- Mojang/載入器 API：獲取官方/載入器版本、自動更新

## 📝 備註
- 未來可擴充：模組下載、相容/依賴性檢查、模組更新、伺服器更新
