import asyncio
import uuid
import os
from typing import Any, Dict, List, Optional
from fastapi import FastAPI, Depends, HTTPException, Header, Request
from pydantic import BaseModel
from fastmcp import FastMCP
import json

# =========================================================================
# CONFIGURACIÓN
# =========================================================================
# API Key por defecto para pruebas locales. En Azure se configura en App Settings
API_KEY = os.environ.get("API_KEY", "1234567890") 

# =========================================================================
# INICIALIZACIÓN DE APLICACIONES
# =========================================================================
app = FastAPI(title="Revit MCP Azure Hub", description="Puente Inverso entre Copilot Studio y Revit local")
mcp = FastMCP("INIO Revit 2025 Assistant")

# =========================================================================
# SISTEMA DE COLAS (POLLING)
# =========================================================================
# Almacenamiento en memoria
pending_tasks: Dict[str, Dict[str, Any]] = {}
completed_tasks: Dict[str, Any] = {}
task_events: Dict[str, asyncio.Event] = {}

def verify_api_key(x_api_key: str = Header(None)):
    if not x_api_key or x_api_key != API_KEY:
        raise HTTPException(status_code=401, detail="Invalid API Key")
    return x_api_key

class TaskResult(BaseModel):
    task_id: str
    result: Any  # Puede ser string, dict, list, etc.
    error: Optional[str] = None

# --- Endpoints para el Plugin de Revit (C#) ---

@app.get("/api/poll")
async def poll_tasks(x_api_key: str = Depends(verify_api_key)):
    """El plugin de Revit llama aquí para obtener la siguiente tarea pendiente."""
    if not pending_tasks:
        return {"task_id": None}
    
    # Extraer la primera tarea (FIFO rudimentario)
    task_id = next(iter(pending_tasks))
    task_data = pending_tasks.pop(task_id) # Sacamos de la cola
    
    return {
        "task_id": task_id,
        "command": task_data["command"],
        "payload": task_data["payload"]
    }

@app.post("/api/result/{task_id}")
async def submit_result(task_id: str, result: TaskResult, x_api_key: str = Depends(verify_api_key)):
    """El plugin de Revit envía el resultado aquí."""
    if task_id in task_events:
        completed_tasks[task_id] = result.dict()
        task_events[task_id].set() # Despierta a la tool de MCP
        return {"status": "ok"}
    return {"status": "error", "message": "Task ID not found or expired"}


async def execute_in_revit(command: str, payload: Dict[str, Any], timeout_seconds: float = 60.0) -> Any:
    """Encola un comando para Revit y espera asincrónicamente el resultado."""
    task_id = str(uuid.uuid4())
    
    event = asyncio.Event()
    task_events[task_id] = event
    pending_tasks[task_id] = {"command": command, "payload": payload}
    
    try:
        # Esperar la respuesta (bloquea solo esta corrutina, no el servidor)
        await asyncio.wait_for(event.wait(), timeout=timeout_seconds)
        
        # Recuperar y limpiar
        res = completed_tasks.pop(task_id, None)
        if res and res.get("error"):
            raise Exception(res["error"])
        
        return res.get("result") if res else None
    except asyncio.TimeoutError:
        pending_tasks.pop(task_id, None)
        raise Exception(f"Timeout: Revit no respondió en {timeout_seconds} segundos al comando '{command}'. ¿Está encendido el puente en Revit?")
    finally:
        task_events.pop(task_id, None)


# =========================================================================
# TOOLS DE MCP (Lógica de negocio portada de la versión local)
# =========================================================================

