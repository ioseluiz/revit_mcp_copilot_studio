from fastmcp import FastMCP
import httpx
from typing import List, Dict, Any

# Inicializamos el servidor
mcp = FastMCP("INIO Revit 2025 Assistant")

# IMPORTANTE: Esta es la URL exacta que definimos en el C# (ServerController.cs)
# Nota la barra al final y que dice 'mcp', no 'api'
REVIT_BRIDGE_URL = "http://localhost:5000/mcp/"


@mcp.tool()
async def obtener_elementos_con_datos(tipo_elemento: str) -> str:
    """
    Obtiene elementos del modelo incluyendo sus parámetros de gestión de obra.
    Busca: codigo_cronograma, codigo_actividad, costo_unitario, division, master format.
    
    Args:
        tipo_elemento: 'columnas', 'cimentacion', 'vigas', 'pisos', 'muros', 'puertas', 'ventanas'.
    """
    
    # 1. Definir qué categoría de Revit queremos
    mapa_categorias = {
        "columnas": "OST_StructuralColumns",
        "cimentacion": "OST_StructuralFoundation",
        "vigas": "OST_StructuralFraming",
        "pisos": "OST_Floors",
        "muros": "OST_Walls",
        "puertas": "OST_Doors",
        "ventanas": "OST_Windows"
    }
    
    clave = tipo_elemento.lower()
    if clave not in mapa_categorias:
        return f"Error: Categoría '{tipo_elemento}' no configurada."

    categoria_tecnica = mapa_categorias[clave]

    # 2. Definir qué parámetros queremos leer (Exactamente como se llaman en Revit)
    # Nota: Revit es sensible a mayúsculas/minúsculas. Asegúrate de escribirlos bien.
    parametros_a_buscar = [
        "codigo_cronograma", 
        "codigo_actividad", 
        "costo_unitario", 
        "division", 
        "master format",
        "Assembly Code",  # A veces el MasterFormat nativo se llama así en inglés
        "Keynote"         # Otro común para códigos
    ]

    try:
        async with httpx.AsyncClient() as client:
            payload = {
                "Command": "get_elements_with_params", # Nuevo comando en C#
                "Payload": {
                    "category": categoria_tecnica,
                    "parameters": parametros_a_buscar
                }
            }
            
            resp = await client.post(REVIT_BRIDGE_URL, json=payload, timeout=60.0) # Timeout más largo por si son muchos datos
            resp.raise_for_status()
            
            # Procesar un poco la respuesta para Claude
            data = resp.json()
            
            # Filtramos para mostrar solo elementos que tengan ALGUN dato relevante (opcional)
            # Para no llenar el chat de elementos vacíos si hay miles.
            elementos_con_datos = []
            for item in data:
                # Chequeamos si alguno de los parámetros importantes tiene valor
                tiene_dato = any(item.get(p) for p in parametros_a_buscar)
                if tiene_dato:
                    elementos_con_datos.append(item)
            
            if not elementos_con_datos:
                return f"Se encontraron {len(data)} elementos de tipo '{tipo_elemento}', pero ninguno tiene los parámetros solicitados ({', '.join(parametros_a_buscar)}) rellenos."
                
            return f"Se encontraron {len(elementos_con_datos)} elementos con datos relevantes (mostrando muestra):\n{str(elementos_con_datos[:20])} \n...(y más)"

    except Exception as e:
        return f"Error obteniendo datos: {str(e)}"

@mcp.tool()
async def obtener_info_proyecto() -> str:
    """
    Obtiene información general del proyecto de Revit abierto actualmente.
    Retorna detalles como nombre del archivo, ubicación y usuario.
    """
    try:
        async with httpx.AsyncClient() as client:
            # Estructura que espera el C# (McpRequest)
            payload = {
                "Command": "get_project_info",  # Debe coincidir con el switch en McpRequestHandler.cs
                "Payload": {}                   # Payload vacío porque no requiere argumentos
            }
            
            # En C# usamos HttpListener que recibe POST en la raiz del contexto
            resp = await client.post(REVIT_BRIDGE_URL, json=payload, timeout=10.0)
            
            # Si el servidor C# devuelve 500 o 404, esto lanzará error
            resp.raise_for_status()
            
            return resp.text
    except Exception as e:
        return f"Error conectando con Revit: {str(e)}. Asegúrate de que el botón en Revit esté en (ON)."

