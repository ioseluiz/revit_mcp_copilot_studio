using System;
using System.Collections.Concurrent;
using System.Collections.Generic;
using System.Linq;
using System.Text.Json;
using System.Threading.Tasks;
using Autodesk.Revit.UI;
using Autodesk.Revit.DB;

namespace RevitMCPBridge
{
    public class McpRequest
    {
        public string Command { get; set; }
        public JsonElement Payload { get; set; }
    }

    public class PendingTask
    {
        public McpRequest Request { get; set; }
        public TaskCompletionSource<string> ResponseTask { get; set; }
    }

    // --- NUEVA CLASE PARA SILENCIAR VENTANAS EMERGENTES DE REVIT ---
    public class WarningSwallower : IFailuresPreprocessor
    {
        public FailureProcessingResult PreprocessFailures(FailuresAccessor failuresAccessor)
        {
            IList<FailureMessageAccessor> failures = failuresAccessor.GetFailureMessages();
            foreach (FailureMessageAccessor f in failures)
            {
                if (f.GetSeverity() == FailureSeverity.Warning)
                {
                    failuresAccessor.DeleteWarning(f); // Destruye la advertencia para que no detenga el proceso
                }
            }
            return FailureProcessingResult.Continue;
        }
    }

    public class McpRequestHandler : IExternalEventHandler
    {
        public static ConcurrentQueue<PendingTask> Queue { get; } = new();

        public void Execute(UIApplication app)
        {
            // Validación de seguridad por si no hay un documento abierto
            if (app.ActiveUIDocument == null) return;
            Document doc = app.ActiveUIDocument.Document;

            // Procesar todas las tareas atascadas en la cola
            while (Queue.TryDequeue(out PendingTask currentTask))
            {
                string resultJson = "";

                try
                {
                    switch (currentTask.Request.Command)
                    {
                        case "get_project_info":
                            resultJson = JsonSerializer.Serialize(new
                            {
                                Title = doc.Title,
                                Path = doc.PathName,
                                User = app.Application.Username
                            });
                            break;

                        case "get_elements_with_params":
                            string catName = currentTask.Request.Payload.GetProperty("category").GetString();
                            List<string> paramsToFind = new();

                            if (currentTask.Request.Payload.TryGetProperty("parameters", out JsonElement paramsJson))
                            {
                                foreach (var p in paramsJson.EnumerateArray())
                                    paramsToFind.Add(p.GetString());
                            }

                            if (Enum.TryParse(catName, out BuiltInCategory bic))
                                resultJson = GetElementsAndParams(doc, bic, paramsToFind);
                            else
                                resultJson = JsonSerializer.Serialize(new { error = $"Categoría inválida: {catName}" });
                            break;

                        case "get_concrete_volume":
                            var catsVol = JsonSerializer.Deserialize<string[]>(currentTask.Request.Payload.GetProperty("categories").GetRawText());
                            resultJson = GetTotalVolume(doc, catsVol);
                            break;

                        case "get_levels_info":
                            resultJson = GetLevelsInfo(doc);
                            break;

                        case "get_family_summary":
                            string catSum = currentTask.Request.Payload.GetProperty("category").GetString();
                            if (Enum.TryParse(catSum, out BuiltInCategory bicSum))
                                resultJson = GetFamilyTypeSummary(doc, bicSum);
                            else
                                resultJson = JsonSerializer.Serialize(new { error = $"Categoría inválida: {catSum}" });
                            break;

                        case "create_levels":
                            JsonElement levelsJson = currentTask.Request.Payload.GetProperty("levels");
                            resultJson = CreateLevels(doc, levelsJson);
                            break;

                        case "create_grids":
                            resultJson = CreateGrids(doc, currentTask.Request.Payload);
                            break;

                        case "insert_isolated_footings":
                            resultJson = InsertIsolatedFootings(doc, currentTask.Request.Payload);
                            break;

                        case "get_grids_info":
                            resultJson = GetGridsInfo(doc);
                            break;

                        case "get_material_takeoff":
                            var catsTakeoff = JsonSerializer.Deserialize<string[]>(currentTask.Request.Payload.GetProperty("categories").GetRawText());
                            resultJson = GetMaterialTakeoff(doc, catsTakeoff);
                            break;

                        case "get_doors_windows_summary":
                            resultJson = GetDoorsWindowsSummary(doc);
                            break;

                        case "get_pipes_quantification":
                            resultJson = GetPipesQuantification(doc);
                            break;

                        case "get_plumbing_summary":
                            resultJson = GetFamilyTypeSummary(doc, BuiltInCategory.OST_PlumbingFixtures);
                            break;

                        case "get_structural_columns_weight":
                            resultJson = GetSteelStructureWeight(doc);
                            break;

                        case "get_rebar_quantification":
                            resultJson = GetRebarQuantification(doc);
                            break;

                        default:
                            resultJson = JsonSerializer.Serialize(new { error = "Comando no reconocido" });
                            break;
                    }

                    currentTask.ResponseTask.SetResult(resultJson);
                }
                catch (Exception ex)
                {
                    currentTask.ResponseTask.SetResult(JsonSerializer.Serialize(new { error = ex.Message }));
                }
            }
        }

