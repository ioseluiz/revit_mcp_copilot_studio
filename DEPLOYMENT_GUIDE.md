# Guía de Despliegue: Revit MCP Server en Azure para Copilot Studio

Esta guía explica cómo desplegar el servidor Python en Azure y cómo conectarlo con tu plugin local de Revit y Microsoft Copilot Studio.

## 1. Despliegue del Servidor en Azure App Service (Sin Contenedores)

Dado que tu suscripción de Azure no permite contenedores, usaremos el despliegue nativo de código (ZipDeploy o Kudu) en Azure App Service (Web App) para Python.

### Paso 1: Crear la Web App en Azure
1. Ve al portal de Azure (portal.azure.com).
2. Crea un nuevo recurso: **Web App** (App Service).
3. Configuración:
   - **Publish:** Code (Código).
   - **Runtime stack:** Python 3.11 o 3.12.
   - **Operating System:** Linux (recomendado para Python en App Service, incluso si subes código fuente directamente).
   - **Region:** Selecciona la más cercana a ti.
   - **Pricing Plan:** Puedes usar el plan Básico (B1) o Estándar (S1). El plan Free (F1) puede quedarse sin memoria.

### Paso 2: Configurar Variables de Entorno
1. Una vez creada la Web App, ve a **Settings > Environment variables** (o Configuration).
2. Añade las siguientes App Settings:
   - `API_KEY`: Define una clave segura (ej: `my-super-secret-key-2026`). **Debe ser la misma que pondrás en el plugin de Revit.**
   - `SCM_DO_BUILD_DURING_DEPLOYMENT`: `true` (Para que Kudu instale los requirements.txt automáticamente).

### Paso 3: Desplegar el Código
1. En tu terminal local, ve a la carpeta `mcp_server_azure`.
2. Comprime el contenido (no la carpeta, sino los archivos dentro de ella) en un archivo `deploy.zip`.
   *Asegúrate de incluir `main.py` y `requirements.txt`.*
3. Usa Azure CLI para subir el zip:
   ```bash
   az webapp deployment source config-zip --resource-group TuGrupoDeRecursos --name TuNombreDeWebApp --src deploy.zip
   ```
4. Azure instalará automáticamente las dependencias (FastAPI, FastMCP, uvicorn, etc.) y ejecutará la aplicación a través de Gunicorn/Uvicorn que viene preconfigurado en el entorno Linux de Python de App Service.

*(Nota: La URL final será algo como `https://tunombre.azurewebsites.net`)*

---

## 2. Configuración del Plugin de Revit

1. Abre el archivo `revit_plugin_azure/RevitMCPBridge/ServerController.cs` en Visual Studio.
2. Modifica las constantes en la parte superior:
   ```csharp
   private const string AZURE_BASE_URL = "https://tunombre.azurewebsites.net"; 
   private const string API_KEY = "my-super-secret-key-2026";
   ```
3. Compila el proyecto de C# (Build Solution).
4. El plugin (RevitMCPBridge.dll) se actualizará en Revit.
5. Abre Revit, ve a la pestaña "INIO IA Assistant", y haz clic en "MCP Server (OFF)" para encenderlo. Ahora dirá (ON) y estará haciendo "Polling" a Azure.

---

## 3. Configuración en Microsoft Copilot Studio

Microsoft Copilot Studio permite agregar servidores MCP utilizando un endpoint SSE.

1. Ve a [Microsoft Copilot Studio](https://copilotstudio.microsoft.com/).
2. Selecciona tu agente (Copilot) o crea uno nuevo.
3. Ve a la sección de **Tools** (Herramientas) o **Actions** y selecciona **Add an MCP Server**.
4. Rellena los datos de configuración:
   - **Name:** `RevitAssistant` (o el nombre que prefieras).
   - **Description:** "Permite extraer información de modelos BIM, cuantificar materiales, y crear elementos en Revit."
   - **Endpoint URL:** `https://tunombre.azurewebsites.net/sse`  *(Es vital agregar `/sse` al final de la URL).*
5. **Autenticación (Authentication):**
   - Selecciona **API Key**.
   - **API Key placement:** `Header`.
   - **Header name:** `x-api-key`.
   - **API Key value:** `my-super-secret-key-2026` (La misma que configuraste en Azure y Revit).
6. Guarda y activa la herramienta en tu agente.

### ¡Listo!
Cuando le pidas a Copilot Studio "Dime el volumen total de concreto", Copilot enviará la solicitud al `/sse` en Azure. Azure pondrá la tarea en cola. El plugin de Revit (que está haciendo polling a `/api/poll`) tomará la tarea, calculará el volumen, y lo enviará de vuelta a `/api/result`. Finalmente, Azure devolverá ese resultado a Copilot Studio. Todo esto ocurrirá en un par de segundos.
