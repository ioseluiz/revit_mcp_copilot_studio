using System;
using System.Net.Http;
using System.Text;
using System.Text.Json;
using System.Threading;
using System.Threading.Tasks;
using Autodesk.Revit.UI;

namespace RevitMCPBridge
{
    public static class ServerController
    {
        private static readonly string CurrentUser = Environment.UserName.ToLower();

        private static HttpClient _httpClient;
        private static CancellationTokenSource _cts;

        private static readonly JsonSerializerOptions _jsonOptions = new JsonSerializerOptions
        {
            PropertyNameCaseInsensitive = true
        };

        public static bool IsRunning { get; private set; } = false;
        public static ExternalEvent ExEvent { get; set; }
        public static McpRequestHandler Handler { get; set; }

        public static void Start()
        {
            if (IsRunning) return;
            try
            {
                // Crear HttpClient con los valores actuales del config (leídos en App.OnStartup)
                _httpClient?.Dispose();
                _httpClient = new HttpClient
                {
                    BaseAddress = new Uri(PluginConfig.AzureBaseUrl),
                    Timeout = TimeSpan.FromSeconds(30)
                };
                _httpClient.DefaultRequestHeaders.Add("x-api-key", PluginConfig.ApiKey);

                IsRunning = true;
                _cts = new CancellationTokenSource();
                Task.Run(() => PollingLoop(_cts.Token));
            }
            catch (Exception ex)
            {
                Autodesk.Revit.UI.TaskDialog.Show("Error MCP", $"No se pudo iniciar el cliente de polling:\n{ex.Message}");
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
                    // Errores de red temporales: esperar y reintentar
                    await Task.Delay(2000, token);
                }

                if (!token.IsCancellationRequested)
                    await Task.Delay(1000, token);
            }
        }

        private static async Task PollAndExecuteAsync(CancellationToken token)
        {
            var response = await _httpClient.GetAsync($"/api/poll/{CurrentUser}", token);
            if (!response.IsSuccessStatusCode) return;

            string jsonBody = await response.Content.ReadAsStringAsync();
            using var doc = JsonDocument.Parse(jsonBody);
            var root = doc.RootElement;

            if (!root.TryGetProperty("task_id", out var taskIdEl) || taskIdEl.ValueKind == JsonValueKind.Null)
                return;

            string taskId = taskIdEl.GetString();
            string command = root.GetProperty("command").GetString();
            JsonElement payload = root.GetProperty("payload");

            var mcpRequest = new McpRequest { Command = command, Payload = payload };
            var tcs = new TaskCompletionSource<string>();
            McpRequestHandler.Queue.Enqueue(new PendingTask { Request = mcpRequest, ResponseTask = tcs });

            ExEvent.Raise();

            string resultJson = null;
            string errorMsg = null;
            try
            {
                resultJson = await tcs.Task;
            }
            catch (Exception ex)
            {
                errorMsg = ex.Message;
            }

            var taskResult = new { task_id = taskId, result = resultJson, error = errorMsg };
            string resultPayload = JsonSerializer.Serialize(taskResult, _jsonOptions);
            var content = new StringContent(resultPayload, Encoding.UTF8, "application/json");

            await _httpClient.PostAsync($"/api/result/{taskId}", content, token);
        }
    }
}
