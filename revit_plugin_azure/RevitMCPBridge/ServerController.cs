using System;
using System.Net.Http;
using System.Net.Http.Headers;
using System.Text;
using System.Text.Json;
using System.Threading;
using System.Threading.Tasks;
using Autodesk.Revit.UI;

namespace RevitMCPBridge
{
    public static class ServerController
    {
        // -------------------------------------------------------------
        // CONFIGURACIÓN DE AZURE
        // -------------------------------------------------------------
        // Cambia esto por la URL real de tu Azure App Service
        private const string AZURE_BASE_URL = "https://tu-app-service.azurewebsites.net"; 
        private const string API_KEY = "1234567890"; // Debe coincidir con el servidor Python
        
        private static readonly HttpClient _httpClient;
        private static CancellationTokenSource _cts;

        private static readonly JsonSerializerOptions _jsonOptions = new JsonSerializerOptions
        {
            PropertyNameCaseInsensitive = true
        };

        public static bool IsRunning { get; private set; } = false;
        public static ExternalEvent ExEvent { get; set; }
        public static McpRequestHandler Handler { get; set; }

        static ServerController()
        {
            _httpClient = new HttpClient();
            _httpClient.BaseAddress = new Uri(AZURE_BASE_URL);
            _httpClient.DefaultRequestHeaders.Add("x-api-key", API_KEY);
            _httpClient.Timeout = TimeSpan.FromSeconds(30);
        }

        public static void Start()
        {
            if (IsRunning) return;
            try
            {
                IsRunning = true;
                _cts = new CancellationTokenSource();
                Task.Run(() => PollingLoop(_cts.Token));
            }
            catch (Exception ex)
            {
                TaskDialog.Show("Error", $"No se pudo iniciar el cliente de polling: {ex.Message}");
            }
        }

        public static void Stop()
        {
            if (!IsRunning) return;
            IsRunning = false;
            try 
            { 
                _cts?.Cancel(); 
                _cts?.Dispose();
                _cts = null;
            } 
            catch { }
        }

        private static async Task PollingLoop(CancellationToken token)
        {
            while (IsRunning && !token.IsCancellationRequested)
            {
                try
                {
                    await PollAndExecuteAsync(token);
                }
                catch (TaskCanceledException) { break; }
                catch (Exception)
                {
                    // Ignoramos errores de red temporales para que el polling no se detenga
                    await Task.Delay(2000, token);
                }
                
                // Esperar antes del siguiente poll para no saturar el servidor
                if (!token.IsCancellationRequested)
                {
                    await Task.Delay(1000, token);
                }
            }
        }

        private static async Task PollAndExecuteAsync(CancellationToken token)
        {
            // 1. Preguntar por tareas pendientes
            var response = await _httpClient.GetAsync("/api/poll", token);
            if (!response.IsSuccessStatusCode) return;

            string jsonBody = await response.Content.ReadAsStringAsync();
            using var doc = JsonDocument.Parse(jsonBody);
            
            var root = doc.RootElement;
            if (!root.TryGetProperty("task_id", out var taskIdElement) || taskIdElement.ValueKind == JsonValueKind.Null)
            {
                // No hay tareas pendientes
                return;
            }

            string taskId = taskIdElement.GetString();
            string command = root.GetProperty("command").GetString();
            JsonElement payload = root.GetProperty("payload");

            // 2. Construir la petición para el manejador de Revit
            var mcpRequest = new McpRequest 
            { 
                Command = command, 
                Payload = payload 
            };

            var tcs = new TaskCompletionSource<string>();
            McpRequestHandler.Queue.Enqueue(new PendingTask { Request = mcpRequest, ResponseTask = tcs });

            // 3. Despertar a Revit para procesar la tarea en el hilo principal
            ExEvent.Raise();

            // 4. Esperar la respuesta de Revit
            string resultJson = null;
            string errorMsg = null;
            try
            {
                // Esperar a que Revit resuelva la tarea
                resultJson = await tcs.Task; 
            }
            catch (Exception ex)
            {
                errorMsg = ex.Message;
            }

            // 5. Enviar el resultado de vuelta a Azure
            // C# serializa el resultJson, pero si es un JSON string, en Python debemos deserializarlo.
            // Para simplificar, enviaremos todo como string dentro de 'result' y Python lo parseará si hace falta.
            var taskResult = new
            {
                task_id = taskId,
                result = resultJson,
                error = errorMsg
            };

            string resultPayload = JsonSerializer.Serialize(taskResult, _jsonOptions);
            var content = new StringContent(resultPayload, Encoding.UTF8, "application/json");

            await _httpClient.PostAsync($"/api/result/{taskId}", content, token);
        }
    }
}