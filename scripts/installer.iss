; Inno Setup 安裝腳本（繁體中文）
; 必須由 build_installer_nuitka.bat 傳入 /DAppVersion、/DAppName 與 /DAppId

[Setup]
AppId={#AppId}
AppName={#AppName}
AppVersion={#AppVersion}
VersionInfoVersion={#AppVersion}
VersionInfoProductVersion={#AppVersion}
AppPublisher=Colin955023
AppPublisherURL=https://github.com/Colin955023/MinecraftServerManager
AppSupportURL=https://github.com/Colin955023/MinecraftServerManager/issues
AppUpdatesURL=https://github.com/Colin955023/MinecraftServerManager/releases
DefaultDirName={localappdata}\Programs\MinecraftServerManager
DefaultGroupName=Minecraft 伺服器管理器
DisableProgramGroupPage=yes
OutputDir=..\dist
OutputBaseFilename={#AppName}-Setup-{#AppVersion}
Compression=lzma2/ultra64
SolidCompression=yes
LZMAUseSeparateProcess=yes
LZMADictionarySize=32768
WizardStyle=modern
SetupIconFile=..\assets\icon.ico
UninstallDisplayIcon={app}\assets\icon.ico
ArchitecturesInstallIn64BitMode=x64compatible
PrivilegesRequired=lowest
AppMutex=MinecraftServerManagerMutex
CloseApplications=yes
CloseApplicationsFilter=MinecraftServerManager.exe
RestartApplications=no
RestartIfNeededByRun=no
LanguageDetectionMethod=locale
SetupLogging=yes

[Languages]
Name: "chinesetraditional"; MessagesFile: "compiler:Default.isl,inno\\ChineseTraditional.isl"


[Files]
; 打包 Nuitka standalone (資料夾模式) 的輸出並排除常見開發檔案
Source: "..\dist\MinecraftServerManager\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion; \
Excludes: "user_settings.json;__pycache__\*;*.pyc;*.pyo;*.pdb;*.map;*.log;.DS_Store;Thumbs.db;*.tmp;*.temp;.git*;.vs*;node_modules\*"

[Icons]
Name: "{group}\Minecraft 伺服器管理器"; Filename: "{app}\MinecraftServerManager.exe"; IconFilename: "{app}\assets\icon.ico"
Name: "{commondesktop}\Minecraft 伺服器管理器"; Filename: "{app}\MinecraftServerManager.exe"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "在桌面建立捷徑"; GroupDescription: "其他選項："

[Run]
Filename: "{app}\MinecraftServerManager.exe"; Description: "安裝後立即執行"; Flags: nowait postinstall skipifsilent runasoriginaluser

[Code]

function FindPortableRoot(const StartPath: string): string;
var
  P, TryPath: string;
begin
  Result := '';
  TryPath := StartPath;
  while TryPath <> '' do
  begin
    P := ExpandConstant(TryPath + '\\.portable');
    if FileExists(P) then
    begin
      Result := TryPath;
      Exit;
    end;
    if (TryPath = '\\') or (TryPath = '') then
      Break;
    TryPath := ExtractFileDir(TryPath);
    if (TryPath = ExtractFileDrive(TryPath) + ':') then
      Break;
  end;
end;

function GetDataRoot(): string;
var
  AppFolder: string;
  PortableFound: string;
begin
  AppFolder := ExpandConstant('{app}');
  PortableFound := FindPortableRoot(AppFolder);
  if PortableFound <> '' then
  begin
    Result := AppFolder;
    exit;
  end;
  Result := ExpandConstant('{localappdata}\\Programs\\MinecraftServerManager');
end;

function IsPortable(): Boolean;
begin
  Result := FindPortableRoot(ExpandConstant('{app}')) <> '';
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  DataRoot, CacheDir, LogDir, SettingsPath: string;
begin
  if CurUninstallStep = usUninstall then
  begin
    { 在解除安裝階段清理使用者資料（而非 PostUninstall）}
    DataRoot := GetDataRoot();
    CacheDir := DataRoot + '\Cache';
    LogDir := DataRoot + '\log';
    SettingsPath := DataRoot + '\user_settings.json';

    if DirExists(CacheDir) then
      DelTree(CacheDir, True, True, True);

    if DirExists(LogDir) then
      DelTree(LogDir, True, True, True);

    if FileExists(SettingsPath) then
      DeleteFile(SettingsPath);
  end;
end;
