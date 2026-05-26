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
API_KEY = os.environ.get("API_KEY", "1234567890")

# =========================================================================
# INICIALIZACIÓN
# =========================================================================
mcp = FastMCP("INIO Revit 2025 Assistant")
mcp_app = mcp.http_app(path="/")

app = FastAPI(
    title="Revit MCP Azure Hub",
    description="Puente Inverso entre Copilot Studio y Revit local",
    lifespan=mcp_app.lifespan
)

# =========================================================================
# SISTEMA DE COLAS (POLLING)
# =========================================================================
pending_tasks: Dict[str, Dict[str, Any]] = {}
completed_tasks: Dict[str, Any] = {}
task_events: Dict[str, asyncio.Event] = {}
user_queues: Dict[str, Dict[str, Dict[str, Any]]] = {}


def verify_api_key(x_api_key: str = Header(None)):
    if not x_api_key or x_api_key != API_KEY:
        raise HTTPException(status_code=401, detail="Invalid API Key")
    return x_api_key


class TaskResult(BaseModel):
    task_id: str
    result: Any
    error: Optional[str] = None


# =========================================================================
# ENDPOINTS PARA EL PLUGIN (C#)
# =========================================================================

@app.get("/api/poll/{user_id}")
async def poll_tasks(user_id: str, x_api_key: str = Depends(verify_api_key)):
    if user_id not in user_queues or not user_queues[user_id]:
        return {"task_id": None}
    task_id = next(iter(user_queues[user_id]))
    task_data = user_queues[user_id].pop(task_id)
    return {"task_id": task_id, "command": task_data["command"], "payload": task_data["payload"]}


@app.post("/api/result/{task_id}")
async def submit_result(task_id: str, result: TaskResult, x_api_key: str = Depends(verify_api_key)):
    if task_id in task_events:
        completed_tasks[task_id] = result.dict()
        task_events[task_id].set()
        return {"status": "ok"}
    return {"status": "error", "message": "Task ID not found or expired"}


# =========================================================================
# CORE: EJECUCIÓN REMOTA EN REVIT
# =========================================================================

async def execute_in_revit(usuario: str, command: str, payload: Dict[str, Any], timeout_seconds: float = 60.0) -> Any:
    task_id = str(uuid.uuid4())
    event = asyncio.Event()
    task_events[task_id] = event

    if usuario not in user_queues:
        user_queues[usuario] = {}

    user_queues[usuario][task_id] = {"command": command, "payload": payload}
    pending_tasks[task_id] = {"command": command, "payload": payload}

    try:
        await asyncio.wait_for(event.wait(), timeout=timeout_seconds)
        res = completed_tasks.pop(task_id, None)
        if res and res.get("error"):
            raise Exception(res["error"])
        return res.get("result") if res else None
    except asyncio.TimeoutError:
        pending_tasks.pop(task_id, None)
        raise Exception(
            f"Timeout: Revit no respondió en {timeout_seconds}s al comando '{command}'. "
            "¿Está activo el puente MCP en Revit (botón ON)?"
        )
    finally:
        task_events.pop(task_id, None)


def _err(tool: str, usuario: str, e: Exception) -> str:
    return json.dumps({
        "status": "error",
        "tool": tool,
        "usuario": usuario,
        "error": str(e),
        "agent_hint": "Verifica que el botón MCP Server esté en estado ON dentro de Revit 2025."
    }, ensure_ascii=False)


def _parse(data: Any) -> Any:
    """Desempaquetar JSON si viene como string escapado desde el plugin C#."""
    while isinstance(data, str):
        clean = data.strip()
        if clean.startswith(("[", "{")):
            try:
                data = json.loads(clean)
            except Exception:
                break
        else:
            break
    return data


# =========================================================================
# TOOLS MCP
# =========================================================================

