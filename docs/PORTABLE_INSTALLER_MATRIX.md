# 可攜式 / 一般安裝差異矩陣

本文件描述執行模式、資料路徑與自動更新流程的差異。實際行為以以下程式碼為準：

- `src/utils/runtime_utils/runtime_paths.py`：模式判定與資料路徑
- `src/utils/update_utils/update_parsing.py`：GitHub Release asset 選擇與 digest 解析
- `src/utils/update_utils/update_checker.py`：下載、驗證、套用更新與關閉流程

## 執行模式與資料路徑

| 項目 | 可攜式安裝 / Portable | 一般安裝 / Installer |
|---|---|---|
| 程式主目錄 | 使用者在 installer 指定的資料夾；搬移後可執行 | `%LOCALAPPDATA%\Programs\MinecraftServerManager` |
| 模式判定 | `<exe_dir>/.portable` 或 `<exe_dir>/.config` 存在時視為 portable | 不符合 portable 條件時採 installer 路徑 |
| 設定檔路徑 | `<exe_dir>/.config/user_settings.json` | `%LOCALAPPDATA%\Programs\MinecraftServerManager\user_settings.json` |
| 日誌路徑 | `<exe_dir>/.log/` | `%LOCALAPPDATA%\Programs\MinecraftServerManager\log\` |
| 快取路徑 | `<exe_dir>/.config/Cache/` | `%LOCALAPPDATA%\Programs\MinecraftServerManager\Cache\` |
| 目錄權限需求 | 程式目錄需允許建立、覆寫、刪除與備份檔案 | 應用程式需可寫入使用者資料、日誌與快取目錄；安裝程式本身的權限需求由 installer 決定 |
| 移除方式 | 不建立 Windows 解除安裝項目；關閉程式後直接刪除整個指定資料夾 | 透過 Windows 已安裝應用程式或 Inno uninstaller 解除安裝 |

## 更新資產與流程

| 項目 | Portable 流程 | Installer 流程 |
|---|---|---|
| 資產選擇 | 選擇 `.exe` asset；名稱含 `setup` 或 `installer` 時優先 | 同 portable |
| digest 規格 | 讀取 GitHub Release asset 的 `digest` 欄位，接受 GitHub 產出的 `sha256:<hex>` | 同 portable |
| 下載前安全檢查 | 缺少可解析 digest 時直接取消，且不下載安裝檔 | 同 portable |
| 下載後驗證 | 以 digest 指定的演算法驗證 exe 檔雜湊 | 同 portable |
| 套用方式 | 啟動驗證後的 installer，傳入 `/MSMPortable=1` 與 `/DIR=<exe_dir>` | 啟動驗證後的 installer，傳入 `/MSMPortable=0` |
| 使用者資料保留 | installer 不打包 `.portable`、`.config`、`.log` 或 `user_settings.json`；portable 資料留在 `<exe_dir>` 下，移除時由使用者刪除整個資料夾 | installer 不打包 `user_settings.json`、`log` 或 `Cache`；資料留在 `%LOCALAPPDATA%\Programs\MinecraftServerManager` |
| 自動回滾能力 | 更新器不覆寫既有程式；installer 的復原能力不在本文件範圍內 | 同 portable |
| 暫存清理 | 下載失敗或驗證失敗會清理暫存；installer 啟動後保留 exe 交由安裝流程使用 | 同 portable |

## 術語

- `Portable` 與 `Installer` 是執行模式與資料路徑策略；release 仍只提供同一個 installer exe。
- `digest` 指 GitHub Release asset metadata；`checksum` 或「雜湊」指本機下載後重新計算出的檔案雜湊。
- 本文件描述應用程式更新器行為，不描述 Inno Setup installer 內部的安裝、權限提升或回滾能力。
