using Autodesk.Revit.Attributes;
using Autodesk.Revit.DB;
using Autodesk.Revit.UI;

namespace RevitMCPBridge
{
    [Transaction(TransactionMode.Manual)]
    public class ToggleServerCommand : IExternalCommand
    {
        public Result Execute(ExternalCommandData commandData, ref string message, ElementSet elements)
        {
            PushButton btn = App.McpButton;

            if (ServerController.IsRunning)
            {
                ServerController.Stop();
                btn.ItemText = "MCP Server\n(OFF)";
                btn.ToolTip = "Servidor detenido. Haz clic para iniciar.";
                btn.LargeImage = App.CreatePowerIcon(isOn: false, size: 32);
                btn.Image = App.CreatePowerIcon(isOn: false, size: 16);
            }
            else
            {
                ServerController.Start();
                btn.ItemText = "MCP Server\n(ON)";
                btn.ToolTip = $"Conectado como: {System.Environment.UserName.ToLower()}";
                btn.LargeImage = App.CreatePowerIcon(isOn: true, size: 32);
                btn.Image = App.CreatePowerIcon(isOn: true, size: 16);
            }
            return Result.Succeeded;
        }
    }
}
