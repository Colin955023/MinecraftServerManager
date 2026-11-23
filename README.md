# Minecraft 伺服器管理器

[![Platform](https://img.shields.io/badge/Windows-11-0078D4?logo=windows&logoColor=white)](https://www.microsoft.com/windows)
[![.NET](https://img.shields.io/badge/.NET-10-512BD4?logo=dotnet&logoColor=white)](https://dotnet.microsoft.com/)
[![WinUI 3](https://img.shields.io/badge/UI-WinUI%203-0078D4)](https://learn.microsoft.com/windows/apps/winui/winui3/)
[![License: GPLv3](https://img.shields.io/badge/License-GPLv3-blue)](LICENSE)
[![CI](https://github.com/Colin955023/MinecraftServerManager/actions/workflows/ci-test.yml/badge.svg)](https://github.com/Colin955023/MinecraftServerManager/actions/workflows/ci-test.yml)
[![CodeQL Analysis](https://github.com/Colin955023/MinecraftServerManager/actions/workflows/codeql.yml/badge.svg)](https://github.com/Colin955023/MinecraftServerManager/actions/workflows/codeql.yml)
[![OpenSSF Scorecard](https://api.scorecard.dev/projects/github.com/Colin955023/MinecraftServerManager/badge)](https://scorecard.dev/viewer/?uri=github.com/Colin955023/MinecraftServerManager)

Windows 11 的 Minecraft 伺服器管理工具，以 C#、.NET 10 與 WinUI 3 開發。系統需求見[使用手冊](docs/USER_GUIDE.md#系統需求)。

**[下載最新版 MinecraftServerManager.exe](https://github.com/Colin955023/MinecraftServerManager/releases/latest/download/MinecraftServerManager.exe)**（[所有版本與更新紀錄](https://github.com/Colin955023/MinecraftServerManager/releases)）

## 主要特色

- **建立與匯入**：Paper、Fabric、Quilt、Forge、NeoForge；可匯入既有伺服器，並自動配對 Java。
- **多伺服器**：可同時執行，各有監控視窗（紀錄、指令、線上玩家）。
- **備份與名單**：備份與還原、存放目錄遷移、OP／白名單／封鎖、`server.properties` 設定。
- **模組**：啟用／停用、Modrinth 搜尋與相依解析、更新檢查、清單匯出。
- **單一執行檔**：WinUI 3 原生介面，不需安裝。

## 使用方法

取得最新版 `MinecraftServerManager.exe` 後，按兩下即可啟動。

### 從原始碼建置

需要 Windows 11、.NET 10 SDK（版本見 global.json）、PowerShell 7（`pwsh`）。

```powershell
dotnet run --project src\MinecraftServerManager.App\MinecraftServerManager.App.csproj
pwsh -NoProfile -File scripts\dotnet_quality_gate.ps1
pwsh -NoProfile -File scripts\dotnet_publish.ps1
```

依序為：執行、品質門禁、發布。

## 說明文件

- [技術手冊](docs/TECHNICAL_OVERVIEW.md)
- [使用手冊](docs/USER_GUIDE.md)

## 授權條款

[GPL-3.0-only](LICENSE)（第三方元件聲明見 [COPYING.md](COPYING.md)）。
