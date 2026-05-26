using System.IO;
using System.Reflection;
using System.Windows.Media.Imaging;
using Autodesk.Revit.UI;

namespace RevitMCPBridge
{
    public class App : IExternalApplication
    {
        public static PushButton McpButton { get; private set; }

        public Result OnStartup(UIControlledApplication application)
        {
            // Cargar config.json antes de inicializar el servidor
            PluginConfig.Load();

            ServerController.Handler = new McpRequestHandler();
            ServerController.ExEvent = ExternalEvent.Create(ServerController.Handler);

            string tabName = "INIO IA Assistant";
            try { application.CreateRibbonTab(tabName); } catch { }
            RibbonPanel panel = application.CreateRibbonPanel(tabName, "Conexión");

            string path = Assembly.GetExecutingAssembly().Location;
            PushButtonData btnData = new PushButtonData(
                "btnMcp", "MCP Server\n(OFF)", path, "RevitMCPBridge.ToggleServerCommand");

            McpButton = panel.AddItem(btnData) as PushButton;
            McpButton.ToolTip = $"Servidor: {PluginConfig.AzureBaseUrl}\nHaz clic para activar el puente MCP.";
            McpButton.LargeImage = CreatePowerIcon(isOn: false, size: 32);
            McpButton.Image = CreatePowerIcon(isOn: false, size: 16);

            return Result.Succeeded;
        }

        public Result OnShutdown(UIControlledApplication application)
        {
            ServerController.Stop();
            return Result.Succeeded;
        }

        /// <summary>
        /// Genera un icono de botón de encendido en runtime.
        /// Verde = ON, gris = OFF. No requiere archivos de imagen externos.
        /// </summary>
        internal static BitmapImage CreatePowerIcon(bool isOn, int size)
        {
            var ms = new MemoryStream();

            using (var bmp = new System.Drawing.Bitmap(size, size))
            {
                using (var g = System.Drawing.Graphics.FromImage(bmp))
                {
                    g.SmoothingMode = System.Drawing.Drawing2D.SmoothingMode.AntiAlias;
                    g.Clear(System.Drawing.Color.Transparent);

                    var bgColor = isOn
                        ? System.Drawing.Color.FromArgb(40, 167, 69)   // verde
                        : System.Drawing.Color.FromArgb(90, 90, 90);   // gris oscuro

                    var borderColor = isOn
                        ? System.Drawing.Color.FromArgb(30, 130, 50)
                        : System.Drawing.Color.FromArgb(55, 55, 55);

                    using (var bgBrush = new System.Drawing.SolidBrush(bgColor))
                        g.FillEllipse(bgBrush, 1, 1, size - 3, size - 3);

                    using (var borderPen = new System.Drawing.Pen(borderColor, (float)(size * 0.06)))
                        g.DrawEllipse(borderPen, 1, 1, size - 3, size - 3);

                    float cx = size / 2f;
                    float cy = size / 2f;
                    float sw = Math.Max(1.5f, size * 0.09f);

                    using (var pen = new System.Drawing.Pen(System.Drawing.Color.White, sw))
                    {
                        pen.StartCap = System.Drawing.Drawing2D.LineCap.Round;
                        pen.EndCap = System.Drawing.Drawing2D.LineCap.Round;

                        // Línea vertical superior (gap del arco)
                        g.DrawLine(pen, cx, cy - size * 0.38f, cx, cy - size * 0.04f);

                        // Arco de 270° con gap de 90° arriba
                        float ar = size * 0.26f;
                        g.DrawArc(pen,
                            new System.Drawing.RectangleF(cx - ar, cy - ar, ar * 2, ar * 2),
                            135f, 270f);
                    }
                }
                // Graphics disposed → bitmap flushed
                bmp.Save(ms, System.Drawing.Imaging.ImageFormat.Png);
            }

            ms.Position = 0;
            var img = new BitmapImage();
            img.BeginInit();
            img.StreamSource = ms;
            img.CacheOption = BitmapCacheOption.OnLoad; // copia los bytes en memoria
            img.EndInit();
            img.Freeze();
            ms.Dispose();
            return img;
        }
    }
}
