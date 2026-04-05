[Setup]
AppId={{#AppId}
AppName={#AppName}
AppVersion={#AppVersion}
VersionInfoVersion={#AppVersion}
VersionInfoProductVersion={#AppVersion}
AppPublisher=Colin955023
AppPublisherURL=[https://github.com/Colin955023/MinecraftServerManager](https://github.com/Colin955023/MinecraftServerManager)
DefaultDirName={localappdata}\Programs\MinecraftServerManager
DefaultGroupName=Minecraft 伺服器管理器
DisableProgramGroupPage=yes
OutputDir=..\dist
OutputBaseFilename={#AppName}-Setup-{#AppVersion}
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
SetupIconFile=..\assets\icon.ico
UninstallDisplayIcon={app}\assets\icon.ico
ArchitecturesInstallIn64BitMode=x64compatible
PrivilegesRequired=lowest
AppMutex=MinecraftServerManagerMutex
CloseApplications=yes
CloseApplicationsFilter=MinecraftServerManager.exe
LanguageDetectionMethod=locale
SetupLogging=yes

[Languages]
Name: "chinesetraditional"; MessagesFile: "compiler:Default.isl,inno\\ChineseTraditional.isl"

[Files]
Source: "..\dist\MinecraftServerManager\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion; \
Excludes: "user_settings.json;__pycache__\*;*.pyc;*.pyo;*.pdb;*.log;.DS_Store;Thumbs.db;*.tmp;*.temp" 

[Icons]
Name: "{group}\Minecraft 伺服器管理器"; Filename: "{app}\MinecraftServerManager.exe"; IconFilename: "{app}\assets\icon.ico"
Name: "{commondesktop}\Minecraft 伺服器管理器"; Filename: "{app}\MinecraftServerManager.exe"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "在桌面建立捷徑"; GroupDescription: "其他選項："

[Run]
Filename: "{app}\MinecraftServerManager.exe"; Description: "安裝後立即執行"; Flags: nowait postinstall skipifsilent runasoriginaluser

[Code]
function GetDataRoot(): string;
begin
  { 使用 ExpandConstant 確保路徑動態獲取，比硬編碼更穩定 }
  Result := ExpandConstant('{localappdata}\Programs\MinecraftServerManager');
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  DataRoot, CacheDir, LogDir, SettingsPath: string;
begin
  if CurUninstallStep = usUninstall then
  begin
    DataRoot := GetDataRoot();
    CacheDir := DataRoot + '\Cache';
    LogDir := DataRoot + '\log';
    SettingsPath := DataRoot + '\user_settings.json';

    { 安全性優化：確認目錄存在才執行刪除，並加入錯誤處理防止解除安裝中斷 }
    try
      if DirExists(CacheDir) then DelTree(CacheDir, True, True, True);
      if DirExists(LogDir) then DelTree(LogDir, True, True, True);
      if FileExists(SettingsPath) then DeleteFile(SettingsPath);
    except
      { 即使刪除資料失敗，也要讓解除安裝繼續進行 }
    end;
  end;

  if CurUninstallStep = usPostUninstall then
  begin
    { 只有在目錄真的為空時才移除，避免誤刪 }
    if DirExists(ExpandConstant('{app}')) then
      RemoveDir(ExpandConstant('{app}'));
  end;
end;