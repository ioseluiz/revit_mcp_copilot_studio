using System.Reflection;
using Autodesk.Revit.UI;

namespace RevitMCPBridge
{
    public class App : IExternalApplication
    {
        public static PushButton McpButton { get; private set; }

        public Result OnStartup(UIControlledApplication application)
        {
            // Inicializar el evento externo
            ServerController.Handler = new McpRequestHandler();
            ServerController.ExEvent = ExternalEvent.Create(ServerController.Handler);

            // Crear pestaña y panel
            string tabName = "INIO IA Assistant";
            try { application.CreateRibbonTab(tabName); } catch { }
            RibbonPanel panel = application.CreateRibbonPanel(tabName, "Conexión");

            // Crear botón
            string path = Assembly.GetExecutingAssembly().Location;
            PushButtonData btnData = new PushButtonData("btnMcp", "MCP Server\n(OFF)", path, "RevitMCPBridge.ToggleServerCommand");

            McpButton = panel.AddItem(btnData) as PushButton;
            McpButton.ToolTip = "Inicia el puente para Claude Desktop";

            return Result.Succeeded;
        }

        public Result OnShutdown(UIControlledApplication application)
        {
            ServerController.Stop();
            return Result.Succeeded;
        }
    }
}