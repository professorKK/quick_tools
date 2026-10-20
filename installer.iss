; QuickTools Windows 安装包配置（Inno Setup 6）
;
; 先决条件：先运行 build_windows.bat 或 build_all.bat，生成 dist\win\QuickTools\。
; 手动构建：
;   "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" installer.iss
; 产物：dist\win\QuickTools-Setup.exe
;
; 说明：
; - 按用户安装到 %LOCALAPPDATA%\Programs\QuickTools，不需要管理员权限；
; - 未内置中文语言文件（Inno Setup 官方不带 ChineseSimplified.isl），
;   安装向导本身是英文，应用名和快捷方式为中文，避免额外依赖第三方语言包；
; - 只支持 64 位 Windows，与打包用的 Python 位数一致。

#define AppName "快捷工具"
#define AppVersion "0.1.0"
#define AppExeName "QuickTools.exe"

[Setup]
AppId={{2E3C3A8B-5F6D-4B7A-9C1E-7A4B5C6D8E9F}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher=QuickTools
DefaultDirName={localappdata}\Programs\QuickTools
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=dist\win
OutputBaseFilename=QuickTools-Setup
SetupIconFile=quicktools\assets\quicktools.ico
UninstallDisplayIcon={app}\{#AppExeName}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
; 安装时如果程序正在运行，提示关闭而不是直接覆盖失败
CloseApplications=yes
RestartApplications=no

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; GroupDescription: "附加任务："; Flags: unchecked

[Files]
Source: "dist\win\QuickTools\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExeName}"
Name: "{group}\卸载 {#AppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExeName}"; Description: "立即启动{#AppName}"; Flags: nowait postinstall skipifsilent
