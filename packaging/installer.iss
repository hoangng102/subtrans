; Trình cài đặt Windows (Inno Setup 6, https://jrsoftware.org/isinfo.php). Chạy sau khi đã build bằng build_windows.ps1:
;   iscc packaging\installer.iss
; Chưa được build thử trên máy phát triển (chưa cài Inno Setup).
#define AppName "SubTrans"
#define AppVersion "0.1.0"

[Setup]
AppName={#AppName}
AppVersion={#AppVersion}
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
OutputDir=..\dist
OutputBaseFilename=SubTrans-Setup-{#AppVersion}
Compression=lzma2
SolidCompression=yes
PrivilegesRequired=lowest
ArchitecturesInstallIn64BitMode=x64compatible
WizardStyle=modern
LicenseFile=..\LICENSE

[Files]
Source: "..\dist\SubTrans\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{group}\SubTrans"; Filename: "{app}\SubTrans.exe"
Name: "{autodesktop}\SubTrans"; Filename: "{app}\SubTrans.exe"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Tạo biểu tượng ngoài màn hình nền"; Flags: unchecked

[Run]
Filename: "{app}\SubTrans.exe"; Description: "Mở SubTrans"; Flags: nowait postinstall skipifsilent