        // --- MÉTODOS DE CONSULTA (LECTURA) ---

        private static string GetElementsAndParams(Document doc, BuiltInCategory bic, List<string> paramNames)
        {
            var elements = new FilteredElementCollector(doc)
                .OfCategory(bic)
                .WhereElementIsNotElementType()
                .ToElements();

            var list = new List<Dictionary<string, object>>();

            foreach (Element e in elements)
            {
                var data = new Dictionary<string, object>
                {
                    ["Id"] = e.Id.Value,
                    ["Name"] = e.Name,
                    ["Level"] = (e.LevelId != ElementId.InvalidElementId) ? doc.GetElement(e.LevelId)?.Name : "N/A"
                };

                foreach (string paramName in paramNames)
                {
                    data[paramName] = GetParameterValue(e, paramName);
                }

                list.Add(data);
            }

            return JsonSerializer.Serialize(list);
        }

        // Método para obtener la información de los niveles existentes
        private static string GetLevelsInfo(Document doc)
        {
            // Filtramos todos los elementos de tipo Level en el documento
            var levels = new FilteredElementCollector(doc)
                .OfClass(typeof(Level))
                .WhereElementIsNotElementType()
                .Cast<Level>()
                .ToList();

            var list = new List<object>();

            foreach (Level lvl in levels)
            {
                // Revit guarda la elevación en pies. La convertimos a metros y redondeamos a 3 decimales.
                double elevMeters = Math.Round(lvl.Elevation * 0.3048, 3);

                list.Add(new
                {
                    Nombre = lvl.Name,
                    Id = lvl.Id.Value,
                    ElevacionM = elevMeters
                });
            }

            return JsonSerializer.Serialize(list);
        }

        private static string GetTotalVolume(Document doc, string[] categories)
        {
            double totalVolumeCubicFeet = 0;
            var details = new List<object>();

            foreach (string catName in categories)
            {
                if (Enum.TryParse(catName, out BuiltInCategory bic))
                {
                    var elements = new FilteredElementCollector(doc)
                        .OfCategory(bic)
                        .WhereElementIsNotElementType()
                        .ToElements();

                    double catVol = 0;
                    int count = 0;

                    foreach (Element e in elements)
                    {
                        Parameter p = e.get_Parameter(BuiltInParameter.HOST_VOLUME_COMPUTED);
                        if (p != null && p.HasValue)
                        {
                            catVol += p.AsDouble();
                            count++;
                        }
                    }

                    totalVolumeCubicFeet += catVol;
                    details.Add(new { Category = catName, Count = count, VolumeM3 = Math.Round(catVol * 0.0283168, 2) });
                }
            }

            return JsonSerializer.Serialize(new
            {
                TotalVolumeM3 = Math.Round(totalVolumeCubicFeet * 0.0283168, 2),
                Breakdown = details
            });
        }