@mcp.tool()
async def listar_muros() -> str:
    """
    Lista los muros en el modelo actual.
    """
    try:
        async with httpx.AsyncClient() as client:
            payload = {
                "Command": "get_walls", # Debe coincidir con el switch en McpRequestHandler.cs
                "Payload": {}
            }
            
            resp = await client.post(REVIT_BRIDGE_URL, json=payload, timeout=30.0)
            resp.raise_for_status()
            
            return resp.text
    except Exception as e:
        return f"Error obteniendo muros: {str(e)}"
    

@mcp.tool()
async def listar_elementos_estructurales(tipo_elemento: str) -> str:
    """
    Lista elementos estructurales del modelo.
    
    Args:
        tipo_elemento: El tipo de elemento a buscar. Opciones válidas:
                       'columnas' (para Structural Columns),
                       'cimentacion' (para Structural Foundations),
                       'vigas' (para Structural Framing),
                       'pisos' (para Floors).
    """
    # Mapeo de lenguaje natural a lenguaje técnico de Revit (BuiltInCategory)
    mapa_categorias = {
        "columnas": "OST_StructuralColumns",
        "cimentacion": "OST_StructuralFoundation",
        "vigas": "OST_StructuralFraming",
        "pisos": "OST_Floors",
        "muros": "OST_Walls"
    }
    
    # Normalizamos la entrada (minusculas)
    clave = tipo_elemento.lower()
    
    if clave not in mapa_categorias:
        return f"Error: Tipo '{tipo_elemento}' no soportado. Usa: columnas, cimentacion, vigas, pisos."

    categoria_tecnica = mapa_categorias[clave]

    try:
        async with httpx.AsyncClient() as client:
            payload = {
                "Command": "get_elements_by_category",
                "Payload": {
                    "category": categoria_tecnica
                }
            }
            
            resp = await client.post(REVIT_BRIDGE_URL, json=payload, timeout=30.0)
            resp.raise_for_status()
            
            # Si la respuesta es muy larga, Claude puede cortarse. 
            # Devolvemos un resumen si hay demasiados elementos, o el JSON directo.
            data = resp.json()
            cantidad = len(data)
            return f"Se encontraron {cantidad} elementos de tipo '{tipo_elemento}':\n{resp.text}"

    except Exception as e:
        return f"Error obteniendo elementos: {str(e)}"
    

@mcp.tool()
async def calcular_volumen_concreto(elementos: List[str]) -> str:
    """
    Calcula el volumen total de concreto (hormigón) en metros cúbicos para las categorías solicitadas.
    Ideal para estimaciones rápidas de material.
    
    Args:
        elementos: Lista de categorías a sumar. Opciones: ['columnas', 'vigas', 'pisos', 'cimentacion', 'muros'].
                   Si se deja vacío, calcula todo lo estructural.
    """
    mapa = {
        "columnas": "OST_StructuralColumns",
        "cimentacion": "OST_StructuralFoundation",
        "vigas": "OST_StructuralFraming",
        "pisos": "OST_Floors",
        "muros": "OST_Walls"
    }
    
    cats_to_send = []
    
    # Si la lista está vacía o es None, asumimos todo
    if not elementos:
        cats_to_send = list(mapa.values())
    else:
        for e in elementos:
            if e.lower() in mapa:
                cats_to_send.append(mapa[e.lower()])
    
    if not cats_to_send:
        return "Error: Ninguna categoría válida seleccionada."

    try:
        async with httpx.AsyncClient() as client:
            payload = {
                "Command": "get_concrete_volume",
                "Payload": {
                    "categories": cats_to_send
                }
            }
            resp = await client.post(REVIT_BRIDGE_URL, json=payload, timeout=60.0)
            resp.raise_for_status()
            
            data = resp.json()
            # Formateamos bonito para Claude
            texto = f"📦 **Reporte de Volumen de Concreto**\n"
            texto += f"**Total General:** {data['TotalVolumeM3']} m³\n\n"
            texto += "Desglose por categoría:\n"
            for item in data['Breakdown']:
                texto += f"- {item['Category']}: {item['Count']} elementos | {item['VolumeM3']} m³\n"
            
            return texto

    except Exception as e:
        return f"Error calculando volúmenes: {str(e)}"

