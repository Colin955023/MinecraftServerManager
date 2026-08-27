# 使用者手冊

## 安裝與移除

從 [GitHub Releases](https://github.com/Colin955023/MinecraftServerManager/releases) 下載 `MinecraftServerManager.exe` 後直接執行，僅支援 Windows 10／11 64-bit。

程式免安裝且不建立解除安裝項目。移除時刪除 EXE；若也要清除設定、日誌與快取，再刪除 `%LOCALAPPDATA%\Programs\MinecraftServerManager`。

## Java

程式不內含 Java。建立或啟動伺服器時會依 Minecraft 版本偵測合適的 Java；找不到時可：

- 選「是」：以 winget 安裝 Oracle JRE 8 或對應 Microsoft OpenJDK，並接受來源與套件授權。
- 選「否」：自行安裝 JDK／JRE，再指定 Java 路徑。

自動安裝需要 winget，可能出現 UAC、Microsoft Store 或來源提示。

## 快速開始

1. 初次啟動時選擇「伺服器主資料夾」。程式會在其中建立 `servers/`，每台伺服器再使用自己的具名子資料夾。
2. 到「建立伺服器」輸入名稱、Minecraft 版本、載入器與記憶體。
3. 視需要調整 JVM 參數；Java 21+ 預設建議 ZGC，其餘支援版本使用 G1GC。
4. 按「建立伺服器」，核對已驗證的建立計畫後確認。
5. 到「管理伺服器」啟動；按「監控」查看控制台、記憶體、運作時間與玩家。

支援 Vanilla、Fabric、Forge、Quilt、NeoForge。

## 匯入與重新偵測

從主導航的「匯入伺服器」可匯入現有資料夾或 ZIP。程式會檢查伺服器內容、版本、載入器、EULA 與啟動目標，再建立受管登錄。

手動更換核心檔案或載入器後，使用「重新偵測」更新登錄資訊。

## 備份與還原

- 「備份地圖檔」會先完成暫存 ZIP，再原子提交；`logs`、`crash-reports`、`backups` 不納入備份。每台伺服器最多保留最新 10 份，建立新備份時會自動刪除更舊的備份。
- 還原採「快照替換」：備份內容會取代目前伺服器的一般檔案，因此**不在備份中的一般檔案會被移除**。`logs`、`crash-reports`、`backups` 與 `.git` 等備份排除目錄會保留目前版本；即使備份 ZIP 內含這些排除目錄，也不會覆寫目前內容。還原若在提交階段失敗，程式會嘗試回滾原伺服器目錄。
- 備份或還原前先停止伺服器，避免世界資料不一致。

## `server.properties`

「設定」開啟 `server.properties` 編輯器，提供分類編輯、數值驗證與預設值。儲存採 revision conflict 檢查與原子寫入；若檔案已被外部修改，請重新載入後再儲存。

## 模組管理

### 安裝與更新

1. 選擇非 Vanilla 伺服器。
2. 本地安裝按「匯入模組」選擇 JAR；線上安裝到「線上瀏覽」搜尋 Modrinth 並加入安裝清單。
3. 在 Review 核對版本、相容性、必要依賴、警告及實際選取項目後執行。
4. 已安裝模組可按「檢查更新」，在本地更新 Review 確認後更新。

### 本地操作

- 雙擊模組切換 `.jar`／`.jar.disabled`；可多選後使用批次切換。
- 右鍵可複製資訊、在檔案總管顯示或刪除。刪除無法復原。
- 「匯出模組清單」支援 XLSX、JSON、HTML、TXT。
- 本地模組的 Modrinth 身分會由檔名、metadata 與雜湊等證據解析；無法可靠辨識時，Review 會將該項目標示為不可執行或需要重新確認，不會自動套用未驗證的 project id／slug。

## 常見問題

### 程式無法啟動

- 確認防毒軟體未封鎖 EXE。
- 改用較短且不含特殊字元的路徑。
- 仍失敗時附上日誌回報；通常不需要以系統管理員身分執行。

### 伺服器無法啟動

- 從監控視窗讀取錯誤。
- 確認 Java 與 Minecraft 版本相容。
- 依序停用最近新增的模組排除衝突。

### 模組清單為空

- 確認 JAR 位於該伺服器的 `mods/`。
- 副檔名必須是 `.jar` 或 `.jar.disabled`。
- 按「重新整理」。

### 介面比例不合

到 Windows「設定 > 系統 > 顯示器 > 縮放」調整。介面由 Qt 6 跟隨系統 DPI。

## 資料位置

- 設定：`%LOCALAPPDATA%\Programs\MinecraftServerManager\user_settings.json`
- 日誌：`%LOCALAPPDATA%\Programs\MinecraftServerManager\Logs\`
- 快取：`%LOCALAPPDATA%\Programs\MinecraftServerManager\Cache\`

## 問題回報

到 [GitHub Issues](https://github.com/Colin955023/MinecraftServerManager/issues) 提供 Windows／程式版本、重現步驟及錯誤訊息。安全漏洞請依 [.github/SECURITY.md](../.github/SECURITY.md) 私下回報。