@mcp.tool()
async def obtener_elementos_con_datos(usuario: str, tipo_elemento: str) -> str:
    """
    Obtiene elementos del modelo incluyendo sus parámetros de gestión de obra.
    Busca: codigo_cronograma, codigo_actividad, costo_unitario, division, master format.

    Args:
        usuario: ID del usuario Windows (ej: jlmunoz)
        tipo_elemento: 'todos', 'columnas', 'cimentacion', 'vigas', 'pisos', 'muros', 'puertas',
                       'ventanas', 'escaleras', 'mobiliario', 'techos', 'cielorrasos', 'tuberias',
                       'barandas', 'muros cortinas', 'conexiones estructurales',
                       'equipos mecanicos', 'aparatos sanitarios', 'conductos'.
    """
    TOOL = "obtener_elementos_con_datos"
    mapa_categorias = {
        "columnas": "OST_StructuralColumns",
        "cimentacion": "OST_StructuralFoundation",
        "vigas": "OST_StructuralFraming",
        "pisos": "OST_Floors",
        "muros": "OST_Walls",
        "puertas": "OST_Doors",
        "ventanas": "OST_Windows",
        "escaleras": "OST_Stairs",
        "mobiliario": "OST_Furniture",
        "techos": "OST_Roofs",
        "cielorrasos": "OST_Ceilings",
        "tuberias": "OST_Pipes",
        "barandas": "OST_StairsRailing",
        "muros cortinas": "OST_Walls_Curtain",
        "conexiones estructurales": "OST_StructConnections",
        "equipos mecanicos": "OST_MechanicalEquipment",
        "aparatos sanitarios": "OST_PlumbingFixtures",
        "conductos": "OST_DuctCurves"
    }

    clave = tipo_elemento.lower()
    if clave != "todos" and clave not in mapa_categorias:
        return json.dumps({
            "status": "error", "tool": TOOL, "usuario": usuario,
            "error": f"Categoría '{tipo_elemento}' no configurada.",
            "valid_categories": list(mapa_categorias.keys()) + ["todos"]
        }, ensure_ascii=False)

    base_params = ["codigo_cronograma", "codigo_actividad", "costo_unitario", "division", "master format", "MasterFormat", "masterformat"]
    parametros_a_buscar = []
    for p in base_params:
        parametros_a_buscar.extend([p, p.lower(), p.capitalize(), p.upper(), p.title()])
    parametros_a_buscar.extend(["Assembly Code", "Keynote", "Código de montaje"])
    parametros_a_buscar = list(set(parametros_a_buscar))

    try:
        if clave == "todos":
            payload = {"categories": list(mapa_categorias.values()), "parameters": parametros_a_buscar}
            timeout = 180.0
        else:
            payload = {"category": mapa_categorias[clave], "parameters": parametros_a_buscar}
            timeout = 60.0

        raw_data = await execute_in_revit(usuario, "get_elements_with_params", payload, timeout_seconds=timeout)
        data = _parse(raw_data)

        elementos_con_datos = []
        if isinstance(data, list):
            for item in data:
                item_normalized = {str(k).lower(): v for k, v in item.items()}
                for p in parametros_a_buscar:
                    valor = item_normalized.get(p.lower())
                    if valor and str(valor).strip() not in ["", "None", "0", "N/A", "null"]:
                        elementos_con_datos.append(item)
                        break

        total_consultados = len(data) if isinstance(data, list) else 0

        return json.dumps({
            "status": "success",
            "tool": TOOL,
            "usuario": usuario,
            "tipo_elemento": tipo_elemento,
            "total_consultados": total_consultados,
            "count": len(elementos_con_datos),
            "data": elementos_con_datos,
            "summary": (
                f"{len(elementos_con_datos)} de {total_consultados} elementos tienen parámetros de obra asignados."
                if elementos_con_datos
                else f"Se consultaron {total_consultados} elementos pero ninguno tiene parámetros de obra ({', '.join(base_params)})."
            ),
            "agent_hint": (
                "Usa los 'Id' de cada elemento para referenciarlos en operaciones posteriores. "
                "Los parámetros 'codigo_cronograma' y 'codigo_actividad' son clave para vincular con programación de obra."
            )
        }, ensure_ascii=False, indent=2)

    except Exception as e:
        return _err(TOOL, usuario, e)


@mcp.tool()
async def obtener_info_proyecto(usuario: str) -> str:
    """Obtiene información general del proyecto de Revit abierto actualmente."""
    TOOL = "obtener_info_proyecto"
    try:
        data = await execute_in_revit(usuario, "get_project_info", {}, timeout_seconds=15.0)
        data = _parse(data)
        return json.dumps({
            "status": "success",
            "tool": TOOL,
            "usuario": usuario,
            "data": data,
            "summary": f"Proyecto: {data.get('Title', 'N/A')} | Archivo: {data.get('Path', 'N/A')} | Usuario Revit: {data.get('User', 'N/A')}",
            "agent_hint": (
                "Confirma que el proyecto abierto es el correcto antes de realizar consultas o modificaciones. "
                "El 'Title' del proyecto identifica el modelo BIM activo."
            )
        }, ensure_ascii=False, indent=2)
    except Exception as e:
        return _err(TOOL, usuario, e)


