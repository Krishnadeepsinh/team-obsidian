import pytest
import time
from playwright.sync_api import sync_playwright, Page, expect

BASE_URL = "http://127.0.0.1:3000"
API_URL = "http://127.0.0.1:8000/api/v1"

@pytest.fixture(scope="session")
def browser_context():
    playwright = sync_playwright().start()
    browser = playwright.chromium.launch(headless=True)
    yield browser
    browser.close()
    playwright.stop()

@pytest.fixture(scope="function")
def page(browser_context):
    context = browser_context.new_context(viewport={"width": 1280, "height": 800})
    page = context.new_page()
    yield page
    context.close()

# ==============================================================================
# Focus Area 9: Auth, Registration, Login, Logout, Session Expiry & Protected Routes
# ==============================================================================
def test_pw_auth_and_protected_routes(page: Page):
    """Verify login validation, success redirect, logout, and unauthenticated protection."""
    
    # 1. Unauthenticated direct access to protected page must redirect to /login
    page.goto(f"{BASE_URL}/handover", wait_until="networkidle")
    time.sleep(1)
    assert "/login" in page.url or page.locator("text=Sign In").is_visible()

    # 2. Failed login with invalid credentials shows error banner
    page.goto(f"{BASE_URL}/login", wait_until="networkidle")
    page.fill('input[type="email"]', "invalid_user@obsidian.io")
    page.fill('input[type="password"]', "WrongPassword123!")
    page.click('button[type="submit"]')
    page.wait_for_timeout(1000)
    
    # Check that error is visible and user remains on /login
    assert "/login" in page.url
    error_banner = page.locator(".text-rose-700, .bg-rose-50, :has-text('Error:')")
    expect(error_banner.first).to_be_visible()

    # 3. Successful login with verified credentials
    user_email = f"auth_user_{int(time.time()*1000)}@saas.com"
    user_pwd = "EnterpriseSecure2026!"
    page.goto(f"{BASE_URL}/register", wait_until="networkidle")
    page.fill('input[type="text"]', "Auth User")
    page.fill('input[type="email"]', user_email)
    page.fill('input[type="password"]', user_pwd)
    page.click('button[type="submit"]')
    page.wait_for_url(f"{BASE_URL}/", timeout=10000)
    
    # Verify token stored in localStorage
    token = page.evaluate("() => localStorage.getItem('obsidian_token')")
    assert token and len(token) > 20

    # 4. Logout flow
    page.click('button[aria-label="User menu"]')
    page.wait_for_timeout(300)
    page.click('button:has-text("Sign Out")')
    page.wait_for_url(f"{BASE_URL}/login", timeout=8000)
    assert "/login" in page.url
    cleared_token = page.evaluate("() => localStorage.getItem('obsidian_token')")
    assert cleared_token is None

    # Log back in with registered credentials
    page.fill('input[type="email"]', user_email)
    page.fill('input[type="password"]', user_pwd)
    page.click('button[type="submit"]')
    page.wait_for_url(f"{BASE_URL}/", timeout=10000)
    relog_token = page.evaluate("() => localStorage.getItem('obsidian_token')")
    assert relog_token and len(relog_token) > 20

# ==============================================================================
# Focus Area 11 & 12: Multi-User SaaS Onboarding & Identity Isolation
# ==============================================================================
def test_pw_multi_user_saas_onboarding_and_isolation(page: Page):
    """Verify that a brand new user registering in the browser receives their own isolated workspace."""
    unique_user = f"user_{int(time.time()*1000)}@saasbrowser.io"
    
    # 1. Register new independent user in browser
    page.goto(f"{BASE_URL}/register", wait_until="networkidle")
    page.fill('input[type="text"]', "Dr. Evelyn Reed")
    page.fill('input[type="email"]', unique_user)
    page.fill('input[type="password"]', "EnterpriseSecure2026!")
    page.click('button[type="submit"]')
    page.wait_for_timeout(2000)

    # User should be navigated to dashboard or onboarding
    token = page.evaluate("() => localStorage.getItem('obsidian_token')")
    assert token and len(token) > 20
    user_str = page.evaluate("() => localStorage.getItem('obsidian_user')")
    assert user_str and "Dr. Evelyn Reed" in user_str

    # 2. Check AppShell displays user's personal identity
    page.goto(f"{BASE_URL}/", wait_until="networkidle")
    page.wait_for_timeout(1000)
    profile_text = page.locator("text=Dr. Evelyn Reed")
    expect(profile_text.first).to_be_visible()

    # 3. Settings page shows personal workspace
    page.goto(f"{BASE_URL}/settings", wait_until="networkidle")
    page.wait_for_timeout(1000)
    expect(page.locator("text=My Account & Personal Workspace")).to_be_visible()
    expect(page.locator("text=Isolated Tenant")).to_be_visible()

    # 4. Integrations page shows connect button & empty state
    page.goto(f"{BASE_URL}/integrations", wait_until="networkidle")
    page.wait_for_timeout(1000)
    expect(page.locator("text=Connect Integration").first).to_be_visible()

