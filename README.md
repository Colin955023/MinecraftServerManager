# Minecraft 伺服器管理器

[![Platform](https://img.shields.io/badge/Windows-10%2F11-0078D4?logo=windows&logoColor=white)](https://www.microsoft.com/windows)
[![Python](https://img.shields.io/badge/Python-3.14%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![License: GPLv3](https://img.shields.io/badge/License-GPLv3-blue)](LICENSE)
[![CI](https://github.com/Colin955023/MinecraftServerManager/actions/workflows/ci-test.yml/badge.svg)](https://github.com/Colin955023/MinecraftServerManager/actions/workflows/ci-test.yml)
[![OpenSSF Scorecard](https://api.securityscorecards.dev/projects/github.com/Colin955023/MinecraftServerManager/badge)](https://securityscorecards.dev/viewer/?uri=github.com/Colin955023/MinecraftServerManager)

Windows 上的 Minecraft 伺服器 GUI 管理工具。從建立伺服器、啟動監控到模組安裝更新，全程在圖形介面內完成，模組操作均附帶可審查的 Review 步驟。

> **僅支援 Windows 10 / 11（64-bit）**

---

## 功能特色

- **建立伺服器** — Vanilla／Fabric／Forge 精靈式設定流程
- **Java 管理** — 自動偵測已安裝 Java，缺少時可引導 winget 或手動安裝
- **即時監控** — 控制台輸出、記憶體、運行狀態與玩家資訊集中顯示
- **模組管理** — 本地掃描 + Modrinth 線上搜尋，安裝前 Review 確認
- **模組更新** — Hash-first 批次比對，相依套件自動規劃
- **Modrinth 相容策略** — 搜尋與更新建議時支援 Quilt → Fabric、NeoForge 1.20.1 → Forge alias
- **匯入伺服器** — 掃描既有資料夾或壓縮檔快速匯入
- **兩種發佈格式** — 可攜版（免安裝）與安裝版

---

## 安裝

**可攜版（推薦初次使用）**

1. 前往 [Releases](https://github.com/Colin955023/MinecraftServerManager/releases) 下載最新的 `*-portable.zip`
2. 解壓縮至任意資料夾
3. 執行 `MinecraftServerManager.exe`

**安裝版**

1. 下載最新的 `*-installer.exe`
2. 執行安裝程式，完成後由開始功能表啟動

---

## Java 與 winget（選用）

本程式不內含 Java。建立或啟動伺服器時，程式會自動偵測對應版本的 Java。

- **自動安裝**：在背景使用 `winget` 安裝對應版本的 Oracle JRE 8 或 Microsoft OpenJDK，並自動同意來源與套件授權
- **手動安裝**：自行下載 JDK / JRE，之後回到程式中指定 Java 路徑

多數 Windows 10 / 11 環境可直接完成 winget 安裝，但部分系統仍可能出現額外的系統提示。

詳細流程與注意事項請見 [使用者手冊](docs/USER_GUIDE.md)。

---

## 開發環境

**需求：** Python 3.10+、[uv](https://github.com/astral-sh/uv)

```bash
git clone https://github.com/Colin955023/MinecraftServerManager.git
cd MinecraftServerManager
py -m pip install --user -U uv
uv sync
uv run python -m src.main
```

**品質檢查：**

```bash
# 快速 test
uv run quick_test.py

# 格式、型別、測試檢查
scripts/format_lint_check.bat

# 產生綜合報告
uv run report\comprehensive_report.py
```

---

## 專案結構

```
src/
  core/      核心邏輯（版本管理、伺服器控制、模組服務）
  ui/        主視窗、功能頁、對話框
  utils/     共用基礎設施（設定、HTTP、日誌、視窗管理）
  models/    資料模型
docs/        文件
tests/       自動化測試
scripts/     建置與品質腳本
reports/     產生的品質報告
```

---

## 文件

- [使用者手冊](docs/USER_GUIDE.md)
- [技術手冊](docs/TECHNICAL_OVERVIEW.md)
- [Portable / Installer 差異矩陣](docs/PORTABLE_INSTALLER_MATRIX.md)

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
