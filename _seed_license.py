"""Insert a pending license row into the running central's DB and report
the pre-issued key. For end-to-end tests against the live VPS central."""
import os
import secrets
import sqlite3
import sys

DB = os.environ.get("DB_PATH", "/data/appvault.db")
EMAIL = sys.argv[1] if len(sys.argv) > 1 else "live-test@example.com"
AGENT_ID = sys.argv[2] if len(sys.argv) > 2 else "vps-live-agent"

c = sqlite3.connect(DB)
key = "AVM-WRITERST-" + secrets.token_hex(6).upper()
c.execute(
    "INSERT INTO app_licenses (key, app_id, email, agent_id, status, expires_at) "
    "VALUES (?, 'writerstudio', ?, ?, 'pending', '2027-09-02')",
    (key, EMAIL, AGENT_ID),
)
c.commit()
c.close()
print(key)
