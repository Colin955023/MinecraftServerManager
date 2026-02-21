# Portable / Installer 差異矩陣

本表格描述兩種發佈模式在路徑、更新、權限與回滾行為上的差異。  
實際行為以 `src/utils/runtime_paths.py`、`src/utils/update_checker.py` 為準。

| 項目 | Portable | Installer |
|---|---|---|
| 程式主目錄 | `exe` 同層目錄（可搬移） | `%LOCALAPPDATA%\Programs\MinecraftServerManager` |
| 設定檔路徑 | `<exe_dir>/.config/user_settings.json` | `%LOCALAPPDATA%\Programs\MinecraftServerManager\user_settings.json` |
| 日誌路徑 | `<exe_dir>/.log/` | `%LOCALAPPDATA%\Programs\MinecraftServerManager\log\` |
| 快取路徑 | `<exe_dir>/.config/Cache/` | `%LOCALAPPDATA%\Programs\MinecraftServerManager\Cache\` |
| 模式判定 | `<exe_dir>/.portable` 或 `<exe_dir>/.config` 存在即視為 portable | 不符合 portable 條件時採 installer 模式 |
| 更新資產優先順序 | 1. `*portable*.zip` 2. 回退 `*.exe` | 1. `*.exe` |
| 更新流程 | 下載 zip -> 驗證 checksum -> 解壓到暫存 -> 備份原目錄與 `.config/.log` -> 關閉程式後由批次檔套用 | 下載 exe -> 驗證 checksum -> 啟動 installer -> 關閉主程式 |
| 權限需求 | 須對程式目錄有讀寫刪除權限（覆寫與備份） | 須可在安裝目錄寫入，且可啟動 installer |
| 回滾/回退行為 | 更新前建立完整備份，套用流程保留 `.config/.log`，若前置驗證失敗則不下載或不套用 | 若找不到 checksum 或驗證失敗，更新直接取消；不覆寫既有程式 |
| 失敗時安全策略 | checksum 或路徑安全檢查任一失敗即中止，清理暫存 | checksum 或下載失敗即中止，清理暫存 |

## 備註

- 「回退判定」指 portable 模式下找不到 portable zip 時，回退使用 installer asset。
- 兩種模式都採用相同的 checksum 驗證策略，且在驗證失敗時不會繼續套用更新。
