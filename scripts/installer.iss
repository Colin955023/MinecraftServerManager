; Inno Setup 安裝腳本（繁體中文）
; 可由 build_installer.bat 傳入 /DAppVersion 與 /DAppName 覆蓋下述定義
#define GetStringDef(param, def) (param == "" ? def : param)
#define AppVersion GetStringDef(AppVersion, "1.3")
#define AppName GetStringDef(AppName, "MinecraftServerManager")

[Setup]
AppId={{B8E0E6D1-2B7E-4A73-9D5A-8C3F8B3E0F11}}
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
OutputDir=..\dist\installer
OutputBaseFilename={#AppName}-Setup-{#AppVersion}
Compression=lzma
SolidCompression=yes
WizardStyle=modern
SetupIconFile=..\assets\icon.ico
UninstallDisplayIcon={app}\assets\icon.ico
ArchitecturesInstallIn64BitMode=x64compatible
PrivilegesRequired=lowest
AppMutex=MinecraftServerManagerMutex
LanguageDetectionMethod=locale

[Languages]
Name: "chinesetraditional"; MessagesFile: "compiler:Languages\\ChineseTraditional.isl"


[Files]
; 打包 PyInstaller one-folder 的輸出並排除常見開發檔案，並排除 user_settings.json（實際上不會有這個檔案）
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
function GetDataRoot(): string;
begin
  Result := ExpandConstant('{localappdata}\\Programs\\MinecraftServerManager');
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  DataRoot, CacheDir, SettingsPath: string;
begin
  if CurUninstallStep = usUninstall then
  begin
    DataRoot := GetDataRoot();
    CacheDir := DataRoot + '\\Cache';
    SettingsPath := DataRoot + '\\user_settings.json';

    if DirExists(CacheDir) then
      DelTree(CacheDir, True, True, True);

    if FileExists(SettingsPath) then
      DeleteFile(SettingsPath);

    if DirExists(DataRoot) then
      RemoveDir(DataRoot);
  end;
end;