# 使用者手冊

## 安裝

| 類型 | 適合對象 | 取得方式 |
|------|----------|----------|
| **可攜版**（推薦） | 初次使用、不想安裝 | 下載 `*-portable.zip`，解壓後直接執行 |
| **安裝版** | 日常長期使用 | 下載 `*-installer.exe`，安裝後由開始功能表啟動 |

從 [GitHub Releases](https://github.com/Colin955023/MinecraftServerManager/releases) 下載最新版本。

---

## 快速開始

### 第一步：設定資料夾

啟動程式後選擇「**伺服器主資料夾**」，程式會在其中自動建立 `servers/` 子資料夾來存放所有伺服器。

### 第二步：建立第一台伺服器

1. 前往「**建立伺服器**」頁面
2. 輸入名稱、選擇 Minecraft 版本
3. 選擇載入器：Vanilla／Fabric／Forge
4. 設定記憶體用量
5. 按下「**建立**」，程式會自動下載所需檔案

### 第三步：啟動與監控

1. 前往「**管理伺服器**」，選擇伺服器後按「**啟動**」
2. 按「**監控**」開啟即時視窗，可查看控制台輸出、CPU 與記憶體用量

---

## 模組管理

### 安裝新模組

1. 前往「**模組管理**」，確認目前選中的伺服器
2. 選擇任一方式：
	- **本地匯入**：直接選擇 `.jar` 檔案
	- **線上搜尋**：搜尋 Modrinth 後加入安裝清單，再至 Review 視窗確認
3. 在 Review 視窗確認後執行安裝

### 更新已安裝的模組

1. 在模組管理頁面按「**檢查更新**」
2. 於「**本地更新 Review**」查看建議版本與相依項目
3. 確認無誤後執行更新

### 識別不到模組資訊時

若某個 `.jar` 無法自動比對到 Modrinth 資料，可在 Review 視窗手動輸入 `project id` 或 `slug`，重新比對後執行更新。

---

## 支援範圍

**伺服器載入器**：Vanilla、Fabric、Forge

**自動 Loader 相容（Prism Launcher 風格）**：

- **Quilt**：搜尋與相容分析時自動帶入 Fabric 模組，Quilt 相容模組皆可正常顯示
- **NeoForge 1.20.1**：自動相容 Forge 模組（binary 完全相容；僅限 1.20.1）
- Fabric 伺服器若有模組依賴 Quilt API／QSL，會自動重定向至 Fabric API

---

## 常見問題

### 程式無法啟動

- 確認防毒軟體未封鎖 `MinecraftServerManager.exe`
- 嘗試以系統管理員身分執行
- 若使用可攜版，確認解壓路徑不含中文或特殊字元

### 伺服器無法啟動

- 開啟監控視窗查看錯誤訊息
- 確認 Java 版本與 Minecraft 版本相容（程式可引導下載對應版本）
- 依序停用最近安裝的模組，排除衝突

### 模組清單是空的

- 確認 `.jar` 檔案位於伺服器的 `mods/` 資料夾內
- 檔案副檔名需為 `.jar` 或 `.jar.disabled`
- 按「**重新整理**」手動刷新清單

---

## 資料位置

| 模式 | 設定檔 | 日誌 |
|------|--------|------|
| 安裝版 | `%LOCALAPPDATA%\Programs\MinecraftServerManager\user_settings.json` | 同目錄 `log\` |
| 可攜版 | 程式目錄 `.config\user_settings.json` | 程式目錄 `.log\` |

---

## 問題回報

前往 [GitHub Issues](https://github.com/Colin955023/MinecraftServerManager/issues) 回報，請附上：

1. Windows 版本（Win10 / Win11）
2. 程式版本（在標題列查看）
3. 重現步驟
4. 錯誤訊息截圖或日誌片段
