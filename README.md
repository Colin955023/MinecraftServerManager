# Minecraft 伺服器管理器

[![Platform](https://img.shields.io/badge/Windows-10%2F11-0078D4?logo=windows&logoColor=white)](https://www.microsoft.com/windows)
[![.NET](https://img.shields.io/badge/.NET-10-512BD4?logo=dotnet&logoColor=white)](https://dotnet.microsoft.com/)
[![WPF](https://img.shields.io/badge/UI-WPF-512BD4)](https://learn.microsoft.com/dotnet/desktop/wpf/)
[![License: GPLv3](https://img.shields.io/badge/License-GPLv3-blue)](LICENSE)
[![CI](https://github.com/Colin955023/MinecraftServerManager/actions/workflows/ci-test.yml/badge.svg)](https://github.com/Colin955023/MinecraftServerManager/actions/workflows/ci-test.yml)
[![CodeQL Analysis (C#)](https://github.com/Colin955023/MinecraftServerManager/actions/workflows/codeql.yml/badge.svg)](https://github.com/Colin955023/MinecraftServerManager/actions/workflows/codeql.yml)
[![OpenSSF Scorecard](https://api.scorecard.dev/projects/github.com/Colin955023/MinecraftServerManager/badge)](https://scorecard.dev/viewer/?uri=github.com/Colin955023/MinecraftServerManager)

專為 Windows 10／11（64 位元）打造的 Minecraft 伺服器管理工具，採用 C#、.NET 10 與 WPF 原生技術開發，提供流暢的操作體驗、安全的檔案防護與快速的啟動速度。

## 主要特色

- **核心與載入器**：支援 Paper、Vanilla、Fabric、Quilt、Forge、NeoForge 等官方核心之快速下載與建立
- **Java 管理與配對**：依照 Minecraft 官方版本需求自動配對，支援 Windows winget 自動安裝 Java（Java 8 到 21+）與自訂路徑，具備跳板轉發器去重機制
- **即時監控視窗**：獨立主控台、開機就緒 Windows 桌面通知、方向鍵瀏覽歷史指令、線上玩家清單、指令傳送與安全關閉流程
- **玩家名冊與權限管理**：視覺化管理營運管理員名單（OP 1～4 級權限與略過人數限制）、白名單及封鎖名冊（玩家與 IP），支援離線玩家快取
- **安全備份與還原**：還原時自動保留現場最新記錄檔與當機報告，具備失敗自動回復機制，自動保留最新 10 份備份
- **模組管理**：支援 Windows 自然排序、模組啟用與停用、自動下載相依模組、Modrinth 線上搜尋與安裝、官方下載來源驗證，以及匯出試算表（XLSX）、HTML、JSON 與純文字
- **伺服器設定驗證**：編輯 `server.properties` 時自動檢查連接埠（1～65534）與 IP 等數值正確性，避免設定錯誤
- **單一執行檔發行**：產出原生單一執行檔（EXE），不使用加殼工具，避免防毒軟體誤判

## 使用方法

### 下載與執行

專案提供兩種單一可執行檔（Single-File EXE），可依您的環境需求選擇：

| 檔案名稱 | 版本類型 | 檔案大小 | 系統需求 | 特色與適用對象 |
| :--- | :--- | :--- | :--- | :--- |
| **`MinecraftServerManager-self-contained.exe`** | 獨立自包含版 | 約 60 MB | **無額外需求**（隨點即開） | **強烈推薦**，內建完整 .NET 10 執行環境與官方原生單檔壓縮，開箱即用，具備最高相容性與穩定度，絕不因缺少環境而報錯 |
| **`MinecraftServerManager-framework-dependent.exe`** | 框架相依版 | 約 1.8 MB | 需預先安裝 [.NET 10 Desktop Runtime](https://dotnet.microsoft.com/) | 體積極致精簡，適合系統已安裝 .NET 10 的進階使用者或偏好極小檔案下載者 |

> [!TIP]
> 如果您不確定電腦是否已安裝 .NET 10，請一律下載 **`MinecraftServerManager-self-contained.exe`** 即可順暢使用。

### 從原始程式碼開發與建置

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
pwsh -NoProfile -File scripts\dotnet_publish.ps1
```

## 專案結構

```text
src/
├─ MinecraftServerManager.App/             WPF 視窗、View、ViewModel 與應用程式進入點
├─ MinecraftServerManager.Core/            工作流程、用例與服務合約
├─ MinecraftServerManager.Domain/          核心領域模型、值物件與業務規則
└─ MinecraftServerManager.Infrastructure/  檔案系統、HTTP、行程管理與 Java 整合
tests/
├─ MinecraftServerManager.UnitTests/       全量單元測試套件
└─ MinecraftServerManager.IntegrationTests/系統整合與流程測試套件
scripts/                                   自動化建置、發布與品質檢驗腳本
```

## 說明文件

- [技術手冊](docs/TECHNICAL_OVERVIEW.md)：架構分層、安全機制與實作技術細節
- [使用手冊](docs/USER_GUIDE.md)：詳細介面操作指南與常見問題排除

## 授權條款

本專案採用 GNU General Public License v3.0（GPLv3）授權，詳見 [LICENSE](LICENSE)。