@mcp.tool()
async def obtener_elementos_con_datos(tipo_elemento: str) -> str:
    """
    Obtiene elementos del modelo incluyendo sus parámetros de gestión de obra.
    Busca: codigo_cronograma, codigo_actividad, costo_unitario, division, master format.
    
    Args:
        tipo_elemento: 'columnas', 'cimentacion', 'vigas', 'pisos', 'muros', 'puertas', 'ventanas'.
    """
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

    parametros_a_buscar = [
        "codigo_cronograma", "codigo_actividad", "costo_unitario", 
        "division", "master format", "Assembly Code", "Keynote"
    ]

    try:
        data = await execute_in_revit(
            command="get_elements_with_params",
            payload={"category": mapa_categorias[clave], "parameters": parametros_a_buscar},
            timeout_seconds=60.0
        )
        
        if isinstance(data, str):
            try:
                data = json.loads(data)
            except:
                pass
                
        elementos_con_datos = []
        if isinstance(data, list):
            for item in data:
                if any(item.get(p) for p in parametros_a_buscar):
                    elementos_con_datos.append(item)
        
        if not elementos_con_datos:
            count = len(data) if isinstance(data, list) else "Varios"
            return f"Se encontraron {count} elementos de tipo '{tipo_elemento}', pero ninguno tiene los parámetros solicitados rellenos."
            
        return f"Se encontraron {len(elementos_con_datos)} elementos con datos relevantes (mostrando muestra):\n{str(elementos_con_datos[:20])} \n...(y más)"
    except Exception as e:
        return f"Error obteniendo datos: {str(e)}"

@mcp.tool()
async def obtener_info_proyecto() -> str:
    """Obtiene información general del proyecto de Revit abierto actualmente."""
    try:
        data = await execute_in_revit("get_project_info", {}, timeout_seconds=15.0)
        return str(data)
    except Exception as e:
        return f"Error conectando con Revit: {str(e)}"

@mcp.tool()
async def listar_muros() -> str:
    """Lista los muros en el modelo actual."""
    try:
        data = await execute_in_revit("get_walls", {}, timeout_seconds=30.0)
        # Formatear a string si viene como lista
        if isinstance(data, (list, dict)):
            return json.dumps(data, indent=2)
        return str(data)
    except Exception as e:
        return f"Error obteniendo muros: {str(e)}"

@mcp.tool()
async def listar_elementos_estructurales(tipo_elemento: str) -> str:
    """
    Lista elementos estructurales del modelo.
    Args:
        tipo_elemento: 'columnas', 'cimentacion', 'vigas', 'pisos'.
    """
    mapa_categorias = {
        "columnas": "OST_StructuralColumns",
        "cimentacion": "OST_StructuralFoundation",
        "vigas": "OST_StructuralFraming",
        "pisos": "OST_Floors",
        "muros": "OST_Walls"
    }
    clave = tipo_elemento.lower()
    if clave not in mapa_categorias:
        return f"Error: Tipo '{tipo_elemento}' no soportado."

    try:
        data = await execute_in_revit("get_elements_by_category", {"category": mapa_categorias[clave]}, timeout_seconds=30.0)
        
        # Parse if string
        if isinstance(data, str):
            try:
                data = json.loads(data)
            except:
                pass
                
        if isinstance(data, list):
            return f"Se encontraron {len(data)} elementos de tipo '{tipo_elemento}':\n{json.dumps(data[:50], indent=2)}\n...(limitado a 50)"
        return str(data)
    except Exception as e:
        return f"Error obteniendo elementos: {str(e)}"

@mcp.tool()
async def calcular_volumen_concreto(elementos: List[str]) -> str:
    """Calcula el volumen total de concreto (hormigón) en metros cúbicos para las categorías solicitadas."""
    mapa = {
        "columnas": "OST_StructuralColumns", "cimentacion": "OST_StructuralFoundation",
        "vigas": "OST_StructuralFraming", "pisos": "OST_Floors", "muros": "OST_Walls"
    }
    cats_to_send = list(mapa.values()) if not elementos else [mapa[e.lower()] for e in elementos if e.lower() in mapa]
    
    if not cats_to_send:
        return "Error: Ninguna categoría válida seleccionada."

    try:
        data = await execute_in_revit("get_concrete_volume", {"categories": cats_to_send}, timeout_seconds=60.0)
        if isinstance(data, str): data = json.loads(data)
        
        texto = f"📦 **Reporte de Volumen de Concreto**\n**Total General:** {data.get('TotalVolumeM3', 0)} m³\n\nDesglose por categoría:\n"
        for item in data.get('Breakdown', []):
            texto += f"- {item['Category']}: {item['Count']} elementos | {item['VolumeM3']} m³\n"
        return texto
    except Exception as e:
        return f"Error calculando volúmenes: {str(e)}"

