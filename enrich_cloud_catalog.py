#!/usr/bin/env python3
"""
Enrich appvault-cloud-prod/static/catalog.json with Cloudron-style manifest fields.
Adds: tagline, long_description, version, author, tags, website, docs_url,
      forum_url, repository_url, changelog, screenshots, emoji.
Reuses the 30 enriched apps from appvault-repo/manager/catalog.json.
Preserves ALL existing fields (Docker config, ports, env, hidden, free_tier).
"""
import json, os, shutil, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

CATALOG_PATH = r"C:\Users\emman\appvault-cloud-prod\static\catalog.json"
BACKUP_PATH = CATALOG_PATH + ".backup-enrich"
PREV_ENRICH = r"C:\Users\emman\appvault-cloud-prod\_prev_enrichment.json"

# ── Emoji per app id (for grid + detail icon) ─────────────────────────
EMOJI = {
    "owncloud": "☁️", "n8n": "📝", "pihole": "🛡️", "openwebui": "💬",
    "crewai-studio": "🤖", "hermes-agent": "🧠", "adguard": "🛡️", "wordpress": "🌐",
    "nextcloud": "📁", "onlyoffice": "📄", "gitlab": "🔧", "bookstack": "📖",
    "paperless": "🗂️", "jellyfin": "🎬", "navidrome": "🎵", "kavita": "📚",
    "photoprism": "🖼️", "immich": "📸", "wireguard": "🔐", "vaultwarden": "🔑",
    "nginx-proxy-manager": "🔄", "traefik": "🚦", "uptime-kuma": "📊", "portainer": "🐳",
    "dozzle": "📜", "code-server": "💻", "gitea": "🐙", "stirling-pdf": "📄",
    "excalidraw": "✏️", "drawio": "📐", "9router": "🔀", "documenso": "✍️",
    "twenty": "🤝", "shieldsign": "🛡️", "anythingllm": "🤖", "searxng": "🔎",
    "dify": "🧩", "librechat": "💬", "comfyui": "🎨", "openhands": "🖐️",
    "khoj": "🧘", "wg-easy": "🔐", "mattermost": "💬", "baserow": "🗄️",
    "umami": "📈", "ghost": "👻", "directus": "🗃️", "formbricks": "📋",
    "chatwoot": "💬", "plane": "✈️", "outline": "📘", "listmonk": "📧",
    "affine": "📝",
    # hidden/infra
    "central-mariadb": "🗄️", "central-postgres": "🐘", "central-redis": "⚡",
    "central-mongo": "🍃", "immich-machine-learning": "🧠", "openmaic": "🤖",
    "appflowy": "📝",
}