@mcp.tool()
async def inventario_por_familia(categoria: str) -> str:
    """
    Genera un resumen cuantitativo agrupado por Familia y Tipo.
    Útil para conteo de puertas, ventanas, luminarias o equipos mecánicos para presupuestos.
    
    Args:
        categoria: 'puertas', 'ventanas', 'muros', 'mobiliario', 'equipos', 'fontaneria'.
    """
    mapa = {
        "puertas": "OST_Doors",
        "ventanas": "OST_Windows",
        "muros": "OST_Walls",
        "mobiliario": "OST_Furniture",
        "equipos": "OST_MechanicalEquipment",
        "fontaneria": "OST_PlumbingFixtures",
        "columnas": "OST_StructuralColumns"
    }
    
    clave = categoria.lower()
    if clave not in mapa:
        return f"Error: Categoría '{categoria}' no soportada en esta tool."
        
    try:
        async with httpx.AsyncClient() as client:
            payload = {
                "Command": "get_family_summary",
                "Payload": {
                    "category": mapa[clave]
                }
            }
            resp = await client.post(REVIT_BRIDGE_URL, json=payload, timeout=45.0)
            resp.raise_for_status()
            
            data = resp.json()
            
            if not data:
                return f"No se encontraron elementos en la categoría {categoria}."
                
            texto = f"📊 **Inventario de {categoria.capitalize()}**\n"
            for familia in data:
                texto += f"\n🔹 **Familia: {familia['FamilyName']}**\n"
                for tipo in familia['Types']:
                    texto += f"   - Tipo: {tipo['TypeName']} | Cantidad: {tipo['Count']}\n"
            
            return texto

    except Exception as e:
        return f"Error generando inventario: {str(e)}"
    

@mcp.tool()
async def obtener_informacion_ejes() -> str:
    """
    Obtiene la lista de ejes (grids) existentes en el modelo junto con sus coordenadas de inicio y fin en metros.
    Útil para identificar intersecciones y saber dónde colocar elementos estructurales como zapatas o columnas.
    """
    try:
        async with httpx.AsyncClient() as client:
            payload = {
                "Command": "get_grids_info",
                "Payload": {} # No necesitamos enviarle datos
            }
            resp = await client.post(REVIT_BRIDGE_URL, json=payload, timeout=30.0)
            resp.raise_for_status()
            
            data = resp.json()
            
            if isinstance(data, dict) and "error" in data:
                return f"❌ Error desde Revit: {data['error']}"
                
            if not data:
                return "No se encontraron ejes (grids) en el proyecto actual."
            
            texto = "📐 **Información de Ejes (Grids) Existentes:**\n"
            for item in data:
                if "StartP_M" in item:
                    x1, y1 = item['StartP_M']['X'], item['StartP_M']['Y']
                    x2, y2 = item['EndP_M']['X'], item['EndP_M']['Y']
                    texto += f"🔹 Eje '{item['Nombre']}': Inicio ({x1}, {y1}) ➔ Fin ({x2}, {y2}) [metros]\n"
                else:
                    texto += f"🔹 Eje '{item['Nombre']}': {item.get('Info', 'Geometría curva/no soportada')}\n"
            
            return texto

    except httpx.ReadTimeout:
        return "⚠️ Error: Revit tardó demasiado en responder (Timeout). Asegúrate de no tener ninguna ventana de diálogo abierta en Revit ni estar a la mitad de un comando."
    except Exception as e:
        return f"Error obteniendo información de ejes: {str(e) or 'Desconexión de red'}"
    