@mcp.tool()
async def listar_muros(usuario: str) -> str:
    """Lista los muros en el modelo actual con sus propiedades principales."""
    TOOL = "listar_muros"
    try:
        data = await execute_in_revit(usuario, "get_walls", {}, timeout_seconds=30.0)
        data = _parse(data)
        count = len(data) if isinstance(data, list) else 0
        return json.dumps({
            "status": "success",
            "tool": TOOL,
            "usuario": usuario,
            "count": count,
            "data": data,
            "summary": f"{count} muros encontrados en el modelo.",
            "agent_hint": "Usa los 'Id' de muros para solicitar su cómputo de materiales con obtener_computo_materiales."
        }, ensure_ascii=False, indent=2)
    except Exception as e:
        return _err(TOOL, usuario, e)


@mcp.tool()
async def listar_elementos_estructurales(usuario: str, tipo_elemento: str) -> str:
    """
    Lista elementos estructurales del modelo.
    Args:
        tipo_elemento: 'columnas', 'cimentacion', 'vigas', 'pisos', 'muros'.
    """
    TOOL = "listar_elementos_estructurales"
    mapa_categorias = {
        "columnas": "OST_StructuralColumns",
        "cimentacion": "OST_StructuralFoundation",
        "vigas": "OST_StructuralFraming",
        "pisos": "OST_Floors",
        "muros": "OST_Walls"
    }
    clave = tipo_elemento.lower()
    if clave not in mapa_categorias:
        return json.dumps({
            "status": "error", "tool": TOOL, "usuario": usuario,
            "error": f"Tipo '{tipo_elemento}' no soportado.",
            "valid_types": list(mapa_categorias.keys())
        }, ensure_ascii=False)

    try:
        data = await execute_in_revit(usuario, "get_elements_by_category",
                                      {"category": mapa_categorias[clave]}, timeout_seconds=30.0)
        data = _parse(data)
        items = data if isinstance(data, list) else []
        return json.dumps({
            "status": "success",
            "tool": TOOL,
            "usuario": usuario,
            "tipo_elemento": tipo_elemento,
            "count": len(items),
            "data": items[:100],  # Limitado a 100 para contexto del agente
            "truncated": len(items) > 100,
            "summary": f"{len(items)} elementos de tipo '{tipo_elemento}' encontrados.",
            "agent_hint": (
                "Para calcular volúmenes usa calcular_volumen_concreto. "
                "Para materiales detallados usa obtener_computo_materiales."
            )
        }, ensure_ascii=False, indent=2)
    except Exception as e:
        return _err(TOOL, usuario, e)


@mcp.tool()
async def calcular_volumen_concreto(usuario: str, elementos: List[str]) -> str:
    """Calcula el volumen total de concreto (hormigón) en metros cúbicos para las categorías solicitadas."""
    TOOL = "calcular_volumen_concreto"
    mapa = {
        "columnas": "OST_StructuralColumns",
        "cimentacion": "OST_StructuralFoundation",
        "vigas": "OST_StructuralFraming",
        "pisos": "OST_Floors",
        "muros": "OST_Walls"
    }
    cats_to_send = list(mapa.values()) if not elementos else [mapa[e.lower()] for e in elementos if e.lower() in mapa]

    if not cats_to_send:
        return json.dumps({
            "status": "error", "tool": TOOL, "usuario": usuario,
            "error": "Ninguna categoría válida seleccionada.",
            "valid_categories": list(mapa.keys())
        }, ensure_ascii=False)

    try:
        data = await execute_in_revit(usuario, "get_concrete_volume",
                                      {"categories": cats_to_send}, timeout_seconds=60.0)
        data = _parse(data)
        total = data.get("TotalVolumeM3", 0)
        breakdown = data.get("Breakdown", [])
        return json.dumps({
            "status": "success",
            "tool": TOOL,
            "usuario": usuario,
            "categories_queried": elementos or list(mapa.keys()),
            "total_volume_m3": total,
            "breakdown": breakdown,
            "data": data,
            "summary": (
                f"Volumen total de concreto: {total} m³ en {len(breakdown)} categorías. "
                + " | ".join([f"{b['Category']}: {b['VolumeM3']} m³" for b in breakdown])
            ),
            "agent_hint": (
                "El volumen total en m³ puede usarse directamente para presupuestos de concreto. "
                "Para obtener desglose por material específico, usa obtener_computo_materiales."
            )
        }, ensure_ascii=False, indent=2)
    except Exception as e:
        return _err(TOOL, usuario, e)