# ── New enrichment for apps NOT in the repo catalog ───────────────────
NEW_ENRICHMENT = {
    "9router": {
        "tagline": "Universal AI router for 200+ models",
        "long_description": "9Router is a universal API router that gives you one endpoint to access 200+ AI models from a single key. It normalizes providers, handles failover and load balancing across models, and simplifies switching between OpenAI, Anthropic, and open models without changing code. Features include unified API format, provider failover, cost tracking, and a single billing interface.",
        "version": "1.0.0",
        "author": "9Router",
        "tags": ["ai", "llm", "router", "api", "gateway"],
        "website": "https://9router.com",
        "docs_url": "https://docs.9router.com",
        "forum_url": "",
        "repository_url": "https://github.com/9router/9router",
        "changelog": "AppVault catalog release - universal AI model router.",
        "screenshots": []
    },
    "documenso": {
        "tagline": "Open-source DocuSign alternative",
        "long_description": "Documenso is an open-source digital signature platform - a transparent alternative to DocuSign and HelloSign. It lets you send, sign, and manage documents entirely on your own infrastructure. Features include legally-binding e-signatures, document templates, signing workflows with multiple recipients, audit trails, and full data ownership.",
        "version": "2.2.0",
        "author": "Documenso",
        "tags": ["esignature", "documents", "legal", "productivity"],
        "website": "https://documenso.com",
        "docs_url": "https://docs.documenso.com",
        "forum_url": "https://github.com/documenso/documenso/discussions",
        "repository_url": "https://github.com/documenso/documenso",
        "changelog": "AppVault catalog release - open-source digital signing.",
        "screenshots": []
    },
    "twenty": {
        "tagline": "Open-source CRM - modern alternative to Salesforce",
        "long_description": "Twenty is an open-source CRM designed to be a modern, community-driven alternative to Salesforce. It provides contact and company management, pipeline tracking, email integration, and customizable views - all in a clean, fast interface. Features include a flexible data model, global search, keyboard-first navigation, and full self-hosting.",
        "version": "0.30.0",
        "author": "Twenty",
        "tags": ["crm", "sales", "productivity", "customers"],
        "website": "https://twenty.com",
        "docs_url": "https://twenty.com/developers",
        "forum_url": "https://github.com/twentyhq/twenty/discussions",
        "repository_url": "https://github.com/twentyhq/twenty",
        "changelog": "AppVault catalog release - open-source CRM platform.",
        "screenshots": []
    },
    "shieldsign": {
        "tagline": "Secure document signing core",
        "long_description": "ShieldSign Core is a security-focused document signing service that manages signature workflows with end-to-end encryption. It provides digital signatures, document integrity verification, and signing audit trails. Features include cryptographic signing, tamper-evident logs, and integration-ready APIs for your document pipeline.",
        "version": "1.0.0",
        "author": "AppVault / ShieldSign",
        "tags": ["security", "signature", "documents", "encryption"],
        "website": "",
        "docs_url": "",
        "forum_url": "",
        "repository_url": "",
        "changelog": "AppVault catalog release - secure signing core service.",
        "screenshots": []
    },
    "anythingllm": {
        "tagline": "All-in-one AI workspace with RAG",
        "long_description": "AnythingLLM is an all-in-one AI workspace that combines documents, AI agents, and chat into a single interface. It turns any document, web page, or text into context for your LLM with built-in RAG. Features include multi-user workspaces, document ingestion (PDF, DOCX, URLs), agent skills, whisper transcription, and support for any LLM - local or cloud.",
        "version": "1.5.0",
        "author": "Mintplex Labs",
        "tags": ["ai", "rag", "llm", "chat", "workspace"],
        "website": "https://anythingllm.com",
        "docs_url": "https://docs.anythingllm.com",
        "forum_url": "https://github.com/Mintplex-Labs/anything-llm/discussions",
        "repository_url": "https://github.com/Mintplex-Labs/anything-llm",
        "changelog": "AppVault catalog release - AI workspace with RAG and agents.",
        "screenshots": []
    },
    "searxng": {
        "tagline": "Privacy-first metasearch engine",
        "long_description": "SearXNG is a privacy-respecting, hackable metasearch engine that queries 70+ search engines and aggregates results without tracking you. It removes the need to use commercial search engines directly - no profiling, no cookies, no ads. Features include result aggregation, search categories (web, images, videos, news), instant answers, and complete self-hosting.",
        "version": "2024.7.1",
        "author": "SearXNG Team",
        "tags": ["search", "privacy", "metasearch", "networking"],
        "website": "https://docs.searxng.org",
        "docs_url": "https://docs.searxng.org",
        "forum_url": "https://github.com/searxng/searxng/discussions",
        "repository_url": "https://github.com/searxng/searxng",
        "changelog": "AppVault catalog release - private metasearch engine.",
        "screenshots": []
    },
    "dify": {
        "tagline": "LLMOps platform to build AI apps visually",
        "long_description": "Dify is an open-source LLMOps platform that lets you build AI applications visually - from RAG pipelines to agentic workflows. It includes a visual workflow builder, prompt management, model marketplace, RAG engine with document ingestion, observability, and a complete API for integrating AI into your products. Built for developers and non-developers alike.",
        "version": "0.6.0",
        "author": "LangGenius",
        "tags": ["ai", "llmops", "rag", "workflow", "agents"],
        "website": "https://dify.ai",
        "docs_url": "https://docs.dify.ai",
        "forum_url": "https://github.com/langgenius/dify/discussions",
        "repository_url": "https://github.com/langgenius/dify",
        "changelog": "AppVault catalog release - visual LLMOps platform.",
        "screenshots": []
    },
    "librechat": {
        "tagline": "Open-source ChatGPT-style interface for any model",
        "long_description": "LibreChat is an open-source, self-hosted AI chat platform that unifies multiple AI providers into one interface. Use ChatGPT, Claude, Gemini, or local models side-by-side with shared conversation history. Features include multi-model chats, custom agents, file uploads with vision, code interpreter, plugins, and a polished UI inspired by ChatGPT.",
        "version": "0.7.0",
        "author": "LibreChat",
        "tags": ["ai", "chat", "llm", "multi-model"],
        "website": "https://www.librechat.ai",
        "docs_url": "https://www.librechat.ai/docs",
        "forum_url": "https://github.com/danny-avila/LibreChat/discussions",
        "repository_url": "https://github.com/danny-avila/LibreChat",
        "changelog": "AppVault catalog release - unified multi-provider AI chat.",
        "screenshots": []
    },
    "comfyui": {
        "tagline": "Node-based AI image generation",
        "long_description": "ComfyUI is a powerful node-based interface for Stable Diffusion and other image generation models. Design complex workflows visually - connect models, samplers, and controls with a modular graph editor. Features include full control over the generation pipeline, custom nodes, workflow sharing, video generation support, and GPU acceleration.",
        "version": "0.2.0",
        "author": "Comfy Org",
        "tags": ["ai", "image-generation", "stable-diffusion", "workflow"],
        "website": "https://www.comfy.org",
        "docs_url": "https://docs.comfy.org",
        "forum_url": "https://github.com/comfyanonymous/ComfyUI/discussions",
        "repository_url": "https://github.com/comfyanonymous/ComfyUI",
        "changelog": "AppVault catalog release - node-based AI image generation.",
        "screenshots": []
    },
    "openhands": {
        "tagline": "AI software engineering agents",
        "long_description": "OpenHands (formerly OpenDevin) is a platform for AI software engineers that can write code, run commands, browse the web, and collaborate with you on real projects. Delegate complex coding tasks to autonomous agents that operate in a sandboxed environment. Features include terminal access, file editing, web browsing, and integration with your repositories.",
        "version": "0.18.0",
        "author": "All Hands AI",
        "tags": ["ai", "coding", "agents", "developer"],
        "website": "https://all-hands.dev",
        "docs_url": "https://docs.all-hands.dev",
        "forum_url": "https://github.com/All-Hands-AI/OpenHands/discussions",
        "repository_url": "https://github.com/All-Hands-AI/OpenHands",
        "changelog": "AppVault catalog release - autonomous AI coding agents.",
        "screenshots": []
    },
    "khoj": {
        "tagline": "AI second brain for your notes and documents",
        "long_description": "Khoj is a self-hosted AI assistant that creates a searchable second brain from your notes, documents, and knowledge base. It indexes Markdown, PDFs, and web content, then lets you chat with your data using your preferred LLM. Features include semantic search, daily summaries, scheduled research, and integration with Obsidian and Emacs.",
        "version": "1.35.0",
        "author": "Khoj AI",
        "tags": ["ai", "notes", "search", "rag", "knowledge"],
        "website": "https://khoj.dev",
        "docs_url": "https://docs.khoj.dev",
        "forum_url": "https://github.com/khoj-ai/khoj/discussions",
        "repository_url": "https://github.com/khoj-ai/khoj",
        "changelog": "AppVault catalog release - AI second brain for documents.",
        "screenshots": []
    },
    "wg-easy": {
        "tagline": "WireGuard VPN with a simple web UI",
        "long_description": "WG-Easy is the easiest way to run a WireGuard VPN - a web UI where you create and manage VPN clients with one click. Generate configs, QR codes, and manage access without touching the command line. Features include a responsive dashboard, client management with QR codes, traffic stats, and automatic restart policies.",
        "version": "14.0.0",
        "author": "WeeJeWel",
        "tags": ["vpn", "wireguard", "networking", "privacy"],
        "website": "https://github.com/wg-easy/wg-easy",
        "docs_url": "https://github.com/wg-easy/wg-easy",
        "forum_url": "https://github.com/wg-easy/wg-easy/discussions",
        "repository_url": "https://github.com/wg-easy/wg-easy",
        "changelog": "AppVault catalog release - WireGuard VPN with web UI.",
        "screenshots": []
    },
    "mattermost": {
        "tagline": "Self-hosted team communication",
        "long_description": "Mattermost is a self-hosted Slack alternative for secure team collaboration. Keep conversations, files, and integrations on your own infrastructure with complete control. Features include channels and direct messages, voice calls, file sharing, playbooks for incident response, integrations with 1000+ tools, and compliance-ready enterprise features.",
        "version": "9.11.0",
        "author": "Mattermost",
        "tags": ["chat", "team", "communication", "productivity"],
        "website": "https://mattermost.com",
        "docs_url": "https://docs.mattermost.com",
        "forum_url": "https://community.mattermost.com",
        "repository_url": "https://github.com/mattermost/mattermost",
        "changelog": "AppVault catalog release - self-hosted team collaboration.",
        "screenshots": []
    },
    "baserow": {
        "tagline": "Open-source no-code database",
        "long_description": "Baserow is an open-source no-code database and app builder - think Airtable that you fully own. Create tables, link records, build views (grid, gallery, kanban, calendar), and share them with your team. Features include a drag-and-drop UI, API access, formulas, permissions, and a plugin ecosystem.",
        "version": "1.25.0",
        "author": "Baserow",
        "tags": ["database", "nocode", "spreadsheet", "productivity"],
        "website": "https://baserow.io",
        "docs_url": "https://baserow.io/docs",
        "forum_url": "https://community.baserow.io",
        "repository_url": "https://gitlab.com/baserow/baserow",
        "changelog": "AppVault catalog release - no-code database platform.",
        "screenshots": []
    },
    "umami": {
        "tagline": "Privacy-friendly Google Analytics alternative",
        "long_description": "Umami is a simple, fast, privacy-focused web analytics tool - a lightweight alternative to Google Analytics. Track website visitors without cookies or personal data, fully GDPR-compliant. Features include real-time analytics, event tracking, custom dashboards, team sharing, and a tiny footprint that won't slow your site.",
        "version": "2.10.0",
        "author": "Umami Software",
        "tags": ["analytics", "privacy", "monitoring", "web"],
        "website": "https://umami.is",
        "docs_url": "https://umami.is/docs",
        "forum_url": "https://github.com/umami-software/umami/discussions",
        "repository_url": "https://github.com/umami-software/umami",
        "changelog": "AppVault catalog release - privacy-friendly web analytics.",
        "screenshots": []
    },
    "ghost": {
        "tagline": "Modern publishing platform for creators",
        "long_description": "Ghost is a powerful, modern publishing platform for creators - blogs, newsletters, and membership sites. Built for speed and SEO with a distraction-free editor. Features include memberships and subscriptions, email newsletters, scheduled posts, analytics, themes, and a clean API for integrations.",
        "version": "5.0.0",
        "author": "Ghost Foundation",
        "tags": ["blogging", "publishing", "newsletter", "cms"],
        "website": "https://ghost.org",
        "docs_url": "https://ghost.org/docs",
        "forum_url": "https://forum.ghost.org",
        "repository_url": "https://github.com/TryGhost/Ghost",
        "changelog": "AppVault catalog release - modern publishing platform.",
        "screenshots": []
    },
    "directus": {
        "tagline": "Headless CMS with a data-first approach",
        "long_description": "Directus is an open-source headless CMS that wraps any SQL database with a REST and GraphQL API plus a no-code admin app. Manage content, media, and users visually while exposing everything through APIs. Features include role-based permissions, custom workflows, file management, and instant REST/GraphQL endpoints.",
        "version": "10.13.0",
        "author": "Monospace Inc",
        "tags": ["cms", "headless", "database", "api"],
        "website": "https://directus.io",
        "docs_url": "https://docs.directus.io",
        "forum_url": "https://github.com/directus/directus/discussions",
        "repository_url": "https://github.com/directus/directus",
        "changelog": "AppVault catalog release - headless CMS for any SQL database.",
        "screenshots": []
    },
    "formbricks": {
        "tagline": "Open-source experience management",
        "long_description": "Formbricks is an open-source platform for surveys, feedback, and in-product experiences - a privacy-friendly alternative to Typeform and Qualtrics. Build beautiful surveys, deploy them in-product or on your site, and analyze responses. Features include in-app surveys, link surveys, user targeting, and a powerful analytics dashboard.",
        "version": "2.2.0",
        "author": "Formbricks",
        "tags": ["surveys", "feedback", "productivity", "analytics"],
        "website": "https://formbricks.com",
        "docs_url": "https://formbricks.com/docs",
        "forum_url": "https://github.com/formbricks/formbricks/discussions",
        "repository_url": "https://github.com/formbricks/formbricks",
        "changelog": "AppVault catalog release - open-source survey platform.",
        "screenshots": []
    },
    "chatwoot": {
        "tagline": "Open-source customer support platform",
        "long_description": "Chatwoot is an open-source customer engagement and support platform - a self-hosted alternative to Intercom and Zendesk. Manage conversations from web chat, email, and social channels in one inbox. Features include live chat widgets, shared inbox, helpdesk with agent assignment, automation, canned responses, and analytics.",
        "version": "3.8.0",
        "author": "Chatwoot",
        "tags": ["support", "chat", "helpdesk", "customer-service"],
        "website": "https://www.chatwoot.com",
        "docs_url": "https://www.chatwoot.com/docs",
        "forum_url": "https://github.com/chatwoot/chatwoot/discussions",
        "repository_url": "https://github.com/chatwoot/chatwoot",
        "changelog": "AppVault catalog release - open-source support platform.",
        "screenshots": []
    },
    "plane": {
        "tagline": "Open-source project management",
        "long_description": "Plane is an open-source project management tool - a Jira alternative for planning, tracking, and launching software. Use issues, cycles, and modules to organize work with a clean, fast interface. Features include project views (list, board, calendar), issue tracking, sprint planning, page docs, and real-time collaboration.",
        "version": "0.21.0",
        "author": "Plane",
        "tags": ["project-management", "issues", "productivity", "agile"],
        "website": "https://plane.so",
        "docs_url": "https://docs.plane.so",
        "forum_url": "https://github.com/makeplane/plane/discussions",
        "repository_url": "https://github.com/makeplane/plane",
        "changelog": "AppVault catalog release - open-source project management.",
        "screenshots": []
    },
    "outline": {
        "tagline": "Team knowledge base and wiki",
        "long_description": "Outline is a beautiful, real-time team knowledge base for documentation and wikis. Designed for speed with a modern editor and instant search. Features include nested document structures, collaborative editing, rich text with embeds, team collections, full-text search, and integrations with Slack and other tools.",
        "version": "0.78.0",
        "author": "Outline",
        "tags": ["wiki", "knowledge-base", "docs", "team"],
        "website": "https://www.getoutline.com",
        "docs_url": "https://docs.getoutline.com",
        "forum_url": "https://github.com/outline/outline/discussions",
        "repository_url": "https://github.com/outline/outline",
        "changelog": "AppVault catalog release - real-time team knowledge base.",
        "screenshots": []
    },
    "listmonk": {
        "tagline": "Self-hosted newsletter and mailing list manager",
        "long_description": "Listmonk is a self-hosted, high-performance newsletter and mailing list manager - a privacy-friendly alternative to Mailchimp. Manage subscribers, campaigns, and templates with a fast, modern UI. Features include double opt-in, campaign scheduling, subscriber segmentation, template builder, and an API for automation.",
        "version": "2.6.0",
        "author": "Listmonk",
        "tags": ["newsletter", "email", "marketing", "productivity"],
        "website": "https://listmonk.app",
        "docs_url": "https://listmonk.app/docs",
        "forum_url": "https://github.com/knadh/listmonk/discussions",
        "repository_url": "https://github.com/knadh/listmonk",
        "changelog": "AppVault catalog release - self-hosted mailing list manager.",
        "screenshots": []
    },
    "affine": {
        "tagline": "Open-source knowledge base with AI",
        "long_description": "AFFiNE is an open-source, privacy-first knowledge base that combines docs, whiteboards, and databases in one tool. It's a Notion alternative with local-first storage and optional collaboration. Features include editable blocks, infinite whiteboards, linked databases, local data ownership, and AI-powered writing assistance.",
        "version": "0.16.0",
        "author": "AFFiNE",
        "tags": ["knowledge-base", "docs", "whiteboard", "productivity"],
        "website": "https://affine.pro",
        "docs_url": "https://docs.affine.pro",
        "forum_url": "https://github.com/toeverything/AFFiNE/discussions",
        "repository_url": "https://github.com/toeverything/AFFiNE",
        "changelog": "AppVault catalog release - open-source knowledge base with AI.",
        "screenshots": []
    },
}

