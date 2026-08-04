"""Add screenshot placeholder URLs and fix missing link fields for visible apps."""
import json

CATALOG_PATH = "catalog.json"

with open(CATALOG_PATH, encoding="utf-8") as f:
    data = json.load(f)

apps = data.get("apps", [])

# Screenshot placeholders for all 52 visible apps (using placehold.co with app-specific labels)
SCREENSHOT_MAP = {
    "owncloud": [
        "https://placehold.co/800x600/1e293b/38bdf8?text=ownCloud+Dashboard",
        "https://placehold.co/800x600/1e293b/38bdf8?text=ownCloud+Files"
    ],
    "n8n": [
        "https://placehold.co/800x600/1e293b/38bdf8?text=n8n+Workflow+Editor",
        "https://placehold.co/800x600/1e293b/38bdf8?text=n8n+Node+Library"
    ],
    "pihole": [
        "https://placehold.co/800x600/1e293b/38bdf8?text=Pi-hole+Dashboard",
        "https://placehold.co/800x600/1e293b/38bdf8?text=Pi-hole+Query+Log"
    ],
    "openwebui": [
        "https://placehold.co/800x600/1e293b/38bdf8?text=Open+WebUI+Chat",
        "https://placehold.co/800x600/1e293b/38bdf8?text=Open+WebUI+Models"
    ],
    "crewai-studio": [
        "https://placehold.co/800x600/1e293b/38bdf8?text=CrewAI+Studio+Agents",
        "https://placehold.co/800x600/1e293b/38bdf8?text=CrewAI+Workflow"
    ],
    "hermes-agent": [
        "https://placehold.co/800x600/1e293b/38bdf8?text=Hermes+Agent+Chat",
        "https://placehold.co/800x600/1e293b/38bdf8?text=Hermes+Agent+Tasks"
    ],
    "adguard": [
        "https://placehold.co/800x600/1e293b/38bdf8?text=AdGuard+Home+Dashboard",
        "https://placehold.co/800x600/1e293b/38bdf8?text=AdGuard+Query+Log"
    ],
    "wordpress": [
        "https://placehold.co/800x600/1e293b/38bdf8?text=WordPress+Editor",
        "https://placehold.co/800x600/1e293b/38bdf8?text=WordPress+Dashboard"
    ],
    "nextcloud": [
        "https://placehold.co/800x600/1e293b/38bdf8?text=Nextcloud+Files",
        "https://placehold.co/800x600/1e293b/38bdf8?text=Nextcloud+Dashboard"
    ],
    "onlyoffice": [
        "https://placehold.co/800x600/1e293b/38bdf8?text=OnlyOffice+Document+Editor",
        "https://placehold.co/800x600/1e293b/38bdf8?text=OnlyOffice+Spreadsheet"
    ],
    "gitlab": [
        "https://placehold.co/800x600/1e293b/38bdf8?text=GitLab+Repository",
        "https://placehold.co/800x600/1e293b/38bdf8?text=GitLab+CI%2FCD+Pipelines"
    ],
    "bookstack": [
        "https://placehold.co/800x600/1e293b/38bdf8?text=BookStack+Bookshelf",
        "https://placehold.co/800x600/1e293b/38bdf8?text=BookStack+Page+Editor"
    ],
    "paperless": [
        "https://placehold.co/800x600/1e293b/38bdf8?text=Paperless-ngx+Dashboard",
        "https://placehold.co/800x600/1e293b/38bdf8?text=Paperless-ngx+Documents"
    ],
    "jellyfin": [
        "https://placehold.co/800x600/1e293b/38bdf8?text=Jellyfin+Home",
        "https://placehold.co/800x600/1e293b/38bdf8?text=Jellyfin+Library"
    ],
    "navidrome": [
        "https://placehold.co/800x600/1e293b/38bdf8?text=Navidrome+Interface",
        "https://placehold.co/800x600/1e293b/38bdf8?text=Navidrome+Player"
    ],
    "kavita": [
        "https://placehold.co/800x600/1e293b/38bdf8?text=Kavita+Library",
        "https://placehold.co/800x600/1e293b/38bdf8?text=Kavita+Reader"
    ],
    "photoprism": [
        "https://placehold.co/800x600/1e293b/38bdf8?text=PhotoPrism+Albums",
        "https://placehold.co/800x600/1e293b/38bdf8?text=PhotoPrism+Search"
    ],
    "immich": [
        "https://placehold.co/800x600/1e293b/38bdf8?text=Immich+Photos",
        "https://placehold.co/800x600/1e293b/38bdf8?text=Immich+Albums"
    ],
    "wireguard": [
        "https://placehold.co/800x600/1e293b/38bdf8?text=WireGuard+Interface",
        "https://placehold.co/800x600/1e293b/38bdf8?text=WireGuard+Peer+Manager"
    ],
    "vaultwarden": [
        "https://placehold.co/800x600/1e293b/38bdf8?text=Vaultwarden+Vault",
        "https://placehold.co/800x600/1e293b/38bdf8?text=Vaultwarden+Login"
    ],
    "nginx-proxy-manager": [
        "https://placehold.co/800x600/1e293b/38bdf8?text=Nginx+Proxy+Manager",
        "https://placehold.co/800x600/1e293b/38bdf8?text=Nginx+Proxy+Hosts"
    ],
    "traefik": [
        "https://placehold.co/800x600/1e293b/38bdf8?text=Traefik+Dashboard",
        "https://placehold.co/800x600/1e293b/38bdf8?text=Traefik+Routes"
    ],
    "portainer": [
        "https://placehold.co/800x600/1e293b/38bdf8?text=Portainer+Dashboard",
        "https://placehold.co/800x600/1e293b/38bdf8?text=Portainer+Containers"
    ],
    "dozzle": [
        "https://placehold.co/800x600/1e293b/38bdf8?text=Dozzle+Logs",
        "https://placehold.co/800x600/1e293b/38bdf8?text=Dozzle+Container+View"
    ],
    "code-server": [
        "https://placehold.co/800x600/1e293b/38bdf8?text=VS+Code+Browser",
        "https://placehold.co/800x600/1e293b/38bdf8?text=VS+Code+Terminal"
    ],
    "gitea": [
        "https://placehold.co/800x600/1e293b/38bdf8?text=Gitea+Repository",
        "https://placehold.co/800x600/1e293b/38bdf8?text=Gitea+Dashboard"
    ],
    "stirling-pdf": [
        "https://placehold.co/800x600/1e293b/38bdf8?text=Stirling+PDF+Tools",
        "https://placehold.co/800x600/1e293b/38bdf8?text=Stirling+PDF+Merge"
    ],
    "excalidraw": [
        "https://placehold.co/800x600/1e293b/38bdf8?text=Excalidraw+Canvas",
        "https://placehold.co/800x600/1e293b/38bdf8?text=Excalidraw+Library"
    ],
    "drawio": [
        "https://placehold.co/800x600/1e293b/38bdf8?text=Draw.io+Editor",
        "https://placehold.co/800x600/1e293b/38bdf8?text=Draw.io+Shapes"
    ],
    "9router": [
        "https://placehold.co/800x600/1e293b/38bdf8?text=9Router+Dashboard",
        "https://placehold.co/800x600/1e293b/38bdf8?text=9Router+Providers"
    ],
    "documenso": [
        "https://placehold.co/800x600/1e293b/38bdf8?text=Documenso+Sign",
        "https://placehold.co/800x600/1e293b/38bdf8?text=Documenso+Documents"
    ],
    "twenty": [
        "https://placehold.co/800x600/1e293b/38bdf8?text=Twenty+CRM+Contacts",
        "https://placehold.co/800x600/1e293b/38bdf8?text=Twenty+CRM+Pipelines"
    ],
    "shieldsign": [
        "https://placehold.co/800x600/1e293b/38bdf8?text=ShieldSign+Sign",
        "https://placehold.co/800x600/1e293b/38bdf8?text=ShieldSign+Documents"
    ],
    "anythingllm": [
        "https://placehold.co/800x600/1e293b/38bdf8?text=AnythingLLM+Chat",
        "https://placehold.co/800x600/1e293b/38bdf8?text=AnythingLLM+Workspaces"
    ],
    "searxng": [
        "https://placehold.co/800x600/1e293b/38bdf8?text=SearXNG+Search",
        "https://placehold.co/800x600/1e293b/38bdf8?text=SearXNG+Preferences"
    ],
    "dify": [
        "https://placehold.co/800x600/1e293b/38bdf8?text=Dify+App+Builder",
        "https://placehold.co/800x600/1e293b/38bdf8?text=Dify+Workflow"
    ],
    "librechat": [
        "https://placehold.co/800x600/1e293b/38bdf8?text=LibreChat+Chat",
        "https://placehold.co/800x600/1e293b/38bdf8?text=LibreChat+Models"
    ],
    "comfyui": [
        "https://placehold.co/800x600/1e293b/38bdf8?text=ComfyUI+Workflow",
        "https://placehold.co/800x600/1e293b/38bdf8?text=ComfyUI+Gallery"
    ],
    "openhands": [
        "https://placehold.co/800x600/1e293b/38bdf8?text=OpenHands+Agent",
        "https://placehold.co/800x600/1e293b/38bdf8?text=OpenHands+Terminal"
    ],
    "khoj": [
        "https://placehold.co/800x600/1e293b/38bdf8?text=Khoj+Chat",
        "https://placehold.co/800x600/1e293b/38bdf8?text=Khoj+Knowledge+Base"
    ],
    "wg-easy": [
        "https://placehold.co/800x600/1e293b/38bdf8?text=WG-Easy+Setup",
        "https://placehold.co/800x600/1e293b/38bdf8?text=WG-Easy+Peers"
    ],
    "mattermost": [
        "https://placehold.co/800x600/1e293b/38bdf8?text=Mattermost+Channels",
        "https://placehold.co/800x600/1e293b/38bdf8?text=Mattermost+Chat"
    ],
    "baserow": [
        "https://placehold.co/800x600/1e293b/38bdf8?text=Baserow+Database",
        "https://placehold.co/800x600/1e293b/38bdf8?text=Baserow+Table"
    ],
    "umami": [
        "https://placehold.co/800x600/1e293b/38bdf8?text=Umami+Dashboard",
        "https://placehold.co/800x600/1e293b/38bdf8?text=Umami+Websites"
    ],
    "ghost": [
        "https://placehold.co/800x600/1e293b/38bdf8?text=Ghost+Editor",
        "https://placehold.co/800x600/1e293b/38bdf8?text=Ghost+Admin"
    ],
    "directus": [
        "https://placehold.co/800x600/1e293b/38bdf8?text=Directus+Data+Studio",
        "https://placehold.co/800x600/1e293b/38bdf8?text=Directus+Collections"
    ],
    "formbricks": [
        "https://placehold.co/800x600/1e293b/38bdf8?text=Formbricks+Surveys",
        "https://placehold.co/800x600/1e293b/38bdf8?text=Formbricks+Analytics"
    ],
    "chatwoot": [
        "https://placehold.co/800x600/1e293b/38bdf8?text=Chatwoot+Conversations",
        "https://placehold.co/800x600/1e293b/38bdf8?text=Chatwoot+Dashboard"
    ],
    "plane": [
        "https://placehold.co/800x600/1e293b/38bdf8?text=Plane+Projects",
        "https://placehold.co/800x600/1e293b/38bdf8?text=Plane+Issues"
    ],
    "outline": [
        "https://placehold.co/800x600/1e293b/38bdf8?text=Outline+Documents",
        "https://placehold.co/800x600/1e293b/38bdf8?text=Outline+Search"
    ],
    "listmonk": [
        "https://placehold.co/800x600/1e293b/38bdf8?text=Listmonk+Campaigns",
        "https://placehold.co/800x600/1e293b/38bdf8?text=Listmonk+Subscribers"
    ],
    "affine": [
        "https://placehold.co/800x600/1e293b/38bdf8?text=AFFiNE+Whiteboard",
        "https://placehold.co/800x600/1e293b/38bdf8?text=AFFiNE+Documents"
    ],
}