@mcp.tool()
async def inventario_por_familia(usuario: str, categoria: str) -> str:
    """Genera un resumen cuantitativo agrupado por Familia y Tipo."""
    TOOL = "inventario_por_familia"
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
        return json.dumps({
            "status": "error", "tool": TOOL, "usuario": usuario,
            "error": f"Categoría '{categoria}' no soportada.",
            "valid_categories": list(mapa.keys())
        }, ensure_ascii=False)

    try:
        data = await execute_in_revit(usuario, "get_family_summary",
                                      {"category": mapa[clave]}, timeout_seconds=45.0)
        data = _parse(data)
        if not data:
            return json.dumps({
                "status": "success", "tool": TOOL, "usuario": usuario,
                "categoria": categoria, "count": 0, "data": [],
                "summary": f"No se encontraron elementos en la categoría '{categoria}'.",
                "agent_hint": "El modelo puede no contener elementos de esta categoría."
            }, ensure_ascii=False)

        total_familias = len(data)
        total_unidades = sum(t["Count"] for f in data for t in f.get("Types", []))
        return json.dumps({
            "status": "success",
            "tool": TOOL,
            "usuario": usuario,
            "categoria": categoria,
            "total_familias": total_familias,
            "total_unidades": total_unidades,
            "data": data,
            "summary": f"{total_unidades} unidades de '{categoria}' en {total_familias} familias.",
            "agent_hint": (
                "Los 'TypeName' y 'Count' son útiles para generar tablas de cómputo de obra. "
                "Usa 'FamilyName' para identificar especificaciones técnicas."
            )
        }, ensure_ascii=False, indent=2)
    except Exception as e:
        return _err(TOOL, usuario, e)


@mcp.tool()
async def obtener_informacion_ejes(usuario: str) -> str:
    """Obtiene la lista de ejes (grids) existentes en el modelo con coordenadas en metros."""
    TOOL = "obtener_informacion_ejes"
    try:
        data = await execute_in_revit(usuario, "get_grids_info", {}, timeout_seconds=30.0)
        data = _parse(data)

        if isinstance(data, dict) and "error" in data:
            return _err(TOOL, usuario, Exception(data["error"]))
        if not data:
            return json.dumps({
                "status": "success", "tool": TOOL, "usuario": usuario,
                "count": 0, "data": [],
                "summary": "No se encontraron ejes (grids) en el proyecto.",
                "agent_hint": "Usa crear_ejes para generar la retícula estructural antes de insertar elementos."
            }, ensure_ascii=False)

        ejes_lineales = [e for e in data if "StartP_M" in e]
        ejes_curvos = [e for e in data if "StartP_M" not in e]
        return json.dumps({
            "status": "success",
            "tool": TOOL,
            "usuario": usuario,
            "count": len(data),
            "ejes_lineales": len(ejes_lineales),
            "ejes_curvos": len(ejes_curvos),
            "data": data,
            "summary": f"{len(data)} ejes encontrados ({len(ejes_lineales)} lineales, {len(ejes_curvos)} curvos/especiales).",
            "agent_hint": (
                "Las coordenadas 'StartP_M' y 'EndP_M' (en metros) definen la posición de cada eje. "
                "Usa estas coordenadas como referencia para insertar columnas, zapatas o verificar ubicaciones. "
                "Los 'Nombre' de los ejes (ej: A, B, 1, 2) son la referencia del plano estructural."
            )
        }, ensure_ascii=False, indent=2)
    except Exception as e:
        return _err(TOOL, usuario, e)