def main():
    # Load previous enrichment (30 apps from repo)
    with open(PREV_ENRICH, encoding="utf-8") as f:
        prev = json.load(f)

    # Load current catalog
    with open(CATALOG_PATH, encoding="utf-8") as f:
        cat = json.load(f)

    # Backup
    if not os.path.exists(BACKUP_PATH):
        shutil.copy2(CATALOG_PATH, BACKUP_PATH)
        print(f"Backup: {BACKUP_PATH}")

    apps = cat.get("apps", [])
    enriched = 0
    for app in apps:
        aid = app.get("id", "")
        meta = prev.get(aid) or NEW_ENRICHMENT.get(aid)
        if meta:
            for k, v in meta.items():
                app[k] = v
            enriched += 1
        # Always set emoji if we have one
        if aid in EMOJI:
            app["emoji"] = EMOJI[aid]

    with open(CATALOG_PATH, "w", encoding="utf-8") as f:
        json.dump(cat, f, indent=2, ensure_ascii=False)

    print(f"Enriched {enriched} apps (metadata) + emojis on {len(EMOJI)} apps")
    print(f"Total apps: {len(apps)}")

    # Verify
    missing = [a["id"] for a in apps if not a.get("hidden") and not (a.get("tagline") or a.get("long_description"))]
    print(f"Visible apps still missing enrichment: {len(missing)}")
    for m in missing:
        print("  -", m)

if __name__ == "__main__":
    main()