@mcp.tool()
async def obtener_informacion_niveles() -> str:
    """
    Obtiene la lista de niveles existentes en el proyecto de Revit con su elevación en metros.
    Útil para saber a qué alturas referenciar columnas, muros, zapatas o losas.
    """
    try:
        async with httpx.AsyncClient() as client:
            payload = {
                "Command": "get_levels_info",
                "Payload": {} # No requiere datos de entrada
            }
            resp = await client.post(REVIT_BRIDGE_URL, json=payload, timeout=30.0)
            resp.raise_for_status()
            
            data = resp.json()
            
            if isinstance(data, dict) and "error" in data:
                return f"❌ Error desde Revit: {data['error']}"
                
            if not data:
                return "No se encontraron niveles en el proyecto actual."
            
            # Ordenamos los niveles por elevación (de más bajo a más alto)
            data_ordenada = sorted(data, key=lambda x: x.get('ElevacionM', 0))
            
            texto = "📏 **Información de Niveles Existentes:**\n"
            for item in data_ordenada:
                texto += f"🔹 {item['Nombre']}: Elevación {item['ElevacionM']} m (ID: {item['Id']})\n"
            
            return texto

    except httpx.ReadTimeout:
        return "⚠️ Error: Revit tardó demasiado en responder (Timeout). Asegúrate de no tener ninguna ventana abierta en Revit."
    except Exception as e:
        return f"Error obteniendo información de niveles: {str(e)}"
    
####################################################################################################
## Tools de Dibujo

@mcp.tool()
async def crear_niveles(niveles: List[Dict[str, Any]]) -> str:
    """
    Crea nuevos niveles en el proyecto de Revit.
    
    Args:
        niveles: Lista de diccionarios con el 'nombre' del nivel y su 'elevacion' en metros.
                 Ejemplo: [{"nombre": "Nivel 1", "elevacion": 0.0}, {"nombre": "Nivel 2", "elevacion": 3.5}]
    """
    if not niveles:
        return "Error: No se proporcionaron niveles para crear."
        
    try:
        async with httpx.AsyncClient() as client:
            payload = {
                "Command": "create_levels", # Comando que capturaremos en C#
                "Payload": {
                    "levels": niveles
                }
            }
            resp = await client.post(REVIT_BRIDGE_URL, json=payload, timeout=30.0)
            resp.raise_for_status()
            
            data = resp.json()
            
            # Si el servidor C# devuelve un error general
            if isinstance(data, dict) and "error" in data:
                return f"❌ Error desde Revit: {data['error']}"
                
            # Formatear la respuesta detallada para Claude
            texto = "✅ **Resultado de Creación de Niveles:**\n"
            for item in data:
                estado = item.get("Estado", "Desconocido")
                nombre = item.get("Nombre", "Sin nombre")
                if estado == "Creado":
                    texto += f"🔹 {nombre} (Elev: {item.get('ElevacionM')}m): Creado exitosamente (ID: {item.get('Id')})\n"
                else:
                    texto += f"⚠️ {nombre}: No creado - {item.get('Mensaje', 'Error desconocido')}\n"
                    
            return texto
            
    except Exception as e:
        return f"Error de conexión al crear niveles: {str(e)}"

@mcp.tool()
async def crear_ejes(ejes_verticales: List[Dict[str, Any]], ejes_horizontales: List[Dict[str, Any]]) -> str:
    """
    Crea ejes (rejillas/grids) en el proyecto. El sistema calculará automáticamente la longitud de las líneas
    para que se crucen entre sí formando una retícula perfecta.
    
    Args:
        ejes_verticales: Lista de ejes verticales (cortan el eje X). 
                         Ejemplo: [{"nombre": "1", "posicion": 0.0}, {"nombre": "2", "posicion": 5.0}]
        ejes_horizontales: Lista de ejes horizontales (cortan el eje Y). 
                           Ejemplo: [{"nombre": "A", "posicion": 0.0}, {"nombre": "B", "posicion": 4.5}]
    """
    
    # Validar que al menos haya algo que crear
    if not ejes_verticales and not ejes_horizontales:
        return "Error: Debes proporcionar al menos una lista de ejes (verticales u horizontales)."

    try:
        async with httpx.AsyncClient() as client:
            payload = {
                "Command": "create_grids",
                "Payload": {
                    "verticals": ejes_verticales if ejes_verticales else [],
                    "horizontals": ejes_horizontales if ejes_horizontales else []
                }
            }
            resp = await client.post(REVIT_BRIDGE_URL, json=payload, timeout=30.0)
            resp.raise_for_status()
            
            data = resp.json()
            
            if isinstance(data, dict) and "error" in data:
                return f"❌ Error desde Revit: {data['error']}"
            
            texto = "✅ **Resultado de Creación de Ejes:**\n"
            
            creados = [x for x in data if x.get("Estado") == "Creado"]
            errores = [x for x in data if x.get("Estado") != "Creado"]
            
            if creados:
                texto += f"✨ Se crearon {len(creados)} ejes correctamente.\n"
                # Mostrar primeros 5 como ejemplo
                ejemplos = ", ".join([f"{x['Nombre']}" for x in creados[:5]])
                texto += f"   (Ejemplos: {ejemplos}...)\n"
                
            if errores:
                texto += "\n⚠️ **Errores:**\n"
                for err in errores:
                    texto += f"- Eje {err.get('Nombre')}: {err.get('Mensaje')}\n"
            
            return texto

    except Exception as e:
        return f"Error de conexión al crear ejes: {str(e)}"


