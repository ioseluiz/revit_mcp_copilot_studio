@echo off
setlocal

:: Define the plugin name
set PLUGIN_NAME=RevitMCPBridge
set REVIT_VERSION=2025

:: Define the target path in AppData
set TARGET_DIR=%APPDATA%\Autodesk\Revit\Addins\%REVIT_VERSION%
set PLUGIN_FOLDER=%TARGET_DIR%\%PLUGIN_NAME%

echo --- Instalando Plugin Revit: %PLUGIN_NAME% ---

:: 1. Crear el folder del plugin si no existe
if not exist "%PLUGIN_FOLDER%" (
    echo Creando directorio: %PLUGIN_FOLDER%
    mkdir "%PLUGIN_FOLDER%"
)

:: 2. Copiar el archivo .dll al folder del plugin
:: Buscamos el DLL en la ruta de build (Debug x64)
set SOURCE_DLL=RevitMCPBridge\bin\x64\Debug\net8.0-windows\RevitMCPBridge.dll

if exist "%SOURCE_DLL%" (
    echo Copiando %PLUGIN_NAME%.dll...
    copy /Y "%SOURCE_DLL%" "%PLUGIN_FOLDER%\"
) else (
    echo [ERROR] No se encontro el archivo DLL en %SOURCE_DLL%
    echo Por favor, compila el proyecto en Visual Studio primero.
    pause
    exit /b 1
)

:: 3. Copiar el archivo .addin al folder de Revit (fuera del folder del plugin)
set SOURCE_ADDIN=RevitMCPBridge.addin

if exist "%SOURCE_ADDIN%" (
    echo Copiando %PLUGIN_NAME%.addin...
    copy /Y "%SOURCE_ADDIN%" "%TARGET_DIR%\"
) else (
    echo [ERROR] No se encontro el archivo %SOURCE_ADDIN%
    pause
    exit /b 1
)

echo.
echo --- Instalacion Completada con Exito ---
echo El plugin estara disponible al reiniciar Revit %REVIT_VERSION%.
echo Ubicacion: %TARGET_DIR%
echo.
pause
endlocal