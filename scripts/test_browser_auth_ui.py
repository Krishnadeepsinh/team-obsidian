from playwright.sync_api import sync_playwright

def test_ui():
    print("=" * 60)
    print("TEAM OBSIDIAN - PLAYWRIGHT FRONTEND UI VERIFICATION")
    print("=" * 60)
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context()
        page = context.new_page()

        # Step 1: Verify Forgot Password Page UI
        print("\n--- TEST A: Forgot Password UI Wizard ---")
        page.goto("http://localhost:3000/forgot-password", wait_until="networkidle")
        assert "Reset your password" in page.content(), "Expected 'Reset your password' title on forgot password page"
        print("PASS: Forgot password page loaded successfully.")

        # Check step 1 email input exists
        email_input = page.locator('input[type="email"]')
        assert email_input.is_visible(), "Email input should be visible in Step 1"
        email_input.fill("yagnadeepsinh.4741@gmail.com")
        
        # Check 'Send Verification Code' button
        send_btn = page.locator('button:has-text("Send Verification Code")')
        assert send_btn.is_visible(), "Send button should be visible"
        print("PASS: Step 1 Email form verified.")

        # Step 2: Login Flow
        print("\n--- TEST B: Login & Dashboard Navigation ---")
        page.goto("http://localhost:3000/login", wait_until="networkidle")
        page.fill('input[type="email"]', "lead.architect@team-obsidian.io")
        page.fill('input[type="password"]', "ObsidianSecurePassword2026!")
        page.click('button[type="submit"]')

        page.wait_for_url(lambda u: "/login" not in u, timeout=10000)
        print(f"PASS: Logged in and navigated to: {page.url}")

        # Step 3: Verify Sign Out from Sidebar
        print("\n--- TEST C: Sign Out Execution ---")
        user_menu_btn = page.locator('[data-testid="user-menu-trigger"]')
        if user_menu_btn.is_visible():
            user_menu_btn.click()
            page.wait_for_timeout(500)
            sign_out_btn = page.locator('button:has-text("Sign Out")')
            assert sign_out_btn.is_visible(), "Sign Out button should be visible in dropdown"
            sign_out_btn.click()
        else:
            # Fallback to header menu
            header_avatar = page.locator('button[aria-label="User profile menu"]')
            header_avatar.click()
            page.wait_for_timeout(500)
            sign_out_btn = page.locator('button:has-text("Sign Out")')
            sign_out_btn.click()

        # Wait for redirect to /login
        page.wait_for_url("**/login", timeout=10000)
        print(f"PASS: Redirected to login page after Sign Out: {page.url}")

        # Step 4: Verify Back-Button Navigation Prevention
        print("\n--- TEST D: Back Button Security Audit ---")
        page.go_back()
        page.wait_for_timeout(1500)
        # Should stay on /login or be redirected back to /login
        current_url = page.url
        print(f"URL after pressing browser Back button: {current_url}")
        assert "/login" in current_url, f"Expected to remain on /login, but was {current_url}"
        print("PASS: Browser back-navigation prevented; session remains cleared.")

        browser.close()
        print("\n" + "=" * 60)
        print("ALL FRONTEND UI & LOGOUT TESTS PASSED PERFECTLY!")
        print("=" * 60)

if __name__ == "__main__":
    test_ui()