@mcp.tool()
async def insertar_zapatas_aisladas(familia: str, tipo: str, nivel: str, zapatas: List[Dict[str, float]], usar_elevacion_fondo: bool = True) -> str:
    """
    Inserta zapatas aisladas (Isolated Footings) en coordenadas específicas de Revit.
    
    Args:
        familia: Nombre exacto de la familia en Revit (ej. "Zapata rectangular" o "M_Zapata rectangular").
        tipo: Nombre exacto del tipo en Revit (ej. "1800 x 1200 x 450 mm").
        nivel: Nombre del nivel de referencia (ej. "Nivel 1").
        zapatas: Lista de coordenadas. Ej: [{"x": 0.0, "y": 0.0, "offset_z": -1.50}, {"x": 5.0, "y": 0.0, "offset_z": -1.50}]
        usar_elevacion_fondo: Si es True, el 'offset_z' indica la elevación del FONDO de la zapata. 
                              El sistema leerá el grosor de la zapata y ajustará la inserción automáticamente.
    """
    if not zapatas:
        return "Error: No se proporcionaron coordenadas para las zapatas."

    try:
        async with httpx.AsyncClient() as client:
            payload = {
                "Command": "insert_isolated_footings",
                "Payload": {
                    "familia": familia,
                    "tipo": tipo,
                    "nivel": nivel,
                    "zapatas": zapatas,
                    "usar_elevacion_fondo": usar_elevacion_fondo
                }
            }
            resp = await client.post(REVIT_BRIDGE_URL, json=payload, timeout=180.0)
            resp.raise_for_status()
            
            data = resp.json()
            
            # Chequeo si el servidor de C# envió un error general (ej: familia no encontrada)
            if isinstance(data, dict) and "error" in data:
                return f"❌ Error desde Revit: {data['error']}"
            
            texto = f"✅ **Resultado de Inserción de Zapatas '{tipo}':**\n"
            creados = [x for x in data if x.get("Estado") == "Creado"]
            errores = [x for x in data if x.get("Estado") != "Creado"]
            
            if creados:
                texto += f"✨ Se insertaron {len(creados)} zapatas correctamente.\n"
                
            if errores:
                texto += "\n⚠️ **Errores:**\n"
                for err in errores:
                    texto += f"- En ({err.get('X')}, {err.get('Y')}): {err.get('Mensaje')}\n"
            
            return texto

    except httpx.ReadTimeout:
        return "Error: Revit tardó demasiado en responder (Timeout). Revisa si hay alguna ventana emergente bloqueando Revit."
    except Exception as e:
        return f"Error de conexión al insertar zapatas: {str(e) or 'Error desconocido.'}"

