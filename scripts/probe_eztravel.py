from __future__ import annotations

from playwright.sync_api import sync_playwright


def main() -> None:
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(locale="zh-TW", timezone_id="Asia/Taipei", viewport={"width": 1280, "height": 720})
        page.goto("https://flight.eztravel.com.tw/", wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(3000)
        page.locator("#search-flight-arrival-0").click()
        page.locator("#search-flight-arrival-0").fill("東京")
        page.get_by_text("東京", exact=True).first.click()
        page.locator("#flight-search-date-range-0-select-start").click()
        page.wait_for_timeout(500)
        page.get_by_label("Next Month").click()
        page.wait_for_timeout(300)
        page.locator('[aria-label="Choose Tuesday, September 1st, 2026"]:not(.dpicker__day--outside-month)').click()
        page.locator('[aria-label="Choose Sunday, September 6th, 2026"]:not(.dpicker__day--outside-month)').first.click()
        page.get_by_role("button", name="搜尋").first.click()
        page.wait_for_timeout(25000)
        print("URL", page.url)
        print("TITLE", page.title())
        print(page.locator("body").inner_text(timeout=10000)[:5000])
        page.screenshot(path="eztravel-search-result.png", full_page=True)
        browser.close()


if __name__ == "__main__":
    main()