@mcp.tool()
async def obtener_informacion_niveles(usuario: str) -> str:
    """Obtiene la lista de niveles existentes en el proyecto con su elevación en metros."""
    TOOL = "obtener_informacion_niveles"
    try:
        data = await execute_in_revit(usuario, "get_levels_info", {}, timeout_seconds=30.0)
        data = _parse(data)

        if isinstance(data, dict) and "error" in data:
            return _err(TOOL, usuario, Exception(data["error"]))
        if not data:
            return json.dumps({
                "status": "success", "tool": TOOL, "usuario": usuario,
                "count": 0, "data": [],
                "summary": "No se encontraron niveles en el proyecto.",
                "agent_hint": "Usa crear_niveles para definir los niveles del proyecto antes de modelar elementos."
            }, ensure_ascii=False)

        data_ordenada = sorted(data, key=lambda x: x.get("ElevacionM", 0))
        return json.dumps({
            "status": "success",
            "tool": TOOL,
            "usuario": usuario,
            "count": len(data_ordenada),
            "nivel_base": data_ordenada[0] if data_ordenada else None,
            "nivel_techo": data_ordenada[-1] if data_ordenada else None,
            "data": data_ordenada,
            "summary": (
                f"{len(data_ordenada)} niveles. "
                f"Rango: {data_ordenada[0]['Nombre']} ({data_ordenada[0]['ElevacionM']}m) "
                f"→ {data_ordenada[-1]['Nombre']} ({data_ordenada[-1]['ElevacionM']}m)."
            ),
            "agent_hint": (
                "Los 'Id' de cada nivel son REQUERIDOS para crear elementos como columnas, zapatas y vigas. "
                "Los 'Nombre' de nivel se usan como parámetro en insertar_zapatas_aisladas y crear_ejes. "
                "Guarda este resultado antes de llamar herramientas de modelado."
            )
        }, ensure_ascii=False, indent=2)
    except Exception as e:
        return _err(TOOL, usuario, e)


@mcp.tool()
async def crear_niveles(usuario: str, niveles: List[Dict[str, Any]]) -> str:
    """
    Crea nuevos niveles en el proyecto de Revit.
    Args:
        niveles: Lista de objetos con 'nombre' (str) y 'elevacion' (float, en metros).
    """
    TOOL = "crear_niveles"
    if not niveles:
        return json.dumps({
            "status": "error", "tool": TOOL, "usuario": usuario,
            "error": "No se proporcionaron niveles para crear.",
            "expected_format": [{"nombre": "Nivel 1", "elevacion": 0.0}]
        }, ensure_ascii=False)
    try:
        data = await execute_in_revit(usuario, "create_levels",
                                      {"levels": niveles}, timeout_seconds=30.0)
        data = _parse(data)
        if isinstance(data, dict) and "error" in data:
            return _err(TOOL, usuario, Exception(data["error"]))

        creados = [x for x in data if x.get("Estado") == "Creado"]
        errores = [x for x in data if x.get("Estado") != "Creado"]
        return json.dumps({
            "status": "success",
            "tool": TOOL,
            "usuario": usuario,
            "created": len(creados),
            "failed": len(errores),
            "data": data,
            "created_levels": [{"Nombre": x["Nombre"], "Id": x.get("Id"), "ElevacionM": x.get("ElevacionM")} for x in creados],
            "errors": [{"Nombre": x.get("Nombre"), "Mensaje": x.get("Mensaje")} for x in errores],
            "summary": f"{len(creados)} niveles creados, {len(errores)} fallidos.",
            "agent_hint": (
                "Los 'Id' de los niveles creados son necesarios para colocar elementos en ellos. "
                "Llama obtener_informacion_niveles para obtener los IDs actualizados si los necesitas."
            )
        }, ensure_ascii=False, indent=2)
    except Exception as e:
        return _err(TOOL, usuario, e)


@mcp.tool()
async def crear_ejes(usuario: str, ejes_verticales: List[Dict[str, Any]], ejes_horizontales: List[Dict[str, Any]]) -> str:
    """
    Crea ejes (rejillas/grids) en el proyecto.
    Args:
        ejes_verticales: Lista de {nombre: str, posicion: float} (posición X en metros).
        ejes_horizontales: Lista de {nombre: str, posicion: float} (posición Y en metros).
    """
    TOOL = "crear_ejes"
    if not ejes_verticales and not ejes_horizontales:
        return json.dumps({
            "status": "error", "tool": TOOL, "usuario": usuario,
            "error": "Debes proporcionar al menos un eje vertical u horizontal.",
            "expected_format": {
                "ejes_verticales": [{"nombre": "A", "posicion": 0.0}],
                "ejes_horizontales": [{"nombre": "1", "posicion": 0.0}]
            }
        }, ensure_ascii=False)
    try:
        data = await execute_in_revit(usuario, "create_grids",
                                      {"verticals": ejes_verticales or [], "horizontals": ejes_horizontales or []},
                                      timeout_seconds=30.0)
        data = _parse(data)
        if isinstance(data, dict) and "error" in data:
            return _err(TOOL, usuario, Exception(data["error"]))

        creados = [x for x in data if x.get("Estado") == "Creado"]
        errores = [x for x in data if x.get("Estado") != "Creado"]
        return json.dumps({
            "status": "success",
            "tool": TOOL,
            "usuario": usuario,
            "created": len(creados),
            "failed": len(errores),
            "data": data,
            "created_grids": [x["Nombre"] for x in creados],
            "errors": [{"Nombre": x.get("Nombre"), "Mensaje": x.get("Mensaje")} for x in errores],
            "summary": f"{len(creados)} ejes creados ({len(ejes_verticales or [])} vert. + {len(ejes_horizontales or [])} horiz.).",
            "agent_hint": (
                "Con los ejes creados puedes usar obtener_informacion_ejes para obtener sus coordenadas exactas "
                "y luego insertar_zapatas_aisladas en las intersecciones."
            )
        }, ensure_ascii=False, indent=2)
    except Exception as e:
        return _err(TOOL, usuario, e)


