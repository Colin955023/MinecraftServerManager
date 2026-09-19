# Minecraft 伺服器管理器

[![Platform](https://img.shields.io/badge/Windows-10%2F11-0078D4?logo=windows&logoColor=white)](https://www.microsoft.com/windows)
[![.NET](https://img.shields.io/badge/.NET-10-512BD4?logo=dotnet&logoColor=white)](https://dotnet.microsoft.com/)
[![WPF](https://img.shields.io/badge/UI-WPF-512BD4)](https://learn.microsoft.com/dotnet/desktop/wpf/)
[![License: GPLv3](https://img.shields.io/badge/License-GPLv3-blue)](LICENSE)
[![CI](https://github.com/Colin955023/MinecraftServerManager/actions/workflows/ci-test.yml/badge.svg)](https://github.com/Colin955023/MinecraftServerManager/actions/workflows/ci-test.yml)

專為 Windows 10／11（64 位元）打造的 Minecraft 伺服器管理工具，採用 C#、.NET 10 與 WPF 技術建置，提供流暢操作體驗、高安全性邊界與極致啟動效能。

## 主要特色

- **載入器支援**：支援 Vanilla、Fabric、Quilt、Forge、NeoForge 官方核心之一鍵下載與伺服器建立
- **獨立即時監控**：獨立主控台視窗、50ms 批次聚合緩衝、ANSI 色碼清洗、在線玩家解析、指令發送與優雅停止
- **安全交易式還原**：備份還原具備暫存解壓、自動快照與失敗回復（Rollback）機制，自動保留最新 10 份備份
- **模組與 Modrinth 整合**：本地模組智慧啟用／停用、Modrinth 線上搜尋下載、雜湊完整性校驗與 4 種格式清單匯出
- **安全屬性編輯**：`server.properties` 設定調整內建樂觀鎖保護，防止檔案並行修改衝突
- **官方原生安全壓縮**：產出原生單一執行檔（Single-File EXE），無第三方加殼，杜絕防毒軟體誤判

## 使用方法

### 下載與執行

專案提供兩種單一可執行檔（Single-File EXE），可依您的環境需求選擇：

| 檔案名稱 | 版本類型 | 檔案大小 | 系統需求 | 特色與適用對象 |
| :--- | :--- | :--- | :--- | :--- |
| **`MinecraftServerManager-self-contained.exe`** | 獨立自包含版 | 約 62 MB | **無額外需求**（隨點即開） | **強烈推薦**，內建完整 .NET 10 Runtime 與所有依賴庫，開箱即用，絕不因缺少環境而報錯 |
| **`MinecraftServerManager-framework-dependent.exe`** | 框架相依版 | 約 1.6 MB | 需預先安裝 [.NET 10 Desktop Runtime](https://dotnet.microsoft.com/) | 體積極致精簡，適合系統已安裝 .NET 10 的進階使用者或偏好極小檔案下載者 |

> [!TIP]
> 如果您不確定電腦是否已安裝 .NET 10，請一律下載 **`MinecraftServerManager-self-contained.exe`** 即可順暢使用。

### 從原始碼開發與建置

需求環境：Windows 10／11、.NET 10 SDK、PowerShell 7（`pwsh`）。

#### 本機開發與執行
```bat
dotnet run --project src\MinecraftServerManager.App\MinecraftServerManager.App.csproj
```

#### 執行品質門禁（檢查、格式化、建置與全量測試）
```bat
pwsh -NoProfile -File scripts\dotnet_quality_gate.ps1
```

#### 發布單一執行檔
```bat
pwsh -NoProfile -File scripts\dotnet_publish.ps1 -Configuration Release
```

## 專案結構

```text
src/
├─ MinecraftServerManager.App/             WPF 視窗、View、ViewModel 與應用程式進入點
├─ MinecraftServerManager.Core/            工作流程、用例與服務合約
├─ MinecraftServerManager.Domain/          核心領域模型、值物件與業務規則
└─ MinecraftServerManager.Infrastructure/  檔案系統、HTTP、程序管理與 Java 整合
tests/
├─ MinecraftServerManager.UnitTests/       全量單元測試套件
└─ MinecraftServerManager.IntegrationTests/系統整合與流程測試套件
scripts/                                   自動化建置、發布與品質檢驗腳本
output/                                    發布建置成品輸出目錄
```

## 說明文件

- [技術手冊](docs/TECHNICAL_OVERVIEW.md)：架構分層、安全機制與實作技術細節
- [使用手冊](docs/USER_GUIDE.md)：詳細介面操作指南與常見問題排除

## 授權條款

本專案採用 GNU General Public License v3.0（GPLv3）授權，詳見 [LICENSE](LICENSE)。
