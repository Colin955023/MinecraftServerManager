#  Minecraft 伺服器管理器 (Minecraft Server Manager)

[![Platform](https://img.shields.io/badge/Platform-Windows-blue)](https://github.com/)
[![Python](https://img.shields.io/badge/Python-3.9%2B-green)](https://python.org)
[![License](https://img.shields.io/badge/License-GPLv3-blue)](LICENSE)
[![GUI](https://img.shields.io/badge/GUI-CustomTkinter-orange)](https://github.com/TomSchimansky/CustomTkinter)

**Minecraft 伺服器管理器** 是一款專為 Windows 平台設計的現代化伺服器管理工具。本專案旨在提供一個直觀、高效且功能強大的圖形化介面，讓使用者能夠輕鬆建立、配置與監控 Minecraft 伺服器。

本工具參考了 [PrismLauncher](https://github.com/PrismLauncher/PrismLauncher) 的模組管理體驗，並結合了自動化的 Java 環境配置與伺服器版本管理，為使用者帶來無縫的伺服器架設體驗。

##  核心特色

###  現代化使用者介面
- **CustomTkinter 框架**：採用現代化的 GUI 設計語言，提供流暢且美觀的操作體驗。
- **響應式佈局**：介面可自適應視窗大小，確保在不同解析度下均能完美呈現。
- **繁體中文支援**：全介面繁體中文在地化，降低使用門檻。

###  智慧型伺服器管理
- **多載入器支援**：完整支援 Vanilla (原版)、Fabric 與 Forge 等主流載入器。
- **自動化版本獲取**：即時同步 Minecraft 官方與載入器社群的最新版本資訊。
- **一鍵建立與部署**：簡化繁瑣的伺服器架設流程，僅需數次點擊即可完成部署。

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
- **多伺服器並行**：支援同時運行多個伺服器實例（需配置不同連接埠）。

##  文件索引

- [ 使用指南 (User Guide)](docs/USER_GUIDE.md)：詳細的操作說明與功能介紹。
- [ 技術概覽 (Technical Overview)](docs/TECHNICAL_OVERVIEW.md)：系統架構、技術堆疊與開發資訊。
- [ 程式碼規範 (Code Compliance)](docs/CODE_REVIEW_AND_COMPLIANCE.md)：程式碼品質標準與審查報告。

##  快速開始

### 系統需求
- **作業系統**：Windows 10 或更新版本 (64-bit)
- **Python 版本**：Python 3.9 或更新版本
- **硬體需求**：建議至少 4GB RAM (視伺服器規模而定)

### 安裝與執行

#### 開發環境設置
```bash
# 1. 複製專案儲存庫
git clone https://github.com/Colin955023/MinecraftServerManager.git
cd MinecraftServerManager

# 2. 安裝 uv（允許使用 pip 安裝 uv 本體）
py -m pip install --user -U uv

# 3. 建立/同步專案環境（uv 會依 pyproject.toml + uv.lock 安裝依賴，並建立 .venv）
uv sync

# 4. 啟動應用程式（建議）
uv run python -m src.main
```

#### 查看目前環境安裝了哪些套件
```bash
uv pip list
uv pip freeze
uv tree
```

#### 建置執行檔
本專案提供自動化建置腳本，可將 Python 原始碼編譯為獨立執行檔。
```bash
# 執行建置腳本
scripts/build_installer_nuitka.bat
```

##  資料儲存位置

- 使用者設定檔：`%LOCALAPPDATA%\Programs\MinecraftServerManager\user_settings.json`
- 日誌檔案：`%LOCALAPPDATA%\Programs\MinecraftServerManager\log\`（自動管理，超過 10MB 時會刪除最舊的 10 筆日誌）
- 伺服器資料夾：由使用者選擇「主資料夾」後，程式會在該資料夾內建立 `servers` 子資料夾並存放所有伺服器資料。

##  貢獻與回饋
歡迎提交 Issue 或 Pull Request 來協助改進本專案。您的回饋是我們進步的動力。

##  授權條款
本專案採用 GNU GPLv3 授權條款，詳細內容請參閱 [LICENSE](LICENSE) 與 [COPYING.md](COPYING.md)。