@mcp.tool()
async def insertar_zapatas_aisladas(
    usuario: str, familia: str, tipo: str, nivel: str,
    zapatas: List[Dict[str, float]], usar_elevacion_fondo: bool = True
) -> str:
    """
    Inserta zapatas aisladas (Isolated Footings) en el modelo.
    Args:
        usuario: ID de usuario Windows.
        familia: Nombre de familia de zapata en Revit (ej: 'Zapata Aislada').
        tipo: Nombre del tipo (ej: 'ZA-120x120x60').
        nivel: Nombre del nivel base (ej: 'Nivel 1').
        zapatas: Lista de {x: float, y: float, offset_z: float (opcional)} en metros.
        usar_elevacion_fondo: Si True, usa elevación de fondo de zapata.
    """
    TOOL = "insertar_zapatas_aisladas"
    if not zapatas:
        return json.dumps({
            "status": "error", "tool": TOOL, "usuario": usuario,
            "error": "Debes proporcionar al menos una coordenada de zapata.",
            "expected_format": [{"x": 0.0, "y": 0.0, "offset_z": -0.6}]
        }, ensure_ascii=False)
    try:
        payload = {
            "familia": familia, "tipo": tipo, "nivel": nivel,
            "zapatas": zapatas, "usar_elevacion_fondo": usar_elevacion_fondo
        }
        data = await execute_in_revit(usuario, "insert_isolated_footings", payload, timeout_seconds=180.0)
        data = _parse(data)
        if isinstance(data, dict) and "error" in data:
            return _err(TOOL, usuario, Exception(data["error"]))

        creados = [x for x in data if x.get("Estado") == "Creado"]
        errores = [x for x in data if x.get("Estado") != "Creado"]
        return json.dumps({
            "status": "success",
            "tool": TOOL,
            "usuario": usuario,
            "familia": familia,
            "tipo": tipo,
            "nivel": nivel,
            "created": len(creados),
            "failed": len(errores),
            "data": data,
            "created_ids": [x.get("Id") for x in creados if x.get("Id")],
            "errors": [{"x": x.get("X"), "y": x.get("Y"), "mensaje": x.get("Mensaje")} for x in errores],
            "summary": f"{len(creados)} zapatas '{tipo}' insertadas en nivel '{nivel}', {len(errores)} fallidas.",
            "agent_hint": (
                "Los 'Id' de zapatas creadas pueden usarse para verificar ubicaciones. "
                "Si hubo errores, verifica que la familia/tipo existan en el proyecto y que las coordenadas sean válidas."
            )
        }, ensure_ascii=False, indent=2)
    except Exception as e:
        return _err(TOOL, usuario, e)


