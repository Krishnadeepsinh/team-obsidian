import time
import requests
from playwright.sync_api import sync_playwright

API_BASE = "http://localhost:8000/api/v1"
WEB_BASE = "http://localhost:3000"

email = "lead.architect@team-obsidian.io"
password = "ObsidianSecurePassword2026!"

# Make sure user exists
session = requests.Session()
login_res = session.post(f"{API_BASE}/auth/login", json={"email": email, "password": password})
if login_res.status_code != 200:
    reg_res = session.post(f"{API_BASE}/auth/register", json={
        "name": "Yagnadeepsinh Vaghela",
        "email": email,
        "password": password,
        "role": "tech_lead",
        "title": "Lead Software Architect",
        "department": "Engineering"
    })
    token = reg_res.json().get("access_token")
else:
    token = login_res.json().get("access_token")

# Seed demo data if needed
session.headers.update({"Authorization": f"Bearer {token}"})
try:
    session.post(f"{API_BASE}/seed/demo")
except Exception as e:
    print("Seed info:", e)

with sync_playwright() as p:
    browser = p.chromium.launch(
        executable_path="C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe",
        headless=True,
        args=["--disable-gpu", "--no-sandbox"]
    )
    context = browser.new_context(
        viewport={"width": 1440, "height": 920},
        device_scale_factor=1.5
    )
    page = context.new_page()

    # 1. Login via UI
    print("Logging in via UI...")
    page.goto(f"{WEB_BASE}/login", wait_until="networkidle")
    page.fill("input[type='email']", email)
    page.fill("input[type='password']", password)
    page.click("button[type='submit']")
    page.wait_for_timeout(3500)
    print("Current URL after login:", page.url)

    # 2. Capture Dashboard
    print("Capturing Dashboard...")
    page.goto(f"{WEB_BASE}/", wait_until="networkidle")
    page.wait_for_timeout(2500)
    page.screenshot(path="docs/screenshots/dashboard.png", full_page=False)

    # 3. Capture AI Assistant
    print("Capturing AI Assistant...")
    page.goto(f"{WEB_BASE}/assistant", wait_until="networkidle")
    page.wait_for_timeout(1500)
    # Type question to show live assistant interaction
    page.fill("input[placeholder*='Ask a technical question']", "how many repo are there in my github")
    page.press("input[placeholder*='Ask a technical question']", "Enter")
    page.wait_for_timeout(4500)
    page.screenshot(path="docs/screenshots/ai_assistant.png", full_page=False)

    # 4. Capture Knowledge Graph
    print("Capturing Knowledge Graph...")
    page.goto(f"{WEB_BASE}/knowledge/graph", wait_until="networkidle")
    page.wait_for_timeout(3500)
    page.screenshot(path="docs/screenshots/knowledge_graph.png", full_page=False)

    # 5. Capture Handover Dossier
    print("Capturing Handover Dossier...")
    page.goto(f"{WEB_BASE}/handover", wait_until="networkidle")
    page.wait_for_timeout(2500)
    page.screenshot(path="docs/screenshots/handover_dossier.png", full_page=False)

    # 6. Capture Integrations Hub
    print("Capturing Integrations Hub...")
    page.goto(f"{WEB_BASE}/integrations", wait_until="networkidle")
    page.wait_for_timeout(2500)
    page.screenshot(path="docs/screenshots/integrations.png", full_page=False)

    browser.close()
    print("All real live screenshots successfully captured!")