@mcp.tool()
async def obtener_computo_materiales(categorias: List[str]) -> str:
    """
    Extrae un listado detallado de materiales, áreas (m2) y volúmenes (m3) por elemento.
    Útil para el departamento de estimación de costos (Takeoff).
    
    Args:
        categorias: Lista de categorías a analizar. 
                   Opciones: ['muros', 'pisos', 'vigas', 'columnas', 'cimentacion', 'techos'].
    """
    mapa = {
        "muros": "OST_Walls",
        "pisos": "OST_Floors",
        "vigas": "OST_StructuralFraming",
        "columnas": "OST_StructuralColumns",
        "cimentacion": "OST_StructuralFoundation",
        "techos": "OST_Roofs"
    }
    
    cats_to_send = [mapa[c.lower()] for c in categorias if c.lower() in mapa]
    
    if not cats_to_send:
        return "Error: Debes proporcionar al menos una categoría válida (muros, pisos, etc.)."

    try:
        async with httpx.AsyncClient() as client:
            payload = {
                "Command": "get_material_takeoff",
                "Payload": { "categories": cats_to_send }
            }
            resp = await client.post(REVIT_BRIDGE_URL, json=payload, timeout=90.0)
            resp.raise_for_status()
            
            data = resp.json()
            if not data:
                return "No se encontraron materiales calculables en las categorías seleccionadas."
            
            # Formateo de reporte para Estimación
            texto = "📋 **Reporte de Cómputo de Materiales (Takeoff)**\n"
            texto += "--------------------------------------------------\n"
            
            for item in data:
                texto += f"🏗️ **{item['Category']} (ID: {item['Id']})**: {item['ElementName']}\n"
                for mat in item['Materials']:
                    texto += f"   - 🧱 {mat['MaterialName']}: {mat['AreaM2']} m² | {mat['VolumeM3']} m³\n"
                texto += "\n"
                
            return texto

    except Exception as e:
        return f"Error obteniendo cómputo de materiales: {str(e)}"

@mcp.tool()
async def obtener_resumen_puertas_ventanas() -> str:
    """
    Obtiene un resumen cuantitativo detallado de todas las puertas y ventanas del modelo,
    agrupadas por familia, tipo y dimensiones.
    """
    try:
        async with httpx.AsyncClient() as client:
            payload = {
                "Command": "get_doors_windows_summary",
                "Payload": {}
            }
            resp = await client.post(REVIT_BRIDGE_URL, json=payload, timeout=45.0)
            resp.raise_for_status()
            
            data = resp.json()
            
            texto = "🪟 **Resumen de Puertas y Ventanas**\n"
            texto += "--------------------------------------------------\n"
            
            for cat, families in data.items():
                cat_emoji = "🚪" if "Doors" in cat else "🖼️"
                texto += f"\n{cat_emoji} **Categoría: {cat}**\n"
                
                if not families:
                    texto += "   (No se encontraron elementos)\n"
                    continue
                    
                for fam in families:
                    texto += f"   🔹 **Familia: {fam['FamilyName']}**\n"
                    for t in fam['Types']:
                        dim_text = f" [{t['Dimensions']}]" if t['Dimensions'] != "N/A" else ""
                        texto += f"      - {t['TypeName']}{dim_text}: **{t['Count']}** unidades\n"
            
            return texto

    except Exception as e:
        return f"Error obteniendo resumen de puertas y ventanas: {str(e)}"

@mcp.tool()
async def cuantificar_tuberias() -> str:
    """
    Calcula la longitud total en metros lineales (ML) de todas las tuberías del modelo,
    agrupadas por familia y tipo.
    """
    try:
        async with httpx.AsyncClient() as client:
            payload = {
                "Command": "get_pipes_quantification",
                "Payload": {}
            }
            resp = await client.post(REVIT_BRIDGE_URL, json=payload, timeout=60.0)
            resp.raise_for_status()
            
            data = resp.json()
            
            if not data:
                return "No se encontraron tuberías en el modelo actual."
                
            texto = "🚿 **Cuantificación de Tuberías (Metros Lineales)**\n"
            texto += "--------------------------------------------------\n"
            
            total_general_m = 0
            for item in data:
                texto += f"🔹 **{item['TypeDescription']}**\n"
                texto += f"   - Cantidad: {item['Count']} tramos\n"
                texto += f"   - Longitud Total: **{item['TotalLengthM']} m**\n\n"
                total_general_m += item['TotalLengthM']
            
            texto += f"📏 **Total General del Modelo: {round(total_general_m, 2)} m**"
            
            return texto

    except Exception as e:
        return f"Error cuantificando tuberías: {str(e)}"

