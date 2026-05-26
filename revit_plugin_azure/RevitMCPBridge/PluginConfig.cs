using System;
using System.IO;
using System.Text.Json;

namespace RevitMCPBridge
{
    /// <summary>
    /// Lee la configuración del plugin desde config.json en la misma carpeta del DLL.
    /// El archivo es escrito por el instalador con los valores que el usuario introduce.
    /// </summary>
    public static class PluginConfig
    {
        public static string AzureBaseUrl { get; private set; } =
            "https://inio-revit-assistant-cfdddkaphacxeqga.centralus-01.azurewebsites.net";

        public static string ApiKey { get; private set; } = "my-super-secret-key-2026";

        public static bool IsLoaded { get; private set; } = false;

        public static string ConfigFilePath => Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData),
            "Autodesk", "Revit", "Addins", "2025", "RevitMCPBridge", "config.json");

        public static void Load()
        {
            try
            {
                if (!File.Exists(ConfigFilePath))
                    return;

                string json = File.ReadAllText(ConfigFilePath);
                using var doc = JsonDocument.Parse(json);
                var root = doc.RootElement;

                if (root.TryGetProperty("AzureBaseUrl", out var urlEl))
                {
                    var val = urlEl.GetString();
                    if (!string.IsNullOrWhiteSpace(val))
                        AzureBaseUrl = val.TrimEnd('/');
                }

                if (root.TryGetProperty("ApiKey", out var keyEl))
                {
                    var val = keyEl.GetString();
                    if (!string.IsNullOrWhiteSpace(val))
                        ApiKey = val;
                }

                IsLoaded = true;
            }
            catch
            {
                // Si el archivo está corrupto, continúa con los valores por defecto.
            }
        }
    }
}