        private static string GetFamilyTypeSummary(Document doc, BuiltInCategory bic)
        {
            var elements = new FilteredElementCollector(doc).OfCategory(bic).WhereElementIsNotElementType().ToElements();

            var query = elements.GroupBy(e => {
                ElementId typeId = e.GetTypeId();
                if (typeId == ElementId.InvalidElementId) return "Desconocido";

                Element typeElem = doc.GetElement(typeId);
                Parameter p = typeElem?.get_Parameter(BuiltInParameter.SYMBOL_FAMILY_NAME_PARAM);
                return p != null ? p.AsString() : "Desconocido";
            }).Select(g => new
            {
                FamilyName = g.Key,
                Types = g.GroupBy(e => {
                    ElementId typeId = e.GetTypeId();
                    return typeId != ElementId.InvalidElementId ? doc.GetElement(typeId)?.Name ?? "Sin Tipo" : "Sin Tipo";
                }).Select(t => new { TypeName = t.Key, Count = t.Count() }).ToList()
            });

            return JsonSerializer.Serialize(query);
        }

        private static string GetGridsInfo(Document doc)
        {
            var grids = new FilteredElementCollector(doc).OfClass(typeof(Grid)).WhereElementIsNotElementType().Cast<Grid>().ToList();
            var list = new List<object>();

            foreach (Grid g in grids)
            {
                if (g.Curve is Line line)
                {
                    XYZ p1 = line.GetEndPoint(0);
                    XYZ p2 = line.GetEndPoint(1);

                    list.Add(new
                    {
                        Nombre = g.Name,
                        Id = g.Id.Value,
                        StartP_M = new { X = Math.Round(p1.X * 0.3048, 3), Y = Math.Round(p1.Y * 0.3048, 3) },
                        EndP_M = new { X = Math.Round(p2.X * 0.3048, 3), Y = Math.Round(p2.Y * 0.3048, 3) }
                    });
                }
                else
                {
                    list.Add(new { Nombre = g.Name, Id = g.Id.Value, Info = "Eje curvo" });
                }
            }
            return JsonSerializer.Serialize(list);
        }

        private static string GetParameterValue(Element e, string paramName)
        {
            Parameter p = e.LookupParameter(paramName);
            if (p != null && p.HasValue) return p.AsValueString() ?? p.AsString();

            ElementId typeId = e.GetTypeId();
            if (typeId != ElementId.InvalidElementId)
            {
                p = e.Document.GetElement(typeId)?.LookupParameter(paramName);
                if (p != null && p.HasValue) return p.AsValueString() ?? p.AsString();
            }
            return "";
        }

        // --- MÉTODOS DE ESCRITURA (TRANSACCIONES) ---

        private static string CreateLevels(Document doc, JsonElement levelsJson)
        {
            var results = new List<object>();

            using (Transaction trans = new Transaction(doc, "MCP: Crear Niveles"))
            {
                trans.Start();
                try
                {
                    var existingLevelsNames = new FilteredElementCollector(doc)
                        .OfClass(typeof(Level))
                        .Cast<Level>()
                        .Select(l => l.Name.ToLower())
                        .ToHashSet();

                    foreach (JsonElement levelData in levelsJson.EnumerateArray())
                    {
                        string name = levelData.GetProperty("nombre").GetString();
                        double elevMeters = levelData.GetProperty("elevacion").GetDouble();

                        if (existingLevelsNames.Contains(name.ToLower()))
                        {
                            results.Add(new { Nombre = name, Estado = "Error", Mensaje = "Ya existe." });
                            continue;
                        }

                        Level newLevel = Level.Create(doc, elevMeters / 0.3048);
                        newLevel.Name = name;
                        existingLevelsNames.Add(name.ToLower());

                        results.Add(new { Nombre = name, ElevacionM = elevMeters, Estado = "Creado", Id = newLevel.Id.Value });
                    }
                    trans.Commit();
                }
                catch (Exception ex)
                {
                    trans.RollBack();
                    return JsonSerializer.Serialize(new { error = "Fallo en transacción: " + ex.Message });
                }
            }
            return JsonSerializer.Serialize(results);
        }