@mcp.tool()
async def inventario_por_familia(categoria: str) -> str:
    """Genera un resumen cuantitativo agrupado por Familia y Tipo."""
    mapa = {
        "puertas": "OST_Doors", "ventanas": "OST_Windows", "muros": "OST_Walls",
        "mobiliario": "OST_Furniture", "equipos": "OST_MechanicalEquipment",
        "fontaneria": "OST_PlumbingFixtures", "columnas": "OST_StructuralColumns"
    }
    clave = categoria.lower()
    if clave not in mapa: return f"Error: Categoría '{categoria}' no soportada."
        
    try:
        data = await execute_in_revit("get_family_summary", {"category": mapa[clave]}, timeout_seconds=45.0)
        if isinstance(data, str): data = json.loads(data)
        
        if not data: return f"No se encontraron elementos en la categoría {categoria}."
            
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
    """Obtiene la lista de ejes (grids) existentes en el modelo."""
    try:
        data = await execute_in_revit("get_grids_info", {}, timeout_seconds=30.0)
        if isinstance(data, str): data = json.loads(data)
        
        if isinstance(data, dict) and "error" in data: return f"❌ Error: {data['error']}"
        if not data: return "No se encontraron ejes (grids) en el proyecto actual."
        
        texto = "📐 **Información de Ejes (Grids) Existentes:**\n"
        for item in data:
            if "StartP_M" in item:
                x1, y1 = item['StartP_M']['X'], item['StartP_M']['Y']
                x2, y2 = item['EndP_M']['X'], item['EndP_M']['Y']
                texto += f"🔹 Eje '{item['Nombre']}': Inicio ({x1}, {y1}) ➔ Fin ({x2}, {y2}) [m]\n"
            else:
                texto += f"🔹 Eje '{item['Nombre']}': {item.get('Info', 'Geometría curva/no soportada')}\n"
        return texto
    except Exception as e:
        return f"Error: {str(e)}"

@mcp.tool()
async def obtener_informacion_niveles() -> str:
    """Obtiene la lista de niveles existentes en el proyecto de Revit con su elevación en metros."""
    try:
        data = await execute_in_revit("get_levels_info", {}, timeout_seconds=30.0)
        if isinstance(data, str): data = json.loads(data)
        
        if isinstance(data, dict) and "error" in data: return f"❌ Error: {data['error']}"
        if not data: return "No se encontraron niveles en el proyecto."
        
        data_ordenada = sorted(data, key=lambda x: x.get('ElevacionM', 0))
        texto = "📏 **Información de Niveles Existentes:**\n"
        for item in data_ordenada:
            texto += f"🔹 {item['Nombre']}: Elevación {item['ElevacionM']} m (ID: {item['Id']})\n"
        return texto
    except Exception as e:
        return f"Error: {str(e)}"

@mcp.tool()
async def crear_niveles(niveles: List[Dict[str, Any]]) -> str:
    """Crea nuevos niveles en el proyecto de Revit."""
    if not niveles: return "Error: No se proporcionaron niveles para crear."
    try:
        data = await execute_in_revit("create_levels", {"levels": niveles}, timeout_seconds=30.0)
        if isinstance(data, str): data = json.loads(data)
        if isinstance(data, dict) and "error" in data: return f"❌ Error: {data['error']}"
        
        texto = "✅ **Resultado de Creación de Niveles:**\n"
        for item in data:
            estado = item.get("Estado", "Desconocido")
            nombre = item.get("Nombre", "Sin nombre")
            if estado == "Creado":
                texto += f"🔹 {nombre} (Elev: {item.get('ElevacionM')}m): Creado exitosamente\n"
            else:
                texto += f"⚠️ {nombre}: No creado - {item.get('Mensaje', 'Error desconocido')}\n"
        return texto
    except Exception as e:
        return f"Error: {str(e)}"

@mcp.tool()
async def crear_ejes(ejes_verticales: List[Dict[str, Any]], ejes_horizontales: List[Dict[str, Any]]) -> str:
    """Crea ejes (rejillas/grids) en el proyecto."""
    if not ejes_verticales and not ejes_horizontales: return "Error: Faltan ejes."
    try:
        data = await execute_in_revit("create_grids", {"verticals": ejes_verticales or [], "horizontals": ejes_horizontales or []}, timeout_seconds=30.0)
        if isinstance(data, str): data = json.loads(data)
        if isinstance(data, dict) and "error" in data: return f"❌ Error: {data['error']}"
        
        texto = "✅ **Resultado de Creación de Ejes:**\n"
        creados = [x for x in data if x.get("Estado") == "Creado"]
        errores = [x for x in data if x.get("Estado") != "Creado"]
        
        if creados:
            texto += f"✨ Se crearon {len(creados)} ejes correctamente.\n"
        if errores:
            texto += "\n⚠️ **Errores:**\n"
            for err in errores: texto += f"- Eje {err.get('Nombre')}: {err.get('Mensaje')}\n"
        return texto
    except Exception as e:
        return f"Error: {str(e)}"

