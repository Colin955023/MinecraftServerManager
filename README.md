# Minecraft 伺服器管理器

[![Platform](https://img.shields.io/badge/Windows-10%2F11-0078D4?logo=windows&logoColor=white)](https://www.microsoft.com/windows)
[![Python](https://img.shields.io/badge/Python-3.14%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![License: GPLv3](https://img.shields.io/badge/License-GPLv3-blue)](LICENSE)
[![CI](https://github.com/Colin955023/MinecraftServerManager/actions/workflows/ci-test.yml/badge.svg)](https://github.com/Colin955023/MinecraftServerManager/actions/workflows/ci-test.yml)
[![OpenSSF Scorecard](https://api.securityscorecards.dev/projects/github.com/Colin955023/MinecraftServerManager/badge)](https://securityscorecards.dev/viewer/?uri=github.com/Colin955023/MinecraftServerManager)

Windows 上的 Minecraft 伺服器 GUI 管理工具。從建立伺服器、啟動監控到模組安裝更新，主要流程都可在圖形介面內完成；線上模組安裝與本地更新提供可審查的 Review 步驟。

> **僅支援 Windows 10 / 11（64-bit）**
> 介面使用 PySide6 + QFluentWidgets (Fluent Design)，顯示縮放跟隨 Windows 與 Qt 高 DPI 行為。

---

## 功能特色

- **建立伺服器** — Vanilla／Fabric／Forge／Quilt／NeoForge 精靈式設定流程
- **JVM 參數最佳化** — 支援 Java 21+ ZGC 及 Java 8/16/17 G1GC 的自動最佳化與視覺化設定
- **Java 管理** — 自動偵測已安裝 Java，缺少時可引導 winget 或手動安裝
- **即時監控** — 控制台輸出、記憶體、運作狀態與玩家資訊集中顯示
- **模組管理** — 本地掃描 + Modrinth 線上搜尋，線上安裝前 Review 確認
- **模組更新** — Hash-first 批次比對，相依套件自動規劃
- **匯入伺服器** — 掃描既有資料夾或壓縮檔快速匯入
- **單一執行檔** — 免安裝、無相依，下載後直接點擊即可執行
---

## 取得程式

本程式為單一執行檔（Single Executable），免安裝即可使用。

1. 前往 [Releases](https://github.com/Colin955023/MinecraftServerManager/releases) 下載最新的 `MinecraftServerManager.exe`
2. 將 `.exe` 放置於您方便的任何位置（如桌面或專屬資料夾）
3. 雙擊執行即可

所有設定、日誌與快取等資料將統一儲存於 `%LOCALAPPDATA%\Programs\MinecraftServerManager`。若要徹底移除程式，只需刪除 `.exe` 檔案以及上述資料夾即可。

---

## Java 與 winget（選用）

本程式不內含 Java。建立或啟動伺服器時，程式會自動偵測對應版本的 Java。

- **自動安裝**：在背景使用 `winget` 安裝對應版本的 Oracle JRE 8 或 Microsoft OpenJDK，並自動同意來源與套件授權
- **手動安裝**：自行下載 JDK / JRE，之後回到程式中指定 Java 路徑

多數 Windows 10 / 11 環境可直接完成 winget 安裝，但部分系統仍可能出現額外的系統提示。

詳細流程與注意事項請見 [使用者手冊](docs/USER_GUIDE.md)。

---

## 開發環境

**需求：** Python 3.14、[uv](https://github.com/astral-sh/uv)

```bash
git clone https://github.com/Colin955023/MinecraftServerManager.git
cd MinecraftServerManager
py -m pip install --user -U uv
uv sync
uv run python -m src.main
```

**品質檢查：**

```bash
# 測試（先同步測試套件）
uv sync --group test
uv run pytest -q

# 格式、型別、測試檢查
scripts/format_lint_check.bat

# 產生綜合報告
uv run report\comprehensive_report.py
```

---

## 專案結構

```
src/
  core/      核心邏輯（CreateServerJourney、ServerInstance、模組協調、Modrinth）
  models/    資料模型
  ui/        主視窗、分頁、對話框、模組 Session/ops、監控與 UIWorkScope 協調
  utils/     基礎設施（設定、HTTP、日誌、UIWorkScope、Java、更新檢查）
docs/        使用者手冊、技術手冊
tests/       自動化測試
scripts/     建置與品質腳本
report/      綜合報告腳本與輸出
```

---

## 文件

- [使用者手冊](docs/USER_GUIDE.md)
- [技術手冊](docs/TECHNICAL_OVERVIEW.md)

---

## 貢獻方式

歡迎提交 Issue 或 Pull Request。

- 每個 PR 聚焦於單一主題
- 提交前執行 `scripts/format_lint_check.bat`
- UI 行為變更請附上重現步驟與預期結果

---

## 授權

[GNU General Public License v3.0](LICENSE)
- [COPYING.md](COPYING.md)