        private static string CreateGrids(Document doc, JsonElement payload)
        {
            var results = new List<object>();
            var verts = payload.GetProperty("verticals").EnumerateArray().ToList();
            var horiz = payload.GetProperty("horizontals").EnumerateArray().ToList();

            double defaultLen = 32.8;
            double margin = 6.56;

            var vPos = verts.Select(x => x.GetProperty("posicion").GetDouble() / 0.3048).ToList();
            var hPos = horiz.Select(x => x.GetProperty("posicion").GetDouble() / 0.3048).ToList();

            double minX = vPos.Any() ? vPos.Min() : 0;
            double maxX = vPos.Any() ? vPos.Max() : defaultLen;
            double minY = hPos.Any() ? hPos.Min() : 0;
            double maxY = hPos.Any() ? hPos.Max() : defaultLen;

            double startX = minX - margin;
            double endX = maxX + margin;
            double startY = minY - margin;
            double endY = maxY + margin;

            using (Transaction trans = new Transaction(doc, "MCP: Crear Ejes"))
            {
                trans.Start();
                try
                {
                    var existingNames = new FilteredElementCollector(doc).OfClass(typeof(Grid)).Cast<Grid>().Select(g => g.Name).ToHashSet();

                    foreach (var item in verts)
                    {
                        string name = item.GetProperty("nombre").GetString();
                        double xFt = item.GetProperty("posicion").GetDouble() / 0.3048;

                        if (existingNames.Contains(name)) continue;

                        try
                        {
                            Grid g = Grid.Create(doc, Line.CreateBound(new XYZ(xFt, startY, 0), new XYZ(xFt, endY, 0)));
                            g.Name = name;
                            existingNames.Add(name);
                            results.Add(new { Nombre = name, Estado = "Creado" });
                        }
                        catch (Exception ex) { results.Add(new { Nombre = name, Estado = "Error", Mensaje = ex.Message }); }
                    }

                    foreach (var item in horiz)
                    {
                        string name = item.GetProperty("nombre").GetString();
                        double yFt = item.GetProperty("posicion").GetDouble() / 0.3048;

                        if (existingNames.Contains(name)) continue;

                        try
                        {
                            Grid g = Grid.Create(doc, Line.CreateBound(new XYZ(startX, yFt, 0), new XYZ(endX, yFt, 0)));
                            g.Name = name;
                            existingNames.Add(name);
                            results.Add(new { Nombre = name, Estado = "Creado" });
                        }
                        catch (Exception ex) { results.Add(new { Nombre = name, Estado = "Error", Mensaje = ex.Message }); }
                    }
                    trans.Commit();
                }
                catch (Exception ex)
                {
                    trans.RollBack();
                    return JsonSerializer.Serialize(new { error = "Fallo en transacción: " + ex.Message });
                }
            }
            return JsonSerializer.Serialize(results);
        }

