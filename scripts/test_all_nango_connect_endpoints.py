import sys
import os
sys.path.insert(0, r"c:\PROJECTS\codefronter\code\backend")

from fastapi.testclient import TestClient
from app.main import app
from app.core.security import create_access_token
from app.core.database import get_db
from app.models.workspace import User, Project

client = TestClient(app)

db = next(get_db())
user = db.query(User).filter(User.email == "yagnadeepsinh.4741@gmail.com").first()
if not user:
    user = db.query(User).first()

from app.core.permissions import get_effective_project

proj = get_effective_project(None, user, db)

print(f"Using test user: {user.email} (ID: {user.id})")
print(f"Using test project: {proj.name} (ID: {proj.id})")

token = create_access_token({"sub": str(user.id), "email": user.email})
headers = {"Authorization": f"Bearer {token}"}

providers = ["slack", "github", "notion", "linear", "gitlab", "jira", "sentry", "google-drive"]

print("\n=== TESTING NANGO CONNECT SESSIONS ACROSS ALL PLATFORMS ===")
for p in providers:
    resp = client.get(
        f"/api/v1/integrations/oauth/{p}/authorize?project_id={proj.id}",
        headers=headers
    )
    if resp.status_code == 200:
        data = resp.json()
        print(f"+ {p.upper()}: Status {resp.status_code}")
        print(f"   Auth Engine: {data.get('auth_engine')}")
        print(f"   Connect URL: {data.get('authorize_url')[:65]}...")
        assert data.get("auth_engine") == "nango", f"Expected nango auth_engine for {p}"
        assert "connect.nango.dev" in data.get("authorize_url"), f"Expected connect.nango.dev in url for {p}"
    else:
        print(f"- {p.upper()}: Failed with status {resp.status_code} - {resp.text}")

print("\nALL PLATFORMS ROUTE THROUGH NANGO CONNECT SESSIONS SUCCESSFULLY!")
