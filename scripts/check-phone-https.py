"""Health check with the same TLS/proxy environment as the project runtime."""
import json
import sys
import urllib.request

try:
    with urllib.request.urlopen(sys.argv[1].rstrip('/')+'/v1/health',timeout=12) as response:
        value=json.loads(response.read(8192))
        ok=response.status==200 and value.get('app')=='CourseInbox Reminders' and value.get('server_id')==sys.argv[2]
except Exception:
    ok=False
print(json.dumps({'ok':ok}))
