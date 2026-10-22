; Inno Setup script — per-user install, no admin rights needed.
#define AppVersion GetEnv("DS_VERSION")
#if AppVersion == ""
  #define AppVersion "1.0.0"
#endif

[Setup]
AppId={{6C1E2B0A-7D5F-4E8B-9F3A-D7A5F1C2B3E4}
AppName=ShiftWheel
AppVersion={#AppVersion}
AppPublisher=ShiftWheel
DefaultDirName={localappdata}\Programs\ShiftWheel
DefaultGroupName=ShiftWheel
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=..\dist
OutputBaseFilename=ShiftWheel-Setup
SetupIconFile=..\shiftwheel\assets\shiftwheel.ico
UninstallDisplayIcon={app}\ShiftWheel.exe
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes
RestartApplications=no

[Tasks]
Name: "autostart"; Description: "Start ShiftWheel when I sign in to Windows"; Flags: checkedonce
Name: "contextmenu"; Description: "Add ""ShiftWheel"" to the right-click menu for files"; Flags: checkedonce
Name: "desktopicon"; Description: "Create a desktop shortcut"; Flags: unchecked

[Files]
Source: "..\dist\ShiftWheel\*"; DestDir: "{app}"; Flags: recursesubdirs ignoreversion

[Icons]
Name: "{autoprograms}\ShiftWheel"; Filename: "{app}\ShiftWheel.exe"
Name: "{autodesktop}\ShiftWheel"; Filename: "{app}\ShiftWheel.exe"; Tasks: desktopicon
Name: "{usersendto}\ShiftWheel"; Filename: "{app}\ShiftWheel.exe"

[Registry]
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "ShiftWheel"; ValueData: """{app}\ShiftWheel.exe"" --quiet"; Tasks: autostart; Flags: uninsdeletevalue
Root: HKCU; Subkey: "Software\Classes\*\shell\ShiftWheel"; ValueType: string; ValueName: "MUIVerb"; ValueData: "ShiftWheel…"; Tasks: contextmenu; Flags: uninsdeletekey
Root: HKCU; Subkey: "Software\Classes\*\shell\ShiftWheel"; ValueType: string; ValueName: "Icon"; ValueData: "{app}\ShiftWheel.exe"; Tasks: contextmenu
Root: HKCU; Subkey: "Software\Classes\*\shell\ShiftWheel"; ValueType: string; ValueName: "MultiSelectModel"; ValueData: "Player"; Tasks: contextmenu
Root: HKCU; Subkey: "Software\Classes\*\shell\ShiftWheel\command"; ValueType: string; ValueName: ""; ValueData: """{app}\ShiftWheel.exe"" ""%1"""; Tasks: contextmenu
Root: HKCU; Subkey: "Software\Classes\Directory\shell\ShiftWheel"; ValueType: string; ValueName: "MUIVerb"; ValueData: "ShiftWheel…"; Tasks: contextmenu; Flags: uninsdeletekey
Root: HKCU; Subkey: "Software\Classes\Directory\shell\ShiftWheel"; ValueType: string; ValueName: "Icon"; ValueData: "{app}\ShiftWheel.exe"; Tasks: contextmenu
Root: HKCU; Subkey: "Software\Classes\Directory\shell\ShiftWheel"; ValueType: string; ValueName: "MultiSelectModel"; ValueData: "Player"; Tasks: contextmenu
Root: HKCU; Subkey: "Software\Classes\Directory\shell\ShiftWheel\command"; ValueType: string; ValueName: ""; ValueData: """{app}\ShiftWheel.exe"" ""%1"""; Tasks: contextmenu
Root: HKCU; Subkey: "Software\ShiftWheel"; Flags: uninsdeletekey

[Run]
Filename: "{app}\ShiftWheel.exe"; Description: "Launch ShiftWheel now"; Flags: nowait postinstall skipifsilent

[UninstallRun]
Filename: "{cmd}"; Parameters: "/C taskkill /F /IM ShiftWheel.exe"; Flags: runhidden; RunOnceId: "KillShiftWheel"