        private static string InsertIsolatedFootings(Document doc, JsonElement payload)
        {
            var results = new List<object>();

            string familyName = payload.GetProperty("familia").GetString();
            string typeName = payload.GetProperty("tipo").GetString();
            string levelName = payload.GetProperty("nivel").GetString();

            bool useBottomElevation = true;
            if (payload.TryGetProperty("usar_elevacion_fondo", out JsonElement ube))
                useBottomElevation = ube.GetBoolean();

            var points = payload.GetProperty("zapatas").EnumerateArray().ToList();

            using (Transaction trans = new Transaction(doc, "MCP: Insertar Zapatas Aisladas"))
            {
                trans.Start();

                // Conectar el silenciador de advertencias a la transacción
                FailureHandlingOptions failOpt = trans.GetFailureHandlingOptions();
                failOpt.SetFailuresPreprocessor(new WarningSwallower());
                trans.SetFailureHandlingOptions(failOpt);

                try
                {
                    FamilySymbol symbol = new FilteredElementCollector(doc)
                        .OfClass(typeof(FamilySymbol))
                        .OfCategory(BuiltInCategory.OST_StructuralFoundation)
                        .Cast<FamilySymbol>()
                        .FirstOrDefault(x => x.FamilyName.Equals(familyName, StringComparison.OrdinalIgnoreCase) &&
                                             x.Name.Equals(typeName, StringComparison.OrdinalIgnoreCase));

                    if (symbol == null)
                    {
                        trans.RollBack();
                        return JsonSerializer.Serialize(new { error = $"No se encontró el tipo '{typeName}' en la familia '{familyName}'." });
                    }

                    if (!symbol.IsActive)
                    {
                        symbol.Activate();
                        doc.Regenerate();
                    }

                    Level level = new FilteredElementCollector(doc)
                        .OfClass(typeof(Level))
                        .Cast<Level>()
                        .FirstOrDefault(l => l.Name.Equals(levelName, StringComparison.OrdinalIgnoreCase));

                    if (level == null)
                    {
                        trans.RollBack();
                        return JsonSerializer.Serialize(new { error = $"No se encontró el nivel '{levelName}'." });
                    }

                    double thicknessFt = 0;
                    if (useBottomElevation)
                    {
                        Parameter thickParam = symbol.get_Parameter(BuiltInParameter.STRUCTURAL_FOUNDATION_THICKNESS);
                        if (thickParam != null && thickParam.HasValue) thicknessFt = thickParam.AsDouble();
                    }

                    foreach (var pt in points)
                    {
                        double xM = pt.GetProperty("x").GetDouble();
                        double yM = pt.GetProperty("y").GetDouble();

                        double offsetM = 0;
                        if (pt.TryGetProperty("offset_z", out JsonElement oz)) offsetM = oz.GetDouble();

                        double xFt = xM / 0.3048;
                        double yFt = yM / 0.3048;
                        double offsetFt = offsetM / 0.3048;

                        if (useBottomElevation) offsetFt += thicknessFt;

                        try
                        {
                            FamilyInstance fi = doc.Create.NewFamilyInstance(new XYZ(xFt, yFt, 0), symbol, level, Autodesk.Revit.DB.Structure.StructuralType.Footing);

                            Parameter offsetParam = fi.get_Parameter(BuiltInParameter.INSTANCE_FREE_HOST_OFFSET_PARAM);
                            if (offsetParam != null && !offsetParam.IsReadOnly) offsetParam.Set(offsetFt);

                            results.Add(new { X = xM, Y = yM, Estado = "Creado", Id = fi.Id.Value });
                        }
                        catch (Exception exIns) { results.Add(new { X = xM, Y = yM, Estado = "Error", Mensaje = exIns.Message }); }
                    }
                    trans.Commit();
                }
                catch (Exception ex)
                {
                    trans.RollBack();
                    return JsonSerializer.Serialize(new { error = "Fallo en transacción: " + ex.Message });
                }
            }
            return JsonSerializer.Serialize(results);
        }