@mcp.tool()
async def obtener_computo_materiales(usuario: str, categorias: List[str]) -> str:
    """
    Extrae un listado detallado de materiales, áreas y volúmenes por elemento.
    Args:
        categorias: Lista con alguna de: 'muros', 'pisos', 'vigas', 'columnas', 'cimentacion', 'techos'.
    """
    TOOL = "obtener_computo_materiales"
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
        return json.dumps({
            "status": "error", "tool": TOOL, "usuario": usuario,
            "error": "Categoría inválida.",
            "valid_categories": list(mapa.keys())
        }, ensure_ascii=False)
    try:
        data = await execute_in_revit(usuario, "get_material_takeoff",
                                      {"categories": cats_to_send}, timeout_seconds=90.0)
        data = _parse(data)
        if not data:
            return json.dumps({
                "status": "success", "tool": TOOL, "usuario": usuario,
                "count": 0, "data": [],
                "summary": "No se encontraron materiales calculables para las categorías seleccionadas.",
                "agent_hint": "Verifica que los elementos tengan materiales asignados en sus propiedades de tipo."
            }, ensure_ascii=False)

        total_area = round(sum(m.get("AreaM2", 0) for item in data for m in item.get("Materials", [])), 3)
        total_vol = round(sum(m.get("VolumeM3", 0) for item in data for m in item.get("Materials", [])), 3)
        return json.dumps({
            "status": "success",
            "tool": TOOL,
            "usuario": usuario,
            "categorias": categorias,
            "count": len(data),
            "total_area_m2": total_area,
            "total_volume_m3": total_vol,
            "data": data,
            "summary": f"{len(data)} elementos analizados | Área total: {total_area} m² | Volumen total: {total_vol} m³.",
            "agent_hint": (
                "Agrupa los resultados por 'MaterialName' para obtener cómputos por tipo de material. "
                "Los campos 'AreaM2' y 'VolumeM3' son directamente usables en presupuestos."
            )
        }, ensure_ascii=False, indent=2)
    except Exception as e:
        return _err(TOOL, usuario, e)


@mcp.tool()
async def obtener_resumen_puertas_ventanas(usuario: str) -> str:
    """Obtiene un resumen de todas las puertas y ventanas del modelo con dimensiones y cantidades."""
    TOOL = "obtener_resumen_puertas_ventanas"
    try:
        data = await execute_in_revit(usuario, "get_doors_windows_summary", {}, timeout_seconds=45.0)
        data = _parse(data)

        total_puertas = sum(t["Count"] for cat, fams in data.items() if "Door" in cat
                            for f in (fams if isinstance(fams, list) else [])
                            for t in f.get("Types", []))
        total_ventanas = sum(t["Count"] for cat, fams in data.items() if "Window" in cat
                             for f in (fams if isinstance(fams, list) else [])
                             for t in f.get("Types", []))
        return json.dumps({
            "status": "success",
            "tool": TOOL,
            "usuario": usuario,
            "total_puertas": total_puertas,
            "total_ventanas": total_ventanas,
            "data": data,
            "summary": f"{total_puertas} puertas y {total_ventanas} ventanas en el modelo.",
            "agent_hint": (
                "Los 'TypeName' y 'Dimensions' permiten identificar cada especificación para tablas de carpintería. "
                "Los 'Count' son las cantidades para el cómputo de obra."
            )
        }, ensure_ascii=False, indent=2)
    except Exception as e:
        return _err(TOOL, usuario, e)


@mcp.tool()
async def cuantificar_tuberias(usuario: str) -> str:
    """Calcula la longitud total en metros lineales (ML) de todas las tuberías del modelo."""
    TOOL = "cuantificar_tuberias"
    try:
        data = await execute_in_revit(usuario, "get_pipes_quantification", {}, timeout_seconds=60.0)
        data = _parse(data)
        if not data:
            return json.dumps({
                "status": "success", "tool": TOOL, "usuario": usuario,
                "count": 0, "total_length_m": 0, "data": [],
                "summary": "No se encontraron tuberías en el modelo.",
                "agent_hint": "Verifica que el modelo contenga sistemas de plomería/mecánica."
            }, ensure_ascii=False)

        total_m = round(sum(item.get("TotalLengthM", 0) for item in data), 2)
        total_tramos = sum(item.get("Count", 0) for item in data)
        return json.dumps({
            "status": "success",
            "tool": TOOL,
            "usuario": usuario,
            "count": len(data),
            "total_tramos": total_tramos,
            "total_length_m": total_m,
            "data": data,
            "summary": f"{total_tramos} tramos de tubería | Total: {total_m} m lineales en {len(data)} tipos.",
            "agent_hint": (
                "Agrupa por 'TypeDescription' para obtener metros lineales por diámetro/material de tubería. "
                "Estos valores son directamente usables en presupuestos de instalaciones."
            )
        }, ensure_ascii=False, indent=2)
    except Exception as e:
        return _err(TOOL, usuario, e)


