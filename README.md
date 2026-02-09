#  Minecraft 伺服器管理器 (Minecraft Server Manager)

[![Platform](https://img.shields.io/badge/Platform-Windows-blue)](https://github.com/)
[![Python](https://img.shields.io/badge/Python-3.10%2B-green)](https://python.org)
[![License](https://img.shields.io/badge/License-GPLv3-blue)](LICENSE)
[![GUI](https://img.shields.io/badge/GUI-CustomTkinter-orange)](https://github.com/TomSchimansky/CustomTkinter)

**Minecraft 伺服器管理器** 是一款專為 Windows 平台設計的現代化伺服器管理工具。本專案旨在提供一個直觀、高效且功能強大的圖形化介面，讓使用者能夠輕鬆建立、配置與監控 Minecraft 伺服器。

本工具參考了 [PrismLauncher](https://github.com/PrismLauncher/PrismLauncher) 的模組管理體驗，並結合了自動化的 Java 環境配置與伺服器版本管理，為使用者帶來無縫的伺服器架設體驗。

##  系統支援

**本專案僅支援 Microsoft Windows 與 Windows Server 作業系統。** 不支援 macOS、Linux 或其他 Unix-like 系統。

##  核心特色

###  現代化使用者介面
- **CustomTkinter 框架**：採用現代化的 GUI 設計語言，提供流暢且美觀的操作體驗。
- **響應式佈局**：介面可自適應視窗大小，確保在不同解析度下均能完美呈現。
- **繁體中文支援**：全介面繁體中文在地化，降低使用門檻。

###  智慧型伺服器管理
- **多載入器支援**：完整支援 Vanilla (原版)、Fabric 與 Forge 等主流載入器。
- **自動化版本獲取**：即時同步 Minecraft 官方與載入器社群的最新版本資訊。
- **一鍵建立與部署**：簡化繁瑣的伺服器架設流程，僅需數次點擊即可完成部署。
- **偵測與匯入**：可掃描指定資料夾的既有伺服器，並將其設定、路徑與備份資訊納入管理。

###  智慧 Java 環境配置
- **自動偵測**：智慧掃描系統中已安裝的 Java 版本。
- **版本匹配**：根據 Minecraft 版本需求，自動選擇最合適的 Java 執行環境。
- **自動下載**：若系統中缺乏合適的 Java 版本，將自動從 Microsoft JDK 等可靠來源下載並配置。

###  專業模組管理
- **即時掃描**：快速讀取 mods 資料夾內容，即時反映檔案變動。
- **靈活切換**：支援雙擊啟用/停用模組 (.jar  .jar.disabled)，並提供批量操作功能。
- **直觀狀態顯示**：清晰標示模組啟用狀態，管理大量模組更輕鬆。

###  系統監控與維運
- **即時資源監控**：即時顯示伺服器記憶體與 CPU 使用率。
- **控制台整合**：內建伺服器控制台，支援即時日誌查看與指令發送。
- **自動更新檢查**：啟動時自動檢查 GitHub Releases，確保您使用的是最新版本。
- **多伺服器並行**：支援同時運行多個伺服器實例（需配置不同連接埠）。

##  文件索引

- [ 使用指南 (User Guide)](docs/USER_GUIDE.md)：詳細的操作說明與功能介紹。
- [ 技術概覽 (Technical Overview)](docs/TECHNICAL_OVERVIEW.md)：系統架構、技術堆疊與開發資訊。

##  快速開始

### 系統需求
- **作業系統**：Windows 10 或更新版本 (64-bit)
- **硬體需求**：建議至少 4GB RAM (視伺服器規模而定)

### 安裝與執行

#### 選項 1：可攜式版本（推薦新手）
最簡單的方式，無需安裝 Python 或任何依賴。

1. 從 [GitHub Releases](https://github.com/Colin955023/MinecraftServerManager/releases) 下載 `MinecraftServerManager-v*.*.* -portable.zip`
2. 解壓到任意位置
3. 雙擊執行 `MinecraftServerManager.exe`

> **可攜式自動更新說明**：程式會嘗試在啟動時或手動檢查更新時，優先尋找命名包含 `-portable.zip` 的 Release asset 並自動套用（若為可攜式安裝）。
4. 如需更新：請至 Release 頁面下載新的 portable ZIP，解壓覆蓋或替換現有資料夾（建議先備份資料夾內的 `.config` 與 `.log`）。

> 程式會在可攜式模式下優先使用 Release 中命名包含 `-portable.zip` 的檔案進行更新；若 Release 同時提供 checksum 檔案，程式會嘗試自動驗證下載檔案的完整性，若驗證失敗會中止更新並顯示錯誤訊息。

#### 選項 2：安裝版本（推薦日常使用）
包含自動更新、系統整合等功能。

1. 從 [GitHub Releases](https://github.com/Colin955023/MinecraftServerManager/releases) 下載 `MinecraftServerManager-v*.*.* -installer.exe`
2. 執行安裝程式並按照指示操作
3. 安裝完成後會自動啟動程式

#### 選項 3：開發環境
用於開發者或需要修改程式碼的情況。

**需求**：
- Python 3.10 或更新版本
- Git

**安裝步驟**：
```bash
# 1. 複製專案儲存庫
git clone https://github.com/Colin955023/MinecraftServerManager.git
cd MinecraftServerManager

# 2. 安裝 uv（允許使用 pip 安裝 uv 本體）
py -m pip install --user -U uv

# 3. 建立/同步專案環境（uv 會依 pyproject.toml + uv.lock 安裝依賴，並建立 .venv）
uv sync

# 4. 啟動應用程式
uv run python -m src.main
```

**查看已安裝的套件**：
```bash
uv pip list
uv pip freeze
uv tree
```

#### 選項 4：自行編譯執行檔
本專案提供自動化建置腳本，可將 Python 原始碼編譯為可攜式版本或安裝程式。

**需求**：
- Python 3.10 或更新版本
- Visual Studio C++ 編譯工具（需要預先安裝）

**編譯與打包步驟**：
```bash
# 1. 執行編譯腳本（生成可執行檔）
scripts/build_installer_nuitka.bat

# 2. 執行打包腳本（將便攜版打包成 ZIP，並包含更新工具）
scripts/package-portable.bat
```

編譯完成後，會在 `dist/` 資料夾中產生：
- `MinecraftServerManager-v*.*.* -portable.zip` - 便攜版 (用戶下載用)
- `installer/MinecraftServerManager-Setup-v*.*.* .exe` - 安裝版 (用戶下載用)
- `MinecraftServerManager/` - 未壓縮的便攜版資料夾 (開發用)

##  資料儲存位置

### 安裝版本
- 使用者設定檔：`%LOCALAPPDATA%\Programs\MinecraftServerManager\user_settings.json`
- 日誌檔案：`%LOCALAPPDATA%\Programs\MinecraftServerManager\log\`（自動管理，最多保留 10 個檔案）
- 伺服器資料夾：由使用者選擇「主資料夾」後，程式會在該資料夾內建立 `servers` 子資料夾並存放所有伺服器資料。
- 伺服器清單設定：同一個主資料夾下的 `servers_config.json` 會記錄每個伺服器的版本、載入器、路徑與備份設定。

### 可攜式版本
- 使用者設定檔：與程式同目錄下的 `.config/user_settings.json`
- 日誌檔案：與程式同目錄下的 `.log/` 資料夾
- 伺服器資料夾：由使用者選擇「主資料夾」後，程式會在該資料夾內建立 `servers` 子資料夾

> **提示**：可攜式版本可複製到 USB 隨身碟上使用，資料完全獨立不依賴系統位置。

##  貢獻與回饋
歡迎提交 Issue 或 Pull Request 來協助改進本專案。您的回饋是我們進步的動力。

##  授權條款
本專案採用 GNU GPLv3 授權條款，詳細內容請參閱 [LICENSE](LICENSE) 與 [COPYING.md](COPYING.md)。
