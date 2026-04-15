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
                btn.ToolTip = "Servidor detenido.";
            }
            else
            {
                ServerController.Start();
                btn.ItemText = "MCP Server\n(ON)";
                btn.ToolTip = "Escuchando en puerto 5000...";
            }
            return Result.Succeeded;
        }
    }
}