# App Catalog Management

## Description

Managing the AppVault catalog: installing/uninstalling apps, handling licensing gates, fixing BOM corruption, and ensuring Docker availability for app deployments.

## Key Patterns

### 1. Catalog Cache Corruption (UTF-8 BOM Issue)
When apps show as "402 Payment Required" despite `free_tier: true`, check for UTF-8 BOM:
```bash
python3 -c "
with open('catalog_cache.json', 'rb') as f:
    data = f.read()
if data.startswith(b'\\xef\\xbb\\xbf'):
    print('BOM detected - needs fixing')
    with open('catalog_cache.json', 'wb') as out:
        out.write(data[3:])  # Remove BOM
"
```

### 2. License Gate Fix
In agent code, remove checking of `locked` and `requires_paid` fields:
```python
# WRONG - blocks free apps
if app.get('locked') or app.get('requires_paid'):
    return {'status': 'error', 'message': 'License required'}

# CORRECT - only check free_tier
if not app.get('free_tier'):
    # Handle premium apps
```

### 3. App Disabling Pattern
To hide an app without deleting:
```python
# Set disabled: true in catalog entry
app['disabled'] = True
# Or use the API endpoint
POST /admin/catalog/apps/{app_id}/disable
{ "disabled": true }
```

### 4. Docker Availability for Agent Container
The agent container needs BOTH:
- Docker socket mounted: `-v //var/run/docker.sock:/var/run/docker.sock`
- Docker CLI available inside container (not just the socket)

## Pitfalls

### Pitfall: Delete vs Uninstall Confusion
- **"Remove"** button in admin panel DELETES app from catalog entirely
- **"Uninstall"** button STOPS/removes containers but keeps app in catalog
- User wants uninstall to clean up installed containers without removing the catalog entry

Fix: Add `/admin/catalog/apps/{app_id}/uninstall` endpoint that sends uninstall job to agent instead of deleting from catalog.

### Pitfall: Port Conflicts
No containers should run on port 3000. Reassign:
- Port 3000 → 3011, 3012, 3013, 3014, etc.

### Pitfall: BOM Encoding
UTF-8 BOM (`\xef\xbb\xbf`) silently breaks JSON parsing. Always check and strip when syncing catalog_cache.json.

## Verification Checklist

Before marking app as working:
- [ ] Container starts successfully
- [ ] Health check passes (no timeouts)
- [ ] Docker socket accessible from agent
- [ ] API_KEY properly set
- [ ] free_tier field correct
- [ ] disabled = false for public apps
- [ ] Port not conflicting (no 3000)

## Troubleshooting

| Symptom | Cause | Fix |
|---------|-------|-----|
| "Docker unavailable" | Docker CLI not in container | Mount docker socket AND ensure CLI available |
| "402 Payment Required" | locked/requires_paid fields blocking | Remove these fields or fix license gate |
| "App install fails silently" | BOM in catalog_cache.json | Strip BOM, sync to container |
| Button shows "Delete" not "Uninstall" | Template not rebuilt | Rebuild agent image with updated templates |
| Container port 8086 not responding | Port not mapped | Verify `-p 127.0.0.1:8086:8086` in run |