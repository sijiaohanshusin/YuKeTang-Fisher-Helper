#ifndef AppVersion
  #define AppVersion "2.1.0"
#endif
#define RepoRoot AddBackslash(SourcePath) + ".."
[Setup]
AppId={{28E10BCF-96F6-4DF5-8D7A-59B01AEF01B8}
AppName=雨课堂助手
AppVersion={#AppVersion}
AppPublisher=sijiaohanshusin
AppPublisherURL=https://github.com/sijiaohanshusin/YuKeTang-Fisher-Helper
AppSupportURL=https://github.com/sijiaohanshusin/YuKeTang-Fisher-Helper/issues
DefaultDirName={localappdata}\Programs\YuketangHelper
DefaultGroupName=雨课堂助手
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
OutputDir={#RepoRoot}\release
OutputBaseFilename=YuketangHelper-Setup-v{#AppVersion}-Windows-x64
Compression=lzma2/fast
SolidCompression=yes
WizardStyle=modern
DisableWelcomePage=yes
DisableDirPage=yes
DisableProgramGroupPage=yes
DisableReadyPage=yes
UninstallDisplayIcon={app}\YuketangHelper.exe
SetupIconFile={#RepoRoot}\frontend\src\favicon_256x256.ico
CloseApplications=yes
RestartApplications=no
[Languages]
Name: "chinesesimp"; MessagesFile: "{#RepoRoot}\installer\ChineseSimplified.isl"
[Files]
Source: "{#RepoRoot}\dist\YuketangHelper.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#RepoRoot}\分发使用说明.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#RepoRoot}\THIRD_PARTY_NOTICES.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#RepoRoot}\build\licenses\*"; DestDir: "{app}\licenses"; Flags: ignoreversion recursesubdirs createallsubdirs
[Dirs]
Name: "{localappdata}\YuketangHelper"; Check: ShouldCreateShortcuts
[Icons]
Name: "{group}\启动雨课堂助手"; Filename: "{app}\YuketangHelper.exe"; Parameters: "--data-dir ""{localappdata}\YuketangHelper\store"""; Check: ShouldCreateShortcuts
Name: "{group}\停止雨课堂助手"; Filename: "{app}\YuketangHelper.exe"; Parameters: "--stop --data-dir ""{localappdata}\YuketangHelper\store"""; Check: ShouldCreateShortcuts
Name: "{group}\打开本地数据目录"; Filename: "{localappdata}\YuketangHelper"; Check: ShouldCreateShortcuts
Name: "{group}\卸载雨课堂助手"; Filename: "{uninstallexe}"; Check: ShouldCreateShortcuts
Name: "{autodesktop}\雨课堂助手"; Filename: "{app}\YuketangHelper.exe"; Parameters: "--data-dir ""{localappdata}\YuketangHelper\store"""; Check: ShouldCreateShortcuts
[Run]
Filename: "{app}\YuketangHelper.exe"; Parameters: "--data-dir ""{localappdata}\YuketangHelper\store"""; Description: "启动雨课堂助手，开始配置"; Flags: nowait postinstall skipifsilent
[UninstallRun]
Filename: "{app}\YuketangHelper.exe"; Parameters: "--stop --data-dir ""{localappdata}\YuketangHelper\store"""; Flags: runhidden skipifdoesntexist; Check: ShouldCreateShortcuts
[Code]
function ShouldCreateShortcuts(): Boolean;
begin
  Result := ExpandConstant('{param:SmokeTest|0}') <> '1';
end;
function PrepareToInstall(var NeedsRestart: Boolean): String;
var ExitCode: Integer;
begin
  Result := '';
  if FileExists(ExpandConstant('{app}\YuketangHelper.exe')) then
    Exec(ExpandConstant('{app}\YuketangHelper.exe'), '--stop --data-dir "' + ExpandConstant('{localappdata}\YuketangHelper\store') + '"', '', SW_HIDE, ewWaitUntilTerminated, ExitCode);
end;