@mcp.tool()
async def insertar_zapatas_aisladas(familia: str, tipo: str, nivel: str, zapatas: List[Dict[str, float]], usar_elevacion_fondo: bool = True) -> str:
    """Inserta zapatas aisladas (Isolated Footings)."""
    if not zapatas: return "Error: Faltan coordenadas."
    try:
        payload = {"familia": familia, "tipo": tipo, "nivel": nivel, "zapatas": zapatas, "usar_elevacion_fondo": usar_elevacion_fondo}
        data = await execute_in_revit("insert_isolated_footings", payload, timeout_seconds=180.0)
        if isinstance(data, str): data = json.loads(data)
        if isinstance(data, dict) and "error" in data: return f"❌ Error: {data['error']}"
        
        texto = f"✅ **Resultado de Inserción de Zapatas '{tipo}':**\n"
        creados = [x for x in data if x.get("Estado") == "Creado"]
        errores = [x for x in data if x.get("Estado") != "Creado"]
        
        if creados: texto += f"✨ Se insertaron {len(creados)} zapatas correctamente.\n"
        if errores:
            texto += "\n⚠️ **Errores:**\n"
            for err in errores: texto += f"- En ({err.get('X')}, {err.get('Y')}): {err.get('Mensaje')}\n"
        return texto
    except Exception as e:
        return f"Error: {str(e)}"

@mcp.tool()
async def obtener_computo_materiales(categorias: List[str]) -> str:
    """Extrae un listado detallado de materiales, áreas y volúmenes por elemento."""
    mapa = {
        "muros": "OST_Walls", "pisos": "OST_Floors", "vigas": "OST_StructuralFraming",
        "columnas": "OST_StructuralColumns", "cimentacion": "OST_StructuralFoundation", "techos": "OST_Roofs"
    }
    cats_to_send = [mapa[c.lower()] for c in categorias if c.lower() in mapa]
    if not cats_to_send: return "Error: Categoría inválida."
    try:
        data = await execute_in_revit("get_material_takeoff", {"categories": cats_to_send}, timeout_seconds=90.0)
        if isinstance(data, str): data = json.loads(data)
        if not data: return "No se encontraron materiales calculables."
        
        texto = "📋 **Reporte de Cómputo de Materiales (Takeoff)**\n--------------------------------------------------\n"
        for item in data:
            texto += f"🏗️ **{item['Category']} (ID: {item['Id']})**: {item['ElementName']}\n"
            for mat in item['Materials']:
                texto += f"   - 🧱 {mat['MaterialName']}: {mat['AreaM2']} m² | {mat['VolumeM3']} m³\n"
            texto += "\n"
        return texto
    except Exception as e:
        return f"Error: {str(e)}"

@mcp.tool()
async def obtener_resumen_puertas_ventanas() -> str:
    """Obtiene un resumen de todas las puertas y ventanas del modelo."""
    try:
        data = await execute_in_revit("get_doors_windows_summary", {}, timeout_seconds=45.0)
        if isinstance(data, str): data = json.loads(data)
        
        texto = "🪟 **Resumen de Puertas y Ventanas**\n--------------------------------------------------\n"
        for cat, families in data.items():
            cat_emoji = "🚪" if "Doors" in cat else "🖼️"
            texto += f"\n{cat_emoji} **Categoría: {cat}**\n"
            if not families:
                texto += "   (No se encontraron elementos)\n"
                continue
            for fam in families:
                texto += f"   🔹 **Familia: {fam['FamilyName']}**\n"
                for t in fam['Types']:
                    dim_text = f" [{t['Dimensions']}]" if t.get('Dimensions') and t['Dimensions'] != "N/A" else ""
                    texto += f"      - {t['TypeName']}{dim_text}: **{t['Count']}** unidades\n"
        return texto
    except Exception as e:
        return f"Error: {str(e)}"

