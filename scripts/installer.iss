[Setup]
AppId={{#AppId}
AppName={#AppName}
AppVersion={#AppVersion}
VersionInfoVersion={#AppVersion}
VersionInfoProductVersion={#AppVersion}
AppPublisher=Colin955023
AppPublisherURL=https://github.com/Colin955023/MinecraftServerManager
DefaultDirName={localappdata}\Programs\MinecraftServerManager
DisableDirPage=no
UsePreviousAppDir=no
DefaultGroupName=Minecraft 伺服器管理器
DisableProgramGroupPage=yes
OutputDir=..\dist
OutputBaseFilename={#AppName}-Setup-{#AppVersion}
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
SetupIconFile=..\assets\icon.ico
UninstallDisplayIcon={app}\assets\icon.ico
Uninstallable=not IsPortableInstall
CreateUninstallRegKey=not IsPortableInstall
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
Excludes: ".portable,.config,.config\*,.log,.log\*,log,log\*,Cache,Cache\*,user_settings.json,__pycache__,__pycache__\*,*.pyc,*.pyo,*.pdb,*.log,.DS_Store,Thumbs.db,*.tmp,*.temp"

[InstallDelete]
Type: files; Name: "{app}\unins*.dat"; Check: IsPortableInstall
Type: files; Name: "{app}\unins*.exe"; Check: IsPortableInstall
Type: files; Name: "{app}\unins*.msg"; Check: IsPortableInstall

[Icons]
Name: "{group}\Minecraft 伺服器管理器"; Filename: "{app}\MinecraftServerManager.exe"; IconFilename: "{app}\assets\icon.ico"; Check: not IsPortableInstall
Name: "{autodesktop}\Minecraft 伺服器管理器"; Filename: "{app}\MinecraftServerManager.exe"; Tasks: desktopicon; Check: not IsPortableInstall

[Tasks]
Name: "desktopicon"; Description: "在桌面建立捷徑"; GroupDescription: "其他選項："; Check: not IsPortableInstall

[Run]
Filename: "{app}\MinecraftServerManager.exe"; Description: "安裝後立即執行"; Flags: nowait postinstall skipifsilent runasoriginaluser

[UninstallDelete]
Type: files; Name: "{app}\.portable"

[Code]
var
  InstallModePage: TInputOptionWizardPage;
  PortableInstallMode: Boolean;

function GetNormalInstallDir(): string;
begin
  Result := ExpandConstant('{localappdata}\Programs\MinecraftServerManager');
end;

function GetPortableInstallDir(): string;
begin
  Result := ExpandConstant('{localappdata}\Programs\MinecraftServerManager-Portable');
end;

function IsPortableInstall(): Boolean;
begin
  Result := PortableInstallMode;
end;

procedure ApplyInstallModeDir();
begin
  if IsPortableInstall() then
  begin
    if (WizardForm.DirEdit.Text = '') or (WizardForm.DirEdit.Text = GetNormalInstallDir()) then
      WizardForm.DirEdit.Text := GetPortableInstallDir();
  end
  else
    WizardForm.DirEdit.Text := GetNormalInstallDir();
end;

function InitializeSetup(): Boolean;
begin
  PortableInstallMode := CompareText(ExpandConstant('{param:MSMPortable|0}'), '1') = 0;
  Result := True;
end;

procedure InitializeWizard();
begin
  InstallModePage := CreateInputOptionPage(
    wpWelcome,
    '選擇安裝模式',
    '請選擇 Minecraft 伺服器管理器的安裝方式。',
    '一般安裝會使用固定的本機使用者資料夾；可攜式安裝會讓您指定資料夾，並把設定與日誌保存在程式目錄下。',
    True,
    False
  );
  InstallModePage.Add('正常安裝');
  InstallModePage.Add('可攜式');
  if PortableInstallMode then
    InstallModePage.SelectedValueIndex := 1
  else
    InstallModePage.SelectedValueIndex := 0;
  ApplyInstallModeDir();
end;

function NextButtonClick(CurPageID: Integer): Boolean;
begin
  Result := True;
  if (InstallModePage <> nil) and (CurPageID = InstallModePage.ID) then
  begin
    PortableInstallMode := InstallModePage.SelectedValueIndex = 1;
    ApplyInstallModeDir();
  end;
end;

function ShouldSkipPage(PageID: Integer): Boolean;
begin
  Result := (PageID = wpSelectDir) and (not IsPortableInstall());
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  PortableMarker: string;
begin
  if CurStep = ssPostInstall then
  begin
    PortableMarker := ExpandConstant('{app}\.portable');
    if IsPortableInstall() then
    begin
      if not SaveStringToFile(PortableMarker, 'portable', False) then
        MsgBox('無法建立可攜式安裝標記：' + PortableMarker, mbError, MB_OK);
    end
    else if FileExists(PortableMarker) then
      DeleteFile(PortableMarker);
  end;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  DataRoot, CacheDir, LogDir, SettingsPath, PortableMarker: string;
begin
  if CurUninstallStep = usUninstall then
  begin
    PortableMarker := ExpandConstant('{app}\.portable');
    DataRoot := GetNormalInstallDir();
    CacheDir := DataRoot + '\Cache';
    LogDir := DataRoot + '\log';
    SettingsPath := DataRoot + '\user_settings.json';

    { 一般安裝解除安裝只清理固定的使用者本機資料；可攜式安裝不建立解除安裝程序。 }
    try
      if DirExists(CacheDir) then DelTree(CacheDir, True, True, True);
      if DirExists(LogDir) then DelTree(LogDir, True, True, True);
      if FileExists(SettingsPath) then DeleteFile(SettingsPath);
      if FileExists(PortableMarker) then DeleteFile(PortableMarker);
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