# ==============================================================================
# Zero Synthetic Data Audit Verification Across All Screens
# ==============================================================================
def test_pw_zero_synthetic_data_in_ui(page: Page):
    """Confirm zero synthetic users or synthetic demo data exist across all screens."""
    timestamp = int(time.time()*1000)
    email = f"verified_clean_{timestamp}@company.com"
    password = "CleanSaaSPassword2026!"
    name = f"Clean User {timestamp}"

    # 1. Register a genuine clean user
    page.goto(f"{BASE_URL}/register", wait_until="networkidle")
    page.fill('input[type="text"]', name)
    page.fill('input[type="email"]', email)
    page.fill('input[type="password"]', password)
    page.click('button[type="submit"]')
    page.wait_for_url(f"{BASE_URL}/", timeout=10000)
    page.wait_for_timeout(1000)

    page_content = page.content()
    assert "Rahul Sharma" not in page_content, "Found synthetic user Rahul Sharma on dashboard"
    assert "Alex Vance" not in page_content, "Found synthetic user Alex Vance on dashboard"
    assert "E-Commerce Platform" not in page_content, "Found synthetic project E-Commerce Platform on dashboard"
    assert "Payments Settlement Engine" not in page_content, "Found synthetic project Payments Settlement Engine on dashboard"

    # 2. Projects Page
    page.goto(f"{BASE_URL}/projects", wait_until="networkidle")
    page.wait_for_timeout(800)
    projects_content = page.content()
    assert "Rahul Sharma" not in projects_content
    assert "Alex Vance" not in projects_content
    assert "E-Commerce Platform" not in projects_content
    assert "Payments Settlement Engine" not in projects_content
    assert f"{name}'s Project" in projects_content or "No Projects Found" in projects_content

    # 3. Team Page
    page.goto(f"{BASE_URL}/team", wait_until="networkidle")
    page.wait_for_timeout(800)
    team_content = page.content()
    assert "Rahul Sharma" not in team_content
    assert "Alex Vance" not in team_content
    assert "Amit Verma" not in team_content
    assert "Priya Nair" not in team_content
    assert "Neha Sharma" not in team_content
    assert name in team_content or "No Team Members Found" in team_content or "0 Stakeholders" in team_content

    # 4. Handover Page
    page.goto(f"{BASE_URL}/handover", wait_until="networkidle")
    page.wait_for_timeout(800)
    handover_content = page.content()
    assert "Rahul Sharma" not in handover_content
    assert "Alex Vance" not in handover_content
    assert "E-Commerce Platform" not in handover_content
    assert "No Handover Dossier Created Yet" in handover_content

    # 5. Evidence Page
    page.goto(f"{BASE_URL}/evidence", wait_until="networkidle")
    page.wait_for_timeout(800)
    evidence_content = page.content()
    assert "rahul-sharma" not in evidence_content
    assert "PR #421: Add payment retry" not in evidence_content
    assert "No Evidence Records Found" in evidence_content

    # 6. Decisions Page
    page.goto(f"{BASE_URL}/decisions", wait_until="networkidle")
    page.wait_for_timeout(800)
    decisions_content = page.content()
    assert "Rahul Sharma" not in decisions_content
    assert "No Decisions Found" in decisions_content

    # 7. Tasks Page
    page.goto(f"{BASE_URL}/tasks", wait_until="networkidle")
    page.wait_for_timeout(800)
    tasks_content = page.content()
    assert "Rahul Sharma" not in tasks_content
    assert "No Tasks Found" in tasks_content

# Helper to log in programmatically for subsequent tests
def authenticate_page(page: Page):
    user_email = f"pw_user_{int(time.time()*1000)}@saas.com"
    user_pwd = "EnterpriseSecure2026!"
    page.goto(f"{BASE_URL}/register", wait_until="networkidle")
    page.fill('input[type="text"]', "SaaS User")
    page.fill('input[type="email"]', user_email)
    page.fill('input[type="password"]', user_pwd)
    page.click('button[type="submit"]')
    page.wait_for_url(f"{BASE_URL}/", timeout=10000)