@mcp.tool()
async def cuantificar_tuberias() -> str:
    """Calcula la longitud total en metros lineales (ML) de todas las tuberías."""
    try:
        data = await execute_in_revit("get_pipes_quantification", {}, timeout_seconds=60.0)
        if isinstance(data, str): data = json.loads(data)
        if not data: return "No se encontraron tuberías."
            
        texto = "🚿 **Cuantificación de Tuberías (Metros Lineales)**\n--------------------------------------------------\n"
        total_general_m = 0
        for item in data:
            texto += f"🔹 **{item['TypeDescription']}**\n   - Cantidad: {item['Count']} tramos\n   - Longitud Total: **{item['TotalLengthM']} m**\n\n"
            total_general_m += item['TotalLengthM']
        texto += f"📏 **Total General: {round(total_general_m, 2)} m**"
        return texto
    except Exception as e:
        return f"Error: {str(e)}"

@mcp.tool()
async def cuantificar_aparatos_sanitarios() -> str:
    """Inventario de aparatos sanitarios."""
    try:
        data = await execute_in_revit("get_plumbing_summary", {}, timeout_seconds=45.0)
        if isinstance(data, str): data = json.loads(data)
        if not data: return "No se encontraron aparatos sanitarios."
            
        texto = "🚽 **Inventario de Aparatos Sanitarios**\n--------------------------------------------------\n"
        total_unidades = 0
        for familia in data:
            texto += f"\n🔹 **Familia: {familia['FamilyName']}**\n"
            for tipo in familia['Types']:
                texto += f"   - Tipo: {tipo['TypeName']} | Cantidad: **{tipo['Count']}**\n"
                total_unidades += tipo['Count']
        texto += f"\n🧮 **Total: {total_unidades} unidades**"
        return texto
    except Exception as e:
        return f"Error: {str(e)}"

@mcp.tool()
async def cuantificar_peso_estructura_metalica() -> str:
    """Calcula el peso total en toneladas de estructura metálica."""
    try:
        data = await execute_in_revit("get_structural_columns_weight", {}, timeout_seconds=60.0)
        if isinstance(data, str): data = json.loads(data)
        if not data: return "No se encontró estructura metálica."
            
        texto = "🏗️ **Cuantificación de Peso: Estructura Metálica**\n--------------------------------------------------\n"
        total_ton = 0
        for item in data:
            texto += f"🔹 **{item['TypeDescription']}**\n   - Cantidad: {item['Count']} unid.\n   - Peso: **{item['TotalWeightTon']} Ton**\n\n"
            total_ton += item['TotalWeightTon']
        texto += f"⚖️ **Peso Total: {round(total_ton, 3)} Ton**\n"
        return texto
    except Exception as e:
        return f"Error: {str(e)}"

@mcp.tool()
async def cuantificar_peso_rebar() -> str:
    """Calcula peso y longitud de acero de refuerzo (Rebar)."""
    try:
        data = await execute_in_revit("get_rebar_quantification", {}, timeout_seconds=60.0)
        if isinstance(data, str): data = json.loads(data)
        if not data: return "No se encontró Rebar."
            
        texto = "⛓️ **Cuantificación de Acero de Refuerzo (Rebar)**\n--------------------------------------------------\n"
        total_ton = 0; total_m = 0
        for item in data:
            texto += f"🔹 **{item['RebarType']}**\n   - Cantidad: {item['Count']}\n   - Longitud: **{item['TotalLengthM']} m**\n   - Peso: **{item['TotalWeightTon']} Ton**\n\n"
            total_ton += item['TotalWeightTon']
            total_m += item['TotalLengthM']
        texto += f"⚖️ **Totales:**\n   - Longitud: {round(total_m, 2)} m\n   - Peso: {round(total_ton, 3)} Ton\n"
        return texto
    except Exception as e:
        return f"Error: {str(e)}"

# =========================================================================
# MONTAR FastMCP en FastAPI (Soporte SSE para Copilot Studio)
# =========================================================================
app.mount("/sse", mcp.get_starlette_app())

if __name__ == "__main__":
    import uvicorn
    # Para ejecutar localmente: python main.py
    # Para Azure: uvicorn main:app --host 0.0.0.0 --port $PORT
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