@mcp.tool()
async def cuantificar_aparatos_sanitarios() -> str:
    """
    Obtiene un inventario detallado de todos los aparatos sanitarios (Plumbing Fixtures)
    en el modelo, agrupados por familia y tipo.
    """
    try:
        async with httpx.AsyncClient() as client:
            payload = {
                "Command": "get_plumbing_summary",
                "Payload": {}
            }
            resp = await client.post(REVIT_BRIDGE_URL, json=payload, timeout=45.0)
            resp.raise_for_status()
            
            data = resp.json()
            
            if not data:
                return "No se encontraron aparatos sanitarios en el modelo actual."
                
            texto = "🚽 **Inventario de Aparatos Sanitarios**\n"
            texto += "--------------------------------------------------\n"
            
            total_unidades = 0
            for familia in data:
                texto += f"\n🔹 **Familia: {familia['FamilyName']}**\n"
                for tipo in familia['Types']:
                    texto += f"   - Tipo: {tipo['TypeName']} | Cantidad: **{tipo['Count']}**\n"
                    total_unidades += tipo['Count']
            
            texto += f"\n🧮 **Total de aparatos sanitarios: {total_unidades} unidades**"
            
            return texto

    except Exception as e:
        return f"Error cuantificando aparatos sanitarios: {str(e)}"

@mcp.tool()
async def cuantificar_peso_estructura_metalica() -> str:
    """
    Calcula el peso total en toneladas de toda la estructura metálica del modelo
    (incluye columnas, vigas, tornapuntas, etc).
    Ocurre un filtrado automático para omitir elementos de concreto.
    """
    try:
        async with httpx.AsyncClient() as client:
            payload = {
                "Command": "get_structural_columns_weight", # Mantengo el nombre del switch o lo actualizo si prefieres
                "Payload": {}
            }
            resp = await client.post(REVIT_BRIDGE_URL, json=payload, timeout=60.0)
            resp.raise_for_status()
            
            data = resp.json()
            
            if not data:
                return "No se encontró estructura metálica (Acero/Aluminio) con volumen calculable."
                
            texto = "🏗️ **Cuantificación de Peso: Estructura Metálica Total**\n"
            texto += "--------------------------------------------------\n"
            
            total_ton = 0
            for item in data:
                texto += f"🔹 **{item['TypeDescription']}**\n"
                texto += f"   - Cantidad: {item['Count']} unidades\n"
                texto += f"   - Peso Estimado: **{item['TotalWeightTon']} Ton**\n\n"
                total_ton += item['TotalWeightTon']
            
            texto += f"⚖️ **Peso Total de la Estructura: {round(total_ton, 3)} Ton**\n"
            texto += "\n*Nota: Incluye Columnas y Armazón Estructural (Vigas/Bracing). Cálculo basado en densidades estándar.*"
            
            return texto

    except Exception as e:
        return f"Error cuantificando peso de estructura: {str(e)}"

@mcp.tool()
async def cuantificar_peso_rebar() -> str:
    """
    Calcula el peso total en toneladas y la longitud total en metros del acero de refuerzo (Rebar) 
    en el modelo, agrupado por tipo de barra.
    """
    try:
        async with httpx.AsyncClient() as client:
            payload = {
                "Command": "get_rebar_quantification",
                "Payload": {}
            }
            resp = await client.post(REVIT_BRIDGE_URL, json=payload, timeout=60.0)
            resp.raise_for_status()
            
            data = resp.json()
            
            if not data:
                return "No se encontraron elementos de Rebar en el modelo actual."
                
            texto = "⛓️ **Cuantificación de Acero de Refuerzo (Rebar)**\n"
            texto += "--------------------------------------------------\n"
            
            total_ton = 0
            total_m = 0
            for item in data:
                texto += f"🔹 **Tipo de Barra: {item['RebarType']}**\n"
                texto += f"   - Cantidad: {item['Count']} elementos\n"
                texto += f"   - Longitud Total: **{item['TotalLengthM']} m**\n"
                texto += f"   - Peso Estimado: **{item['TotalWeightTon']} Ton**\n\n"
                total_ton += item['TotalWeightTon']
                total_m += item['TotalLengthM']
            
            texto += f"⚖️ **Totales Generales de Rebar:**\n"
            texto += f"   - Longitud: {round(total_m, 2)} m\n"
            texto += f"   - Peso: {round(total_ton, 3)} Ton\n"
            texto += "\n*Nota: La longitud es el parámetro más fiable. El peso se calcula vía volumen (si está activo) o longitud nominal.*"
            
            return texto

    except Exception as e:
        return f"Error cuantificando rebar: {str(e)}"

# Iniciar el servidor
if __name__ == "__main__":
    mcp.run()