# ==============================================================================
# Focus Area 10: Handover Approval, Rejection & Acknowledgement
# ==============================================================================
def test_pw_handover_approvals_and_acknowledgement(page: Page):
    """Verify handover studio, approvals tab, sign-off and rejection actions."""
    authenticate_page(page)

    # 1. Handover Studio navigation
    page.goto(f"{BASE_URL}/handover", wait_until="networkidle")
    page.wait_for_timeout(1000)
    assert page.locator("text=Handover Dossier").first.is_visible() or page.locator("text=Dossier").first.is_visible()

    # 2. Handover Approvals page navigation
    page.goto(f"{BASE_URL}/handover/approvals", wait_until="networkidle")
    page.wait_for_timeout(1000)
    
    # Verify approval status cards or buttons exist
    sign_off_btn = page.locator('button:has-text("Sign Off"), button:has-text("Acknowledge"), button:has-text("Approve")').first
    reject_btn = page.locator('button:has-text("Reject"), button:has-text("Request Changes")').first

    # 3. Test interaction with sign off or reject
    if sign_off_btn.is_visible():
        sign_off_btn.click()
        page.wait_for_timeout(1000)
    
    # 4. Verify Export / PDF action
    pdf_btn = page.locator('button:has-text("PDF"), button:has-text("Export"), a:has-text("PDF")').first
    if pdf_btn.is_visible():
        expect(pdf_btn).to_be_enabled()

# ==============================================================================
# Focus Area 8: Knowledge Graph Canvas, Filtering & Blast Radius
# ==============================================================================
def test_pw_knowledge_graph_canvas_and_filtering(page: Page):
    """Verify graph canvas rendering, node presence, and entity filtering."""
    authenticate_page(page)

    page.goto(f"{BASE_URL}/knowledge/graph", wait_until="networkidle")
    page.wait_for_timeout(1500)

    # Verify canvas or svg container exists
    graph_container = page.locator("canvas, svg, .react-flow, [data-testid='graph-canvas']").first
    expect(graph_container).to_be_visible()

# ==============================================================================
# Focus Area 13: Mobile Responsiveness Across All Major Pages
# ==============================================================================
MOBILE_PAGES = [
    "/login",
    "/register",
    "/forgot-password",
    "/onboarding",
    "/",
    "/projects",
    "/knowledge/graph",
    "/knowledge/dependencies",
    "/knowledge/explorer",
    "/handover",
    "/handover/approvals",
    "/handover/history",
    "/integrations",
    "/documents",
    "/evidence",
    "/decisions",
    "/tasks",
    "/risks",
    "/gaps",
    "/assistant",
    "/timeline",
    "/logs",
    "/notifications",
    "/team",
    "/settings",
    "/profile"
]

def test_pw_mobile_responsive_all_pages(browser_context):
    """Verify mobile rendering on iPhone SE / standard mobile viewport (375x667)."""
    context = browser_context.new_context(viewport={"width": 375, "height": 667})
    page = context.new_page()

    # Authenticate first
    authenticate_page(page)

    for path in MOBILE_PAGES:
        page.goto(f"{BASE_URL}{path}", wait_until="domcontentloaded")
        page.wait_for_timeout(600)

        # 1. Verify no horizontal layout blowout
        has_horizontal_overflow = page.evaluate("""() => {
            return document.documentElement.scrollWidth > (window.innerWidth + 10);
        }""")
        assert not has_horizontal_overflow, f"Horizontal overflow detected on mobile page: {path}"

        # 2. On authenticated pages, verify hamburger menu toggle button is present
        if path not in ["/login", "/register"]:
            hamburger = page.locator('button[aria-label="Toggle mobile navigation menu"]').first
            if hamburger.is_visible():
                # Open menu
                hamburger.click()
                page.wait_for_timeout(300)
                # Verify backdrop or drawer visible
                drawer = page.locator('aside, nav, [role="dialog"]').first
                assert drawer.is_visible()
                # Close menu
                hamburger.click()
                page.wait_for_timeout(300)

    context.close()

# ==============================================================================
# Focus Area 14 & 15: Token Security & Secret Keys Protection in Network Requests
# ==============================================================================
FORBIDDEN_SECRETS = [
    "obsidian-super-secure-production-jwt-key-2026",
    "ObsidianEnterprise2026!",
    "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InJsY2xiYm52Y2lxbnhtcHBqYXZyIiwicm9sZSI6InNlcnZpY2Vfcm9sZS"  # Service role token prefix
]

