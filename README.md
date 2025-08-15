# 🎮 Minecraft 伺服器管理器

[![Platform](https://img.shields.io/badge/Platform-Windows-blue)](https://github.com/)
[![Python](https://img.shields.io/badge/Python-3.7%2B-green)](https://python.org)
[![License](https://img.shields.io/badge/License-GPL%20v3-blue)](LICENSE)
[![GUI](https://img.shields.io/badge/GUI-CustomTkinter-orange)](https://github.com/TomSchimansky/CustomTkinter)
[![Code Quality](https://img.shields.io/badge/Code%20Quality-優秀-green)](docs/CODE_REVIEW_AND_COMPLIANCE.md)

Minecraft 伺服器建立與管理工具，**參考 [PrismLauncher](https://github.com/PrismLauncher/PrismLauncher) 的模組管理體驗**。
採用現代化的 CustomTkinter 介面框架，提供專業且美觀的使用者體驗。

## 📖 目錄
- [現代化界面](#-現代化界面)
- [核心功能](#-核心功能)
- [快速開始](#-快速開始)
- [建置說明](#️-建置說明)
- [測試](#-測試)
- [疑難排解](#-疑難排解)
- [致謝](#-致謝)
- [授權](#-授權)

## 🎨 現代化界面
- ✨ 基於 CustomTkinter 的現代化 GUI 設計  
- 📱 響應式佈局設計

## ✨ 核心功能

### 🚦 智慧 Java 管理
- **自動偵測**：根據常見安裝路徑偵測本機所有 Java 版本
- **智慧選擇**：自動選擇最適合的 Java 版本（根據Minecraft官方json選擇）
- **自動下載**：若本機無合適版本，會自動下載 Microsoft JDK
- **多來源支持**：同時支援 Microsoft、Adoptium、Azul、Oracle JDK

### 🧩 模組管理（參考 Prism Launcher）
- **即時掃描**：即時掃描 mods 資料夾內容
- **快速切換**：雙擊啟用/停用（.jar ↔ .jar.disabled）
- **批量操作**：支援多選、批量啟用/停用
- **直觀介面**：清晰的模組狀態顯示

### 🖥️ 伺服器管理
- **多載入器支援**：Vanilla、Fabric、Forge
- **版本管理**：自動獲取最新版本資訊
- **資源監控**：即時記憶體使用率監控
- **指令介面**：內建伺服器指令發送功能
- **多伺服器**：支援多伺服器同時運行（需設定不同 server_port）
- **一鍵操作**：簡單的啟動/停止伺服器功能

### 🎨 使用者介面
- **現代化設計**：基於 CustomTkinter 的現代化 GUI
- **響應式佈局**：自適應視窗大小變化
- **繁體中文**：完整繁體中文介面
- **即時同步**：狀態資訊即時更新
- **分頁設計**：清晰的功能分類管理

## 🔍 進階功能

請參閱：
- [技術概覽](docs/TECHNICAL_OVERVIEW.md)
- [使用指南](docs/USER_GUIDE.md)

## 🚀 快速開始

### 💻 系統需求
- **作業系統**：Windows 10 或更新版本
- **Python 版本**：Python 3.7 或更新版本
- **硬碟空間**：至少 2GB 可用空間
- **記憶體**：建議 4GB 以上（執行伺服器時）
- **網路連線**：下載版本資訊、伺服器檔案與 Java 安裝檔
- **Java 環境**：無需手動安裝，程式會自動偵測/下載最適合的版本

### 📦 安裝與啟動

#### 直接執行（開發環境）
```bash
# 1. 複製或下載專案
git clone https://github.com/Colin955023/MinecraftServerManager.git
cd MinecraftServerManager

# 2. 安裝 Python 依賴
pip install -r requirements.txt

# 3. 啟動程式
python minecraft_server_manager.py
```

## 🏗️ 建置說明

### 建置可執行檔
```bash
# 執行自動化建置腳本
scripts/build.bat
```

建置腳本會自動完成以下步驟：
1. **環境檢查**：驗證 Python 和依賴套件安裝狀況
2. **依賴安裝**：自動安裝 PyInstaller 和專案依賴
3. **清理舊檔**：清除之前的建置檔案
4. **執行打包**：使用 PyInstaller 進行打包
5. **結果驗證**：檢查打包結果並顯示檔案資訊

### 建置輸出
- **位置**：`dist/MinecraftServerManager/`
- **主程式**：`MinecraftServerManager.exe`
- **依賴檔案**：所有必要的函式庫和資源檔案
- **可攜性**：整個資料夾可複製到其他 Windows 電腦使用

## 🧪 測試

### 快速功能測試
```bash
# 執行整合功能測試(需要有整個儲存庫src中的核心檔案)
quick_test.py
```

測試內容包括：
- ✅ **基礎模組導入測試**：驗證所有核心模組正常載入
- ✅ **介面初始化測試**：檢查 GUI 元件初始化狀況
- ✅ **Java 偵測測試**：測試 Java 版本偵測功能
- ✅ **網路連線測試**：驗證版本資訊下載功能
- ✅ **模組管理測試**：測試模組啟用/停用切換
- ✅ **設定檔讀寫測試**：檢查設定檔案操作功能

### 手動測試步驟
1. **執行測試腳本**：`scripts/quick_test.bat`
2. **查看測試結果**：確認所有項目顯示 ✅ 通過
3. **啟動主程式**：測試完成後可選擇啟動完整應用程式
4. **功能驗證**：建立測試伺服器驗證完整功能

## 🔧 疑難排解

### 常見問題

#### Python 環境問題
```bash
# 問題：找不到 Python
解決：確保已安裝 Python 3.7+ 並加入系統 PATH

# 問題：套件安裝失敗
解決：pip install --upgrade pip 升級 pip 後重試
```

#### Java 偵測問題
```bash
# 問題：Java 偵測失敗
解決：程式會自動下載 Microsoft JDK，確保網路連線正常

# 問題：Java 版本不相容
解決：程式會自動選擇最適合的 Java 版本，無需手動處理
```

#### 建置問題
```bash
# 問題：PyInstaller 打包失敗
解決：pip install --upgrade pyinstaller 升級後重試

# 問題：打包檔案過大
解決：正常現象，包含完整執行環境約 50-100MB
```

#### 執行時問題
```bash
# 問題：啟動緩慢
解決：首次啟動較慢屬正常現象，後續啟動會較快

# 問題：防毒軟體誤報
解決：將程式加入防毒軟體白名單
```

### 取得支援
- **GitHub Issues**：[提交問題回報](https://github.com/Colin955023/MinecraftServerManager/issues)
- **文檔參考**：查看 `docs/` 資料夾內的詳細文檔
- **版本確認**：確保使用最新版本以獲得最佳體驗


## 🎉 致謝

本專案模組管理功能設計參考了 [PrismLauncher](https://github.com/PrismLauncher/PrismLauncher) 及 [MinecraftModChecker](https://github.com/MrPlayerYork/MinecraftModChecker)。
感謝 PrismLauncher 團隊與 MinecraftModChecker 作者在模組管理、相容性檢查等領域的開源貢獻。

## 📄 授權

本專案使用 [GPL v3 授權](LICENSE)。
