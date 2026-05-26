; ============================================================
; INIO IA Assistant - RevitMCPBridge Installer
; Inno Setup 6.x
; No requiere permisos de administrador (instala en %APPDATA%)
; URL del servidor y API Key se configuran durante la instalación.
; ============================================================

#ifndef AppVersion
  #define AppVersion "1.0.0"
#endif

#define AppName      "INIO IA Assistant - RevitMCPBridge"
#define AppPublisher "INIO-CE"
#define AppURL       "https://github.com/inio-ce"
#define RevitVersion "2025"
#define DefaultUrl   "https://inio-revit-assistant-cfdddkaphacxeqga.centralus-01.azurewebsites.net"

[Setup]
AppId={{A7F3C2D1-8B4E-4F9A-B3C7-D2E5F6A8B9C0}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
AppPublisherURL={#AppURL}
DefaultDirName={userappdata}\Autodesk\Revit\Addins\{#RevitVersion}\RevitMCPBridge
DefaultGroupName={#AppName}
DisableDirPage=yes
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=commandline
OutputDir=Output
OutputBaseFilename=RevitMCPBridge-Setup-{#AppVersion}
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
WizardResizable=no
UninstallDisplayName={#AppName}
CloseApplications=no

[Languages]
Name: "spanish"; MessagesFile: "compiler:Languages\Spanish.isl"

[Files]
Source: "..\RevitMCPBridge\bin\x64\Release\net8.0-windows\RevitMCPBridge.dll"; \
  DestDir: "{userappdata}\Autodesk\Revit\Addins\{#RevitVersion}\RevitMCPBridge"; \
  Flags: ignoreversion

Source: "..\RevitMCPBridge\bin\x64\Release\net8.0-windows\RevitMCPBridge.deps.json"; \
  DestDir: "{userappdata}\Autodesk\Revit\Addins\{#RevitVersion}\RevitMCPBridge"; \
  Flags: ignoreversion skipifsourcedoesntexist

Source: "..\RevitMCPBridge\bin\x64\Release\net8.0-windows\RevitMCPBridge.runtimeconfig.json"; \
  DestDir: "{userappdata}\Autodesk\Revit\Addins\{#RevitVersion}\RevitMCPBridge"; \
  Flags: ignoreversion skipifsourcedoesntexist

Source: "..\RevitMCPBridge.addin"; \
  DestDir: "{userappdata}\Autodesk\Revit\Addins\{#RevitVersion}"; \
  Flags: ignoreversion

[UninstallDelete]
Type: filesandordirs; Name: "{userappdata}\Autodesk\Revit\Addins\{#RevitVersion}\RevitMCPBridge"
Type: files; Name: "{userappdata}\Autodesk\Revit\Addins\{#RevitVersion}\RevitMCPBridge.addin"

[Code]

// ----------------------------------------------------------------
// Variables globales
// ----------------------------------------------------------------
var
  RevitExePath: String;

  // Página: Revit no encontrado
  RevitPathEdit: TEdit;
  BrowseButton: TButton;
  RevitStatusLabel: TLabel;
  RevitPageCreated: Boolean;

  // Páginas de configuración del servidor
  ServerConfigPage: TInputQueryWizardPage;
  ApiKeyPage: TInputQueryWizardPage;


// ----------------------------------------------------------------
// Escapar caracteres especiales de JSON para el config.json
// ----------------------------------------------------------------
function JsonEscape(S: String): String;
var
  I: Integer;
  C: Char;
  R: String;
begin
  R := '';
  for I := 1 to Length(S) do
  begin
    C := S[I];
    if C = '"' then R := R + '\"'
    else if C = '\' then R := R + '\\'
    else if Ord(C) = 13 then R := R + '\r'
    else if Ord(C) = 10 then R := R + '\n'
    else R := R + C;
  end;
  Result := R;
end;


// ----------------------------------------------------------------
// Busca Revit 2025 en rutas comunes y en el registro
// ----------------------------------------------------------------
function FindRevit2025: String;
var
  InstallDir: String;
  RegPath: String;
  Candidates: TArrayOfString;
  I: Integer;
begin
  Result := '';
  RegPath := 'SOFTWARE\Autodesk\Revit\Autodesk Revit 2025\2025';

  if RegQueryStringValue(HKLM64, RegPath, 'InstallLocation', InstallDir) then
    if FileExists(InstallDir + '\Revit.exe') then
    begin
      Result := InstallDir + '\Revit.exe';
      Exit;
    end;

  if RegQueryStringValue(HKLM, RegPath, 'InstallLocation', InstallDir) then
    if FileExists(InstallDir + '\Revit.exe') then
    begin
      Result := InstallDir + '\Revit.exe';
      Exit;
    end;

  SetArrayLength(Candidates, 4);
  Candidates[0] := 'C:\Program Files\Autodesk\Revit 2025\Revit.exe';
  Candidates[1] := 'C:\Program Files\Autodesk\Revit Architecture 2025\Revit.exe';
  Candidates[2] := ExpandConstant('{commonpf64}\Autodesk\Revit 2025\Revit.exe');
  Candidates[3] := ExpandConstant('{commonpf}\Autodesk\Revit 2025\Revit.exe');

  for I := 0 to GetArrayLength(Candidates) - 1 do
    if FileExists(Candidates[I]) then
    begin
      Result := Candidates[I];
      Exit;
    end;
end;


// ----------------------------------------------------------------
// Lee el valor de una clave del config.json existente (si hay)
// Permite pre-llenar los campos en reinstalación.
// ----------------------------------------------------------------
function ReadExistingConfig(Key: String): String;
var
  ConfigPath: String;
  Content: String;
  StartPos, EndPos: Integer;
  SearchKey: String;
begin
  Result := '';
  ConfigPath := ExpandConstant('{userappdata}\Autodesk\Revit\Addins\{#RevitVersion}\RevitMCPBridge\config.json');
  if not FileExists(ConfigPath) then Exit;

  LoadStringFromFile(ConfigPath, Content);
  SearchKey := '"' + Key + '": "';
  StartPos := Pos(SearchKey, Content);
  if StartPos = 0 then Exit;

  StartPos := StartPos + Length(SearchKey);
  EndPos := StartPos;
  while (EndPos <= Length(Content)) and (Content[EndPos] <> '"') do
    EndPos := EndPos + 1;

  Result := Copy(Content, StartPos, EndPos - StartPos);
end;


// ----------------------------------------------------------------
// Página personalizada: Revit no encontrado
// ----------------------------------------------------------------
procedure CreateRevitNotFoundPage;
var
  Page: TWizardPage;
  TitleLbl, DescLbl, PathLbl: TLabel;
begin
  Page := CreateCustomPage(wpWelcome,
    'Revit 2025 no encontrado',
    'Ayúdanos a localizar Autodesk Revit 2025 en tu equipo.');

  TitleLbl := TLabel.Create(Page);
  TitleLbl.Parent := Page.Surface;
  TitleLbl.Caption := 'No se pudo detectar Revit 2025 automáticamente.';
  TitleLbl.Font.Style := [fsBold];
  TitleLbl.SetBounds(0, 0, Page.SurfaceWidth, 20);

  DescLbl := TLabel.Create(Page);
  DescLbl.Parent := Page.Surface;
  DescLbl.Caption :=
    'El instalador buscó en rutas estándar y en el registro de Windows ' +
    'pero no encontró Autodesk Revit 2025.' + #13#10 + #13#10 +
    'Si tienes Revit 2025 instalado en una ubicación personalizada, ' +
    'usa el botón "Buscar..." para localizar el archivo Revit.exe.' + #13#10 + #13#10 +
    'Puedes continuar sin seleccionarlo: el plugin estará instalado ' +
    'y se activará automáticamente cuando instales Revit 2025.';
  DescLbl.WordWrap := True;
  DescLbl.SetBounds(0, 28, Page.SurfaceWidth, 90);

  PathLbl := TLabel.Create(Page);
  PathLbl.Parent := Page.Surface;
  PathLbl.Caption := 'Ruta de Revit.exe (opcional):';
  PathLbl.SetBounds(0, 128, Page.SurfaceWidth, 18);

  RevitPathEdit := TEdit.Create(Page);
  RevitPathEdit.Parent := Page.Surface;
  RevitPathEdit.SetBounds(0, 148, Page.SurfaceWidth - 92, 22);
  RevitPathEdit.Text := 'C:\Program Files\Autodesk\Revit 2025\Revit.exe';

  BrowseButton := TButton.Create(Page);
  BrowseButton.Parent := Page.Surface;
  BrowseButton.Caption := 'Buscar...';
  BrowseButton.SetBounds(Page.SurfaceWidth - 87, 146, 87, 26);
  BrowseButton.OnClick := @BrowseRevitPath;

  RevitStatusLabel := TLabel.Create(Page);
  RevitStatusLabel.Parent := Page.Surface;
  RevitStatusLabel.SetBounds(0, 178, Page.SurfaceWidth, 22);
  RevitStatusLabel.Caption := '';

  RevitPageCreated := True;
end;


// ----------------------------------------------------------------
// Handler del botón "Buscar..."
// ----------------------------------------------------------------
procedure BrowseRevitPath(Sender: TObject);
var
  FileName: String;
begin
  FileName := RevitPathEdit.Text;
  if GetOpenFileName('Localizar Revit.exe', FileName,
      'C:\Program Files\Autodesk',
      'Revit Executable|Revit.exe|Todos los archivos|*.*', 'exe') then
  begin
    RevitPathEdit.Text := FileName;
    if FileExists(FileName) and (CompareText(ExtractFileName(FileName), 'Revit.exe') = 0) then
    begin
      RevitStatusLabel.Caption := 'Revit.exe encontrado. La instalación procederá correctamente.';
      RevitStatusLabel.Font.Color := clGreen;
      RevitExePath := FileName;
    end
    else
    begin
      RevitStatusLabel.Caption := 'El archivo seleccionado no parece ser Revit.exe.';
      RevitStatusLabel.Font.Color := clMaroon;
    end;
  end;
end;


// ----------------------------------------------------------------
// Inicialización del wizard
// ----------------------------------------------------------------
procedure InitializeWizard;
var
  ExistingUrl, ExistingKey: String;
begin
  RevitPageCreated := False;
  RevitExePath := FindRevit2025();

  if RevitExePath = '' then
    CreateRevitNotFoundPage();

  // Leer valores existentes de config (para reinstalaciones)
  ExistingUrl := ReadExistingConfig('AzureBaseUrl');
  ExistingKey := ReadExistingConfig('ApiKey');

  if ExistingUrl = '' then ExistingUrl := '{#DefaultUrl}';
  if ExistingKey = '' then ExistingKey := 'my-super-secret-key-2026';

  // Página 1: URL del servidor Azure
  ServerConfigPage := CreateInputQueryPage(
    wpWelcome,
    'Configuración del servidor MCP',
    'Introduce la URL de tu servidor Azure App Service.',
    'Puedes encontrar esta URL en el portal de Azure, ' +
    'en la sección "Overview" de tu App Service.');
  ServerConfigPage.Add('URL del servidor Azure:', False);
  ServerConfigPage.Values[0] := ExistingUrl;

  // Página 2: API Key
  ApiKeyPage := CreateInputQueryPage(
    ServerConfigPage.ID,
    'Clave de autenticación (API Key)',
    'Introduce la clave secreta de tu servidor MCP.',
    'Esta clave debe coincidir con la variable de entorno ' +
    'API_KEY configurada en tu Azure App Service.');
  ApiKeyPage.Add('API Key (x-api-key):', False);
  ApiKeyPage.Values[0] := ExistingKey;
end;


// ----------------------------------------------------------------
// Validación al avanzar de página
// ----------------------------------------------------------------
function NextButtonClick(CurPageID: Integer): Boolean;
begin
  Result := True;

  // Validar URL del servidor
  if CurPageID = ServerConfigPage.ID then
  begin
    if Trim(ServerConfigPage.Values[0]) = '' then
    begin
      MsgBox('La URL del servidor no puede estar vacía.', mbError, MB_OK);
      Result := False;
      Exit;
    end;
    if (Pos('http://', LowerCase(ServerConfigPage.Values[0])) = 0) and
       (Pos('https://', LowerCase(ServerConfigPage.Values[0])) = 0) then
    begin
      MsgBox('La URL debe comenzar con http:// o https://', mbError, MB_OK);
      Result := False;
      Exit;
    end;
  end;

  // Validar API Key
  if CurPageID = ApiKeyPage.ID then
  begin
    if Trim(ApiKeyPage.Values[0]) = '' then
    begin
      MsgBox('La API Key no puede estar vacía.', mbError, MB_OK);
      Result := False;
      Exit;
    end;
  end;

  // Si tenemos la página de Revit y el usuario escribió una ruta
  if RevitPageCreated and (CurPageID = wpWelcome) then
  begin
    if (RevitPathEdit <> nil) and (Trim(RevitPathEdit.Text) <> '') then
    begin
      if FileExists(RevitPathEdit.Text) then
        RevitExePath := RevitPathEdit.Text;
    end;
  end;
end;


// ----------------------------------------------------------------
// Escribir config.json después de copiar los archivos
// ----------------------------------------------------------------
procedure CurStepChanged(CurStep: TSetupStep);
var
  ConfigPath: String;
  AzureUrl, ApiKey: String;
  ConfigJson: String;
begin
  if CurStep = ssPostInstall then
  begin
    AzureUrl := Trim(ServerConfigPage.Values[0]);
    ApiKey   := Trim(ApiKeyPage.Values[0]);

    // Eliminar barra final de la URL
    if (Length(AzureUrl) > 0) and (AzureUrl[Length(AzureUrl)] = '/') then
      AzureUrl := Copy(AzureUrl, 1, Length(AzureUrl) - 1);

    ConfigPath := ExpandConstant(
      '{userappdata}\Autodesk\Revit\Addins\{#RevitVersion}\RevitMCPBridge\config.json');

    ConfigJson :=
      '{' + #13#10 +
      '  "AzureBaseUrl": "' + JsonEscape(AzureUrl) + '",' + #13#10 +
      '  "ApiKey": "' + JsonEscape(ApiKey) + '"' + #13#10 +
      '}';

    SaveStringToFile(ConfigPath, ConfigJson, False);
  end;

  if CurStep = ssDone then
  begin
    if RevitExePath <> '' then
      MsgBox(
        'RevitMCPBridge instalado correctamente.' + #13#10 + #13#10 +
        'Servidor configurado: ' + Trim(ServerConfigPage.Values[0]) + #13#10 + #13#10 +
        'Reinicia Autodesk Revit 2025 para activar el plugin.' + #13#10 +
        'Encontrarás el botón "MCP Server (OFF)" en la pestaña "INIO IA Assistant".',
        mbInformation, MB_OK)
    else
      MsgBox(
        'El plugin se instaló, pero Revit 2025 no fue detectado.' + #13#10 + #13#10 +
        'Servidor configurado: ' + Trim(ServerConfigPage.Values[0]) + #13#10 + #13#10 +
        'Si instalas Revit 2025 más adelante, el plugin estará disponible automáticamente.',
        mbInformation, MB_OK);
  end;
end;
