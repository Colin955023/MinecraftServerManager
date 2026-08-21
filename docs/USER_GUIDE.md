# 使用者手冊

## 取得程式

本程式為單一執行檔（Single Executable），免安裝即可使用。

1. 從 [GitHub Releases](https://github.com/Colin955023/MinecraftServerManager/releases) 下載最新的 `MinecraftServerManager.exe`。
2. 將 `.exe` 放置於您方便的任何位置（如桌面或專屬資料夾）。
3. 雙擊執行即可。

### 解除安裝

本程式不寫入 Windows Registry，也不產生系統解除安裝項目。若要徹底移除，請直接刪除 `.exe` 檔案，並刪除 `%LOCALAPPDATA%\Programs\MinecraftServerManager` 隱藏資料夾即可。

---

### Java 與 winget 安裝說明

本程式本身不內含 Java。建立或啟動伺服器時，程式會依 Minecraft 版本自動檢查需要的 Java 主版本，並偵測本機可用的 `javaw.exe`。若找不到合適版本，會跳出「**Java 未找到**」詢問視窗。

- 選擇 **是**：程式會嘗試使用 **winget** 自動安裝對應版本的 Java。
- 選擇 **否**：請自行從瀏覽器下載並安裝 JDK / JRE，之後回到程式中手動指定 Java 路徑。

選擇自動安裝（是）時，流程如下：

1. 程式會先顯示提示，說明接下來會在背景執行 `winget install`，並傳入自動同意來源與套件授權的參數。
2. Java 8 會安裝 Oracle JRE；其餘支援版本會安裝對應的 Microsoft OpenJDK 官方套件。
3. 安裝完成後，程式會重新掃描本機 Java，找到後即可直接使用。
4. 多數 Windows 10 / 11 環境可直接完成，但部分系統仍可能出現 UAC、Microsoft Store 或 winget 相關提示。

注意事項：

- 僅適用於已安裝 **winget** 的 Windows 10 / 11 環境
- 在程式中選擇「是」，代表同意由本程式代入授權接受參數
- 若你不想由程式自動處理授權，請選擇「否」並改用手動安裝

---

## 快速開始

### 第一步：設定資料夾

啟動程式後選擇「**伺服器主資料夾**」，程式會在其中自動建立 `servers/` 子資料夾來存放所有伺服器。

### 第二步：建立第一個伺服器

1. 前往「**建立伺服器**」頁面
2. 輸入名稱、選擇 Minecraft 版本
3. 選擇載入器：Vanilla／Fabric／Forge／Quilt／NeoForge
4. 設定記憶體用量
5. **JVM 參數設定**：點擊「JVM參數設定...」可查看並微調程式自動依據 Java 版本推薦的效能參數（Java 21+ 使用 ZGC；舊版使用 G1GC）。
6. 按下「**建立伺服器**」
7. 程式會彈出「**確認建立伺服器參數**」對話框，請仔細核對所有設定與完整啟動參數。確認無誤後點擊「**確認並建立**」，程式便會自動下載所需檔案並完成建立；若需修改可點擊「取消」。

### 第三步：啟動與監控

1. 前往「**管理伺服器**」，選擇伺服器後按「**啟動**」
2. 按「**監控**」開啟即時視窗，可查看控制台輸出、記憶體、運行時間與玩家資訊

---

## 模組管理

### 安裝新模組

1. 前往「**模組管理**」，確認目前選中的伺服器
2. 選擇任一方式：
   - **本地匯入**：直接選擇 `.jar` 檔案
   - **線上搜尋**：搜尋 Modrinth 後加入安裝清單，再至 Review 視窗確認
3. 線上安裝清單會在 Review 視窗確認後執行安裝

### 更新已安裝的模組

1. 在模組管理頁面按「**檢查更新**」
2. 於「**本地更新 Review**」查看建議版本與相依項目
3. 確認無誤後執行更新

### 識別不到模組資訊時

若某個 `.jar` 無法自動比對到 Modrinth 資料，程式會先嘗試依快取資料、檔名與其他線索自動補齊；大多數情況下不需要人工介入，只有在仍無法辨識時，才會在 Review 視窗提供手動補正入口，讓你輸入 `project id` 或 `slug` 後重新比對並執行更新。

---

## 支援範圍

**建立伺服器載入器**：Vanilla、Fabric、Forge、Quilt、NeoForge

程式目前支援直接建立和管理 Vanilla 伺服器，以及 Fabric、Forge、Quilt、NeoForge 載入器伺服器。各載入器使用各自的版本查詢與下載流程。

---

## 常見問題

### 介面太大或太小

請在 Windows「設定 > 系統 > 顯示器 > 縮放」調整顯示比例。程式使用 Qt Widgets，會跟隨系統顯示縮放，不需要在程式內另外設定 DPI 倍率。

### 程式無法啟動

- 確認防毒軟體未封鎖 `MinecraftServerManager.exe`
- 嘗試以系統管理員身分執行
- 請確認您的存放路徑不要包含過長的特殊字元，建議改用簡短英文路徑重新測試

### 伺服器無法啟動

- 開啟監控視窗查看錯誤訊息
- 確認 Java 版本與 Minecraft 版本相容（程式可引導下載對應版本）
- 依序停用最近安裝的模組，排除衝突

### 模組清單是空的

- 確認 `.jar` 檔案位於伺服器的 `mods/` 資料夾內
- 檔案副檔名需為 `.jar` 或 `.jar.disabled`
- 按「**重新整理**」手動刷新清單

## 資料位置

本程式的所有資料將統一儲存於系統的應用程式資料夾中：

- **設定檔**：`%LOCALAPPDATA%\Programs\MinecraftServerManager\user_settings.json`
- **日誌**：`%LOCALAPPDATA%\Programs\MinecraftServerManager\log\`
- **快取**：`%LOCALAPPDATA%\Programs\MinecraftServerManager\Cache\`

---

## 問題回報

前往 [GitHub Issues](https://github.com/Colin955023/MinecraftServerManager/issues) 回報，請附上：

1. Windows 版本（Win10 / Win11）
2. 程式版本（在標題列查看）
3. 重現步驟
4. 錯誤訊息截圖或日誌片段
