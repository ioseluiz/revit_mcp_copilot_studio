# GitHub Secrets requeridos

Configura estos secrets en: **Settings → Secrets and variables → Actions**

## Para deploy-mcp-server.yml

| Secret | Valor |
|--------|-------|
| `AZURE_WEBAPP_NAME` | `inio-revit-assistant-cfdddkaphacxeqga` |
| `AZURE_WEBAPP_PUBLISH_PROFILE` | Contenido del archivo de Publish Profile descargado desde Azure Portal |

### Obtener el Publish Profile:
1. Ir a Azure Portal → App Service → `inio-revit-assistant-cfdddkaphacxeqga`
2. Click en **"Get publish profile"** (botón en la barra superior)
3. Copiar todo el contenido XML del archivo descargado
4. Pegarlo como valor del secret `AZURE_WEBAPP_PUBLISH_PROFILE`

## Para release-plugin.yml

No requiere secrets adicionales. Usa el `GITHUB_TOKEN` automático de Actions.

## Trigger de deploy

- **MCP Server**: Se despliega automáticamente al hacer push a `main`/`master` si hay cambios en `mcp_server_azure/`
- **Plugin Release**: Se activa al crear un tag con formato `vX.Y.Z` (ej: `v1.0.0`)

```bash
# Para crear un release del plugin:
git tag v1.0.0
git push origin v1.0.0
```
