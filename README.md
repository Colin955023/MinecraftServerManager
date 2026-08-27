# Minecraft 伺服器管理器

[![Platform](https://img.shields.io/badge/Windows-10%2F11-0078D4?logo=windows&logoColor=white)](https://www.microsoft.com/windows)
[![Python](https://img.shields.io/badge/Python-3.14-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![License: GPLv3](https://img.shields.io/badge/License-GPLv3-blue)](LICENSE)
[![CI](https://github.com/Colin955023/MinecraftServerManager/actions/workflows/ci-test.yml/badge.svg)](https://github.com/Colin955023/MinecraftServerManager/actions/workflows/ci-test.yml)
[![OpenSSF Scorecard](https://api.scorecard.dev/projects/github.com/Colin955023/MinecraftServerManager/badge)](https://scorecard.dev/viewer/?uri=github.com/Colin955023/MinecraftServerManager)
[![OpenSSF Best Practices](https://www.bestpractices.dev/projects/11917/badge)](https://www.bestpractices.dev/projects/11917)

Windows 10／11（64-bit）的 Minecraft 伺服器 GUI 管理工具，支援建立、匯入、啟停、監控、備份、`server.properties` 與 Modrinth 模組管理。

## 功能

- 建立 Vanilla、Fabric、Forge、Quilt、NeoForge 伺服器
- 自動偵測 Java；缺少時引導 winget 或手動安裝
- 集中管理伺服器狀態、控制台、玩家與記憶體
- 匯入資料夾或 ZIP，支援批次探索與重新偵測
- 原子建立備份；交易式快照還原與失敗回滾
- 視覺化編輯 `server.properties`
- 掃描本地模組、搜尋 Modrinth、規劃依賴及 Review 後安裝／更新
- 匯出模組清單為 XLSX、JSON、HTML 或純文字

## 使用

從 [Releases](https://github.com/Colin955023/MinecraftServerManager/releases) 下載 `MinecraftServerManager.exe` 後直接執行。程式不內含 Java；需要時會提示安裝符合 Minecraft 版本的 Java。

設定、日誌與快取位於 `%LOCALAPPDATA%\Programs\MinecraftServerManager`。完整操作請見 [使用者手冊](docs/USER_GUIDE.md)。

## 開發

需求：Windows、Python `>=3.14,<3.15`、[uv](https://docs.astral.sh/uv/)。

```bat
uv sync
uv run python -m src.main

uv sync --group test
uv run pytest -q

scripts\format_lint_check.bat
uv run report\comprehensive_report.py
```

## 結構

```text
src/core/    伺服器、載入器、模組與 Modrinth 業務邏輯
src/models/  跨模組共享的領域資料
src/ui/      主視窗、對話框、模組 Review 與監控
src/utils/   檔案、網路、Java、日誌、UI 與執行期工具
tests/       自動化測試
scripts/     建置與品質檢查
report/      綜合報告產生器
```

架構與開發規則請見 [技術手冊](docs/TECHNICAL_OVERVIEW.md) 及 [AGENTS.md](AGENTS.md)。

## 貢獻與授權

PR 請聚焦單一主題，提交前執行 `scripts\format_lint_check.bat`。授權條款見 [GPLv3](LICENSE) 與 [COPYING.md](COPYING.md)。