        private static string GetMaterialTakeoff(Document doc, string[] categories)
        {
            var report = new List<object>();

            foreach (string catName in categories)
            {
                if (Enum.TryParse(catName, out BuiltInCategory bic))
                {
                    var elements = new FilteredElementCollector(doc)
                        .OfCategory(bic)
                        .WhereElementIsNotElementType()
                        .ToElements();

                    foreach (Element e in elements)
                    {
                        var materialInfo = new List<object>();

                        // Obtener IDs de materiales aplicados al elemento
                        ICollection<ElementId> matIds = e.GetMaterialIds(false);

                        foreach (ElementId mId in matIds)
                        {
                            Material mat = doc.GetElement(mId) as Material;
                            if (mat == null) continue;

                            // Revit devuelve áreas en SqFt y volúmenes en CuFt.
                            // Conversión: SqFt * 0.092903 = m2 | CuFt * 0.028317 = m3
                            double areaM2 = e.GetMaterialArea(mId, false) * 0.092903;
                            double volumeM3 = e.GetMaterialVolume(mId) * 0.028317;

                            if (areaM2 > 0 || volumeM3 > 0)
                            {
                                materialInfo.Add(new
                                {
                                    MaterialName = mat.Name,
                                    AreaM2 = Math.Round(areaM2, 2),
                                    VolumeM3 = Math.Round(volumeM3, 3)
                                });
                            }
                        }

                        if (materialInfo.Count > 0)
                        {
                            report.Add(new
                            {
                                Id = e.Id.Value,
                                Category = catName.Replace("OST_", ""),
                                ElementName = e.Name,
                                Materials = materialInfo
                            });
                        }
                    }
                }
            }
            return JsonSerializer.Serialize(report);
        }

        private static string GetDoorsWindowsSummary(Document doc)
        {
            var categories = new List<BuiltInCategory> { BuiltInCategory.OST_Doors, BuiltInCategory.OST_Windows };
            var result = new Dictionary<string, object>();

            foreach (var bic in categories)
            {
                var elements = new FilteredElementCollector(doc).OfCategory(bic).WhereElementIsNotElementType().ToElements();

                var categorySummary = elements.GroupBy(e => {
                    ElementId typeId = e.GetTypeId();
                    Element typeElem = doc.GetElement(typeId);
                    Parameter p = typeElem?.get_Parameter(BuiltInParameter.SYMBOL_FAMILY_NAME_PARAM);
                    return p?.AsString() ?? "Desconocido";
                }).Select(g => new
                {
                    FamilyName = g.Key,
                    Types = g.GroupBy(e => {
                        ElementId typeId = e.GetTypeId();
                        return doc.GetElement(typeId)?.Name ?? "Sin Tipo";
                    }).Select(t => {
                        Element firstElem = t.First();
                        Element typeElem = doc.GetElement(firstElem.GetTypeId());

                        // Intentamos obtener dimensiones comunes
                        string width = GetParameterValue(typeElem, "Width") ?? GetParameterValue(typeElem, "Ancho") ?? "";
                        string height = GetParameterValue(typeElem, "Height") ?? GetParameterValue(typeElem, "Alto") ?? "";

                        return new
                        {
                            TypeName = t.Key,
                            Count = t.Count(),
                            Dimensions = (string.IsNullOrEmpty(width) || string.IsNullOrEmpty(height)) ? "N/A" : $"{width} x {height}"
                        };
                    }).ToList()
                }).ToList();

                result[bic.ToString().Replace("OST_", "")] = categorySummary;
            }

            return JsonSerializer.Serialize(result);
        }

        private static string GetPipesQuantification(Document doc)
        {
            // Filtramos la categoría de tuberías
            var pipes = new FilteredElementCollector(doc)
                .OfCategory(BuiltInCategory.OST_PipeCurves)
                .WhereElementIsNotElementType()
                .ToElements();

            var summary = pipes.GroupBy(p => {
                ElementId typeId = p.GetTypeId();
                Element typeElem = doc.GetElement(typeId);
                Parameter famParam = typeElem?.get_Parameter(BuiltInParameter.SYMBOL_FAMILY_NAME_PARAM);
                string family = famParam?.AsString() ?? "Desconocida";
                return $"{family} : {p.Name}";
            }).Select(g => {
                double totalLengthFt = 0;
                foreach (Element e in g)
                {
                    Parameter pLen = e.get_Parameter(BuiltInParameter.CURVE_ELEM_LENGTH);
                    if (pLen != null && pLen.HasValue) totalLengthFt += pLen.AsDouble();
                }

                return new
                {
                    TypeDescription = g.Key,
                    Count = g.Count(),
                    TotalLengthM = Math.Round(totalLengthFt * 0.3048, 2) // Pies a Metros
                };
            }).ToList();

            return JsonSerializer.Serialize(summary);
        }

