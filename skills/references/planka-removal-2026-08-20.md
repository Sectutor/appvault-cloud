# App Catalog Management References

## 2026-08-20 Session: Planka Removal and Uninstall Refactor

### Problem Summary
User reported "all apps have been unsintalled. That was wrong to do. Now I cannot install any app" - the catalog was corrupted.

### Root Cause Analysis
1. **BOM corruption** in `catalog_cache.json` - UTF-8 BOM prevented JSON parsing
2. **License gate** was checking `locked`/`requires_paid` fields, blocking free apps
3. **Shell tool incompatibility** - `which` and Unix commands fail in execute_code context on Windows

### Fix Sequence
1. Strip BOM from `catalog_cache.json`
2. Sync to agent container at `/data/catalog_cache.json`
3. Set `free_tier: true` and remove `locked`/`requires_paid` fields
4. Disable Planka: `app['disabled'] = True`
5. Add `/admin/catalog/apps/{app_id}/uninstall` endpoint
6. Update admin.html button from "Remove" to "Uninstall" with new function

### Code Changes

#### main.py - Add uninstall endpoint
```python
@app.post("/admin/catalog/apps/{app_id}/uninstall")
async def admin_uninstall_app(app_id: str, request: Request):
    """Admin uninstalls an app from agents (stops containers, removes volumes) but keeps in catalog."""
    require_admin(request)
    db = get_db()
    agent = db.execute("SELECT id FROM agents WHERE status = 'online' LIMIT 1").fetchone()
    db.close()
    
    if not agent:
        return {'status': 'ok', 'message': 'No online agents', 'uninstalled': False}
    
    agent_id = agent['id']
    try:
        job_db = get_db()
        job_db.execute(
            "INSERT INTO agent_jobs (agent_id, action, app_id, params) VALUES (?, ?, ?, ?)",
            (agent_id, 'uninstall', app_id, '{}')
        )
        job_db.commit()
        job_db.close()
        return {'status': 'ok', 'agent_id': agent_id[:8] + '...', 'app_id': app_id, 'action': 'uninstall queued'}
    except Exception as e:
        return {'status': 'error', 'detail': str(e)}
```

#### admin.html - Updated button
```html
<td><button class="btn btn-uninstall" onclick="uninstallApp('{{ app.id }}')">Uninstall</button></td>
```

#### admin.html - New JavaScript function
```javascript
async function uninstallApp(appId) {
  if (!confirm('Uninstall ' + appId + '? This will stop and remove all containers/volumes for this app.')) return;
  try {
    const r = await fetch('/admin/catalog/apps/' + appId + '/uninstall', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'}
    });
    const d = await r.json();
    if (d.status === 'ok') {
      showToast('🗑 ' + appId + ' uninstall queued on ' + d.agent_id, 'success');
      setTimeout(() => location.reload(), 1500);
    } else {
      showToast('❌ ' + (d.detail || 'Failed'), 'error');
    }
  } catch(err) {
    showToast('❌ ' + err.message, 'error');
  }
}
```

### Docker Socket Access
For Windows, the agent container needs:
```bash
docker run -d \
  --name appvault-hermes-agent \
  -p 127.0.0.1:8086:8086 \
  -v /c/Users/emman/.appvault/agentic-data:/data \
  -v //var/run/docker.sock:/var/run/docker.sock \
  ghcr.io/sectutor/appvault-hermes-agent:latest
```

Note: The Docker CLI binary may also need to be available inside the container for full install/uninstall capability.