@mcp.tool()
async def cuantificar_aparatos_sanitarios(usuario: str) -> str:
    """Genera un inventario completo de aparatos sanitarios (plumbing fixtures) del modelo."""
    TOOL = "cuantificar_aparatos_sanitarios"
    try:
        data = await execute_in_revit(usuario, "get_plumbing_summary", {}, timeout_seconds=45.0)
        data = _parse(data)
        if not data:
            return json.dumps({
                "status": "success", "tool": TOOL, "usuario": usuario,
                "count": 0, "total_unidades": 0, "data": [],
                "summary": "No se encontraron aparatos sanitarios en el modelo.",
                "agent_hint": "Verifica que el modelo contenga elementos de plomería."
            }, ensure_ascii=False)

        total_unidades = sum(t["Count"] for f in data for t in f.get("Types", []))
        return json.dumps({
            "status": "success",
            "tool": TOOL,
            "usuario": usuario,
            "total_familias": len(data),
            "total_unidades": total_unidades,
            "data": data,
            "summary": f"{total_unidades} aparatos sanitarios en {len(data)} familias.",
            "agent_hint": (
                "Los 'FamilyName' y 'TypeName' identifican cada especificación sanitaria. "
                "Los 'Count' son las cantidades para el cómputo de instalaciones hidráulicas."
            )
        }, ensure_ascii=False, indent=2)
    except Exception as e:
        return _err(TOOL, usuario, e)


@mcp.tool()
async def cuantificar_peso_estructura_metalica(usuario: str) -> str:
    """Calcula el peso total en toneladas de la estructura metálica (acero/aluminio) del modelo."""
    TOOL = "cuantificar_peso_estructura_metalica"
    try:
        data = await execute_in_revit(usuario, "get_structural_columns_weight", {}, timeout_seconds=60.0)
        data = _parse(data)
        if not data:
            return json.dumps({
                "status": "success", "tool": TOOL, "usuario": usuario,
                "count": 0, "total_weight_ton": 0, "data": [],
                "summary": "No se encontró estructura metálica en el modelo.",
                "agent_hint": "Este cómputo aplica solo a elementos de acero o aluminio. El concreto se cuantifica con calcular_volumen_concreto."
            }, ensure_ascii=False)

        total_ton = round(sum(item.get("TotalWeightTon", 0) for item in data), 3)
        total_unidades = sum(item.get("Count", 0) for item in data)
        return json.dumps({
            "status": "success",
            "tool": TOOL,
            "usuario": usuario,
            "count": len(data),
            "total_unidades": total_unidades,
            "total_weight_ton": total_ton,
            "data": data,
            "summary": f"Estructura metálica: {total_ton} ton en {total_unidades} elementos ({len(data)} tipos).",
            "agent_hint": (
                "El peso en toneladas es directamente usable en presupuestos de estructura metálica. "
                "Combina con cuantificar_peso_rebar para el reporte completo de estructura."
            )
        }, ensure_ascii=False, indent=2)
    except Exception as e:
        return _err(TOOL, usuario, e)


@mcp.tool()
async def cuantificar_peso_rebar(usuario: str) -> str:
    """Calcula peso y longitud total de acero de refuerzo (Rebar) en el modelo."""
    TOOL = "cuantificar_peso_rebar"
    try:
        data = await execute_in_revit(usuario, "get_rebar_quantification", {}, timeout_seconds=60.0)
        data = _parse(data)
        if not data:
            return json.dumps({
                "status": "success", "tool": TOOL, "usuario": usuario,
                "count": 0, "total_weight_ton": 0, "total_length_m": 0, "data": [],
                "summary": "No se encontró acero de refuerzo (Rebar) en el modelo.",
                "agent_hint": "Verifica que el modelo tenga elementos de refuerzo modelados (no solo simbólicos)."
            }, ensure_ascii=False)

        total_ton = round(sum(item.get("TotalWeightTon", 0) for item in data), 3)
        total_m = round(sum(item.get("TotalLengthM", 0) for item in data), 2)
        total_barras = sum(item.get("Count", 0) for item in data)
        return json.dumps({
            "status": "success",
            "tool": TOOL,
            "usuario": usuario,
            "count": len(data),
            "total_barras": total_barras,
            "total_length_m": total_m,
            "total_weight_ton": total_ton,
            "data": data,
            "summary": f"Acero de refuerzo: {total_ton} ton | {total_m} m | {total_barras} barras en {len(data)} tipos.",
            "agent_hint": (
                "El 'RebarType' identifica el diámetro y grado del acero. "
                "Combina con cuantificar_peso_estructura_metalica para el reporte total de acero."
            )
        }, ensure_ascii=False, indent=2)
    except Exception as e:
        return _err(TOOL, usuario, e)


# =========================================================================
# MONTAR FastMCP EN FastAPI
# =========================================================================
app.mount("/sse", mcp_app)


@app.get("/")
async def root():
    return {"status": "online", "message": "Revit MCP Azure Hub is running"}


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port)
