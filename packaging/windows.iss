#ifndef AppVersion
  #define AppVersion "0.19.0"
#endif

[Setup]
AppId=CantusPDF{param:BuildCheck|}
AppName=Cantus PDF
AppVersion={#AppVersion}
AppPublisher=Cantus PDF
DefaultDirName={localappdata}\Programs\Cantus PDF
DefaultGroupName=Cantus PDF
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0.22000
OutputDir=..\dist
OutputBaseFilename=CantusPDF-Windows-x64-Setup
SetupIconFile=..\build\windows\CantusPDF.ico
UninstallDisplayIcon={app}\CantusPDF.exe
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes

[Tasks]
Name: desktopicon; Description: "Create a desktop shortcut"; GroupDescription: "Shortcuts:"

[Files]
Source: "..\dist\CantusPDF-Windows\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\Cantus PDF"; Filename: "{app}\CantusPDF.exe"
Name: "{autodesktop}\Cantus PDF"; Filename: "{app}\CantusPDF.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\CantusPDF.exe"; Description: "Open Cantus PDF"; Flags: nowait postinstall skipifsilent