        private static string GetSteelStructureWeight(Document doc)
        {
            var categories = new List<BuiltInCategory> { 
                BuiltInCategory.OST_StructuralColumns, 
                BuiltInCategory.OST_StructuralFraming 
            };

            var elements = new List<Element>();
            foreach (var bic in categories)
            {
                elements.AddRange(new FilteredElementCollector(doc)
                    .OfCategory(bic)
                    .WhereElementIsNotElementType()
                    .ToElements());
            }

            var summary = elements.GroupBy(e => {
                ElementId typeId = e.GetTypeId();
                Element typeElem = doc.GetElement(typeId);
                Parameter famParam = typeElem?.get_Parameter(BuiltInParameter.SYMBOL_FAMILY_NAME_PARAM);
                string catName = e.Category.Name;
                return $"[{catName}] {famParam?.AsString() ?? "Desconocida"} : {e.Name}";
            }).Select(g => {
                double totalWeightTon = 0;
                foreach (Element e in g)
                {
                    Parameter volParam = e.get_Parameter(BuiltInParameter.HOST_VOLUME_COMPUTED);
                    if (volParam != null && volParam.HasValue)
                    {
                        double volCuFt = volParam.AsDouble();
                        double volM3 = volCuFt * 0.0283168;

                        double density = 7850; // Acero por defecto

                        ElementId matId = e.GetMaterialIds(false).FirstOrDefault();
                        if (matId != null)
                        {
                            Material mat = doc.GetElement(matId) as Material;
                            if (mat != null)
                            {
                                string matName = mat.Name.ToLower();
                                if (matName.Contains("aluminio") || matName.Contains("aluminum"))
                                    density = 2710;
                                else if (matName.Contains("concreto") || matName.Contains("concrete"))
                                    continue;
                            }
                        }
                        totalWeightTon += (volM3 * density) / 1000.0;
                    }
                }

                return new
                {
                    TypeDescription = g.Key,
                    Count = g.Count(),
                    TotalWeightTon = Math.Round(totalWeightTon, 3)
                };
            }).Where(x => x.TotalWeightTon > 0).ToList();

            return JsonSerializer.Serialize(summary);
        }

        private static string GetRebarQuantification(Document doc)
        {
            var rebars = new FilteredElementCollector(doc)
                .OfCategory(BuiltInCategory.OST_Rebar)
                .WhereElementIsNotElementType()
                .ToElements();

            var summary = rebars.GroupBy(r => {
                ElementId typeId = r.GetTypeId();
                return doc.GetElement(typeId)?.Name ?? "Sin Tipo";
            }).Select(g => {
                double totalLengthFt = 0;
                double totalWeightKg = 0;

                foreach (Element e in g)
                {
                    Parameter pLen = e.get_Parameter(BuiltInParameter.REBAR_ELEM_LENGTH);
                    if (pLen != null && pLen.HasValue)
                    {
                        double lenFt = pLen.AsDouble();
                        totalLengthFt += lenFt;

                        Parameter pVol = e.get_Parameter(BuiltInParameter.HOST_VOLUME_COMPUTED);
                        if (pVol != null && pVol.HasValue && pVol.AsDouble() > 0)
                        {
                            totalWeightKg += (pVol.AsDouble() * 0.0283168) * 7850;
                        }
                    }
                }

                return new
                {
                    RebarType = g.Key,
                    Count = g.Count(),
                    TotalLengthM = Math.Round(totalLengthFt * 0.3048, 2),
                    TotalWeightTon = Math.Round(totalWeightKg / 1000.0, 3)
                };
            }).ToList();

            return JsonSerializer.Serialize(summary);
        }

        public string GetName() => "Mcp Handler v2.3";
    }
}