FIXED = 0
SCREENSHOTS_ADDED = 0

for app in apps:
    app_id = app.get("id", "")
    
    # Fix missing fields for 9Router
    if app_id == "9router":
        if not app.get("forum_url"):
            app["forum_url"] = "https://github.com/9router/9router/discussions"
            FIXED += 1
    
    # Fix missing fields for ShieldSign Core
    if app_id == "shieldsign":
        if not app.get("website"):
            app["website"] = "https://github.com/KatalystDigital/shieldsign-core"
            FIXED += 1
        if not app.get("docs_url"):
            app["docs_url"] = "https://github.com/KatalystDigital/shieldsign-core#readme"
            FIXED += 1
        if not app.get("forum_url"):
            app["forum_url"] = "https://github.com/KatalystDigital/shieldsign-core/discussions"
            FIXED += 1
        if not app.get("repository_url"):
            app["repository_url"] = "https://github.com/KatalystDigital/shieldsign-core"
            FIXED += 1
    
    # Add screenshots for all apps that have an entry in SCREENSHOT_MAP
    if app_id in SCREENSHOT_MAP:
        existing = app.get("screenshots", [])
        if not existing or (isinstance(existing, list) and len(existing) == 0):
            app["screenshots"] = SCREENSHOT_MAP[app_id]
            SCREENSHOTS_ADDED += 1

# Save
with open(CATALOG_PATH, "w", encoding="utf-8") as f:
    json.dump(data, f, indent=2, ensure_ascii=False)

print(f"Done. Fixed {FIXED} link fields. Added screenshots to {SCREENSHOTS_ADDED} apps.")