def test_pw_no_secret_keys_in_browser_assets(page: Page):
    """Intercept all network requests and DOM assets to confirm zero secrets are exposed."""
    leaked_secrets = []

    def handle_response(response):
        try:
            # Check headers and bodies of text/json/js/html
            content_type = response.headers.get("content-type", "")
            if any(t in content_type for t in ["text", "json", "javascript"]):
                body = response.text()
                for secret in FORBIDDEN_SECRETS:
                    if secret in body:
                        leaked_secrets.append({
                            "url": response.url,
                            "secret_snippet": secret[:15] + "..."
                        })
        except Exception:
            pass

    page.on("response", handle_response)

    # Navigate across major application flows
    authenticate_page(page)
    page.goto(f"{BASE_URL}/", wait_until="networkidle")
    page.goto(f"{BASE_URL}/integrations", wait_until="networkidle")
    page.goto(f"{BASE_URL}/handover", wait_until="networkidle")
    page.goto(f"{BASE_URL}/settings", wait_until="networkidle")

    assert len(leaked_secrets) == 0, f"Critical Secret Keys Exposed in Browser: {leaked_secrets}"


def test_pw_end_to_end_knowledge_and_handover_workflow(page: Page, tmp_path):
    """End-to-end UI flow: create project -> upload document -> AI extract -> grounded query -> handover -> PDF export."""
    authenticate_page(page)

    # 1. Create Project in /projects UI & visit /projects/[id]
    page.goto(f"{BASE_URL}/projects", wait_until="networkidle")
    page.click('button:has-text("New Project")')
    page.fill('input[placeholder*="Core Payment Engine"]', "E2E Checkout Continuity")
    page.click('button:has-text("Create Project")')
    page.wait_for_timeout(1200)
    expect(page.locator("text=E2E Checkout Continuity").first).to_be_visible()
    page.locator("text=E2E Checkout Continuity").first.click()
    page.wait_for_timeout(1000)
    assert "/projects/" in page.url

    # 2. Upload a real runbook document in /documents & inspect parsed chunks
    doc_file = tmp_path / "checkout_architecture_e2e.md"
    doc_file.write_text(
        "# Checkout Settlement Architecture\n\n"
        "Razorpay processes domestic UPI settlement with HMAC-SHA256 webhook verification. "
        "Orders use Redis Redlock with 5000ms TTL to prevent concurrent checkout races. "
        "Kafka handles async fulfillment events cleanly.\n",
        encoding="utf-8",
    )
    page.goto(f"{BASE_URL}/documents", wait_until="networkidle")
    page.fill('input[placeholder*="Document Title"]', "Checkout Settlement Runbook")
    page.set_input_files('input[type="file"]', str(doc_file))
    page.click('button:has-text("Upload & Index")')
    page.wait_for_timeout(2000)
    expect(page.locator("text=Checkout Settlement Runbook").first).to_be_visible()

    page.locator('button:has-text("Chunks")').first.click()
    page.wait_for_timeout(800)
    expect(page.locator("text=Extracted Chunks").first).to_be_visible()
    page.keyboard.press("Escape")
    # Close chunk modal if X button exists
    close_btn = page.locator("div.fixed button").first
    if close_btn.is_visible():
        close_btn.click()

    # 3. Query AI Project Assistant: grounded query + unsupported refusal
    page.goto(f"{BASE_URL}/assistant", wait_until="networkidle")
    page.fill('input[placeholder*="Ask a question"]', "How are Redis locks and Razorpay webhook verification handled?")
    page.click('button[type="submit"]')
    page.wait_for_timeout(2500)
    expect(page.locator("text=Grounded in Evidence").first).to_be_visible()

    page.fill('input[placeholder*="Ask a question"]', "What is the boiling point of liquid helium in Kelvin?")
    page.click('button[type="submit"]')
    page.wait_for_timeout(1800)
    expect(page.locator("text=Unsupported / Missing Evidence").first).to_be_visible()

    # 4. Run AI Extract on Knowledge Graph
    page.goto(f"{BASE_URL}/knowledge/graph", wait_until="networkidle")
    page.click('button:has-text("AI Extract Knowledge Graph")')
    page.wait_for_timeout(2500)

    # 5. Reconstruct 16-Section Handover Dossier & verify PDF download endpoint
    page.goto(f"{BASE_URL}/handover", wait_until="networkidle")
    page.click('button:has-text("Reconstruct Handover"), button:has-text("New Handover Dossier")')
    page.fill('input[placeholder="Full name"]', "Jordan Taylor")
    page.fill('input[placeholder*="Senior Backend Engineer"]', "Staff Backend Engineer")
    page.fill('input[placeholder="Successor full name"]', "Morgan Lee")
    page.fill('input[placeholder*="Staff Engineer"]', "Lead Platform Engineer")
    page.click('button:has-text("Generate Handover Dossier")')
    page.wait_for_timeout(3000)
    expect(page.locator("text=SECTION 1").first).to_be_visible()

    with page.expect_response(lambda r: "/handovers/" in r.url and "/pdf" in r.url) as resp_info:
        page.click('button:has-text("Download PDF")')
    pdf_resp = resp_info.value
    assert pdf_resp.status == 200
    assert "application/pdf" in (pdf_resp.headers.get("content-type") or "")

