# Minecraft 伺服器管理器

[![Platform](https://img.shields.io/badge/Windows-11-0078D4?logo=windows&logoColor=white)](https://www.microsoft.com/windows)
[![.NET](https://img.shields.io/badge/.NET-10-512BD4?logo=dotnet&logoColor=white)](https://dotnet.microsoft.com/)
[![WinUI 3](https://img.shields.io/badge/UI-WinUI%203-0078D4)](https://learn.microsoft.com/windows/apps/winui/winui3/)
[![License: GPLv3](https://img.shields.io/badge/License-GPLv3-blue)](LICENSE)
[![CI](https://github.com/Colin955023/MinecraftServerManager/actions/workflows/ci-test.yml/badge.svg)](https://github.com/Colin955023/MinecraftServerManager/actions/workflows/ci-test.yml)
[![CodeQL Analysis (C#)](https://github.com/Colin955023/MinecraftServerManager/actions/workflows/codeql.yml/badge.svg)](https://github.com/Colin955023/MinecraftServerManager/actions/workflows/codeql.yml)
[![OpenSSF Scorecard](https://api.scorecard.dev/projects/github.com/Colin955023/MinecraftServerManager/badge)](https://scorecard.dev/viewer/?uri=github.com/Colin955023/MinecraftServerManager)

Windows 11（21H2 以上，64 位元）的 Minecraft 伺服器管理工具，以 C#、.NET 10 與 WinUI 3 開發。

**[下載最新版 MinecraftServerManager.exe](https://github.com/Colin955023/MinecraftServerManager/releases/latest/download/MinecraftServerManager.exe)**（[所有版本與更新紀錄](https://github.com/Colin955023/MinecraftServerManager/releases)）

## 主要特色

- **建立與匯入**：支援 Paper、Fabric、Quilt、Forge、NeoForge 建立與 Vanilla 等既有伺服器匯入（複製或遷移），依官方版本動態配對與安裝 Java（8～21+）。
- **多伺服器執行與監控**：各伺服器獨立監控視窗（即時紀錄、指令、線上玩家）、啟動前連接埠衝突檢查、平順停止與遺留行程偵測。
- **交易式備份、遷移與名單**：備份自動保留最新份數、失敗自動回復的交易式還原、存放根目錄安全遷移，以及 OP／白名單／封鎖與 `server.properties` 驗證。
- **模組管理**：本機啟用／停用、Modrinth 搜尋與相依自動解析、官方 CDN 與雜湊驗證、FlexVersion 更新檢查，並支援匯出 XLSX／HTML／JSON／TXT。
- **原生單一執行檔**：WinUI 3 原生介面（跟隨系統深淺色與強調色），單檔自包含發布，無第三方加殼。

## 使用方法

下載[最新版 `MinecraftServerManager.exe`](https://github.com/Colin955023/MinecraftServerManager/releases/latest/download/MinecraftServerManager.exe)（約 31 MB，自包含，不需另裝 .NET 或 Windows App SDK），按兩下即可啟動。

### 從原始碼建置

需要 Windows 11、.NET 10 SDK、PowerShell 7（`pwsh`）。

```bat
dotnet run --project src\MinecraftServerManager.App\MinecraftServerManager.App.csproj
pwsh -NoProfile -File scripts\dotnet_quality_gate.ps1
pwsh -NoProfile -File scripts\dotnet_publish.ps1
```

依序為：執行、品質門禁（格式、建置、全量測試）、發布單一執行檔。

## 說明文件

- [技術手冊](docs/TECHNICAL_OVERVIEW.md)：專案分層（`App`、`Core`、`Domain`、`Infrastructure`）、安全機制與實作細節
- [使用手冊](docs/USER_GUIDE.md)：操作指南與常見問題

## 授權條款

[GPL-3.0-only](LICENSE)（第三方元件聲明見 [COPYING.md](COPYING.md)）。
