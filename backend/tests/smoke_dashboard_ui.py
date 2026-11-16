"""Optional browser smoke test. Requires Python Playwright and an installed Chrome."""
import json
from pathlib import Path
from playwright.sync_api import sync_playwright, expect


def run():
    output = Path('artifacts')
    output.mkdir(exist_ok=True)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel='chrome', headless=True)
        page = browser.new_page(viewport={'width': 1440, 'height': 1000})
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))

        def login(email, password):
            page.get_by_label('Email address').fill(email)
            page.get_by_label('Password', exact=True).fill(password)
            page.get_by_role('button', name='Sign in', exact=True).click()
            expect(page.get_by_role('heading', name='Revenue Overview')).to_be_visible(timeout=30000)

        page.goto('http://localhost:3000/login')
        login('sunset@propertyflow.com', 'client_a_2024')
        expect(page.get_by_text('USD 2,250.00', exact=True)).to_be_visible(timeout=30000)
        options = page.locator('select').nth(0).locator('option').all_text_contents()
        assert options == ['Beach House Alpha', 'City Apartment Downtown', 'Country Villa Estate'], options
        page.screenshot(path=str(output / 'sunset-march.png'), full_page=True)
        page.reload()
        expect(page.get_by_text('USD 2,250.00', exact=True)).to_be_visible(timeout=30000)
        page.locator('select').nth(2).select_option('2')
        expect(page.get_by_text('No reservations in this period.')).to_be_visible(timeout=15000)
        page.locator('select').nth(2).select_option('3')
        expect(page.get_by_text('USD 2,250.00', exact=True)).to_be_visible(timeout=15000)
        page.locator('select').nth(1).select_option('annual')
        expect(page.get_by_text('USD 2,250.00', exact=True)).to_be_visible(timeout=15000)
        page.locator('select').nth(0).select_option('prop-002')
        expect(page.get_by_text('USD 4,975.50', exact=True)).to_be_visible(timeout=15000)
        page.get_by_role('button', name='User menu').click()
        page.get_by_role('button', name='Sign out', exact=True).click()
        expect(page.get_by_label('Email address')).to_be_visible(timeout=30000)
        login('ocean@propertyflow.com', 'client_b_2024')
        expect(page.get_by_text('No reservations in this period.')).to_be_visible(timeout=30000)
        options = page.locator('select').nth(0).locator('option').all_text_contents()
        assert options == ['Mountain Lodge Beta', 'Lakeside Cottage', 'Urban Loft Modern'], options
        page.locator('select').nth(0).select_option('prop-004')
        expect(page.get_by_text('USD 1,776.50', exact=True)).to_be_visible(timeout=15000)
        page.screenshot(path=str(output / 'ocean-march.png'), full_page=True)
        page.locator('select').nth(0).select_option('prop-005')
        expect(page.get_by_text('USD 3,256.00', exact=True)).to_be_visible(timeout=15000)
        page.wait_for_timeout(5500)  # Exercise the scheduled storage health cleanup.
        assert page.evaluate("localStorage.getItem('base360-auth-token') !== null")
        page.reload()
        expect(page.get_by_text('No reservations in this period.')).to_be_visible(timeout=30000)
        page.reload()
        expect(page.get_by_text('No reservations in this period.')).to_be_visible(timeout=30000)
        page.get_by_role('button', name='User menu').click()
        page.get_by_role('button', name='Sign out', exact=True).click()
        expect(page.get_by_label('Email address')).to_be_visible(timeout=30000)
        login('sunset@propertyflow.com', 'client_a_2024')
        expect(page.get_by_text('USD 2,250.00', exact=True)).to_be_visible(timeout=30000)
        page.reload()
        expect(page.get_by_text('USD 2,250.00', exact=True)).to_be_visible(timeout=30000)
        assert not errors, errors
        browser.close()
        report = {'status': 'passed', 'checks': ['login both assignment accounts', 'tenant property lists',
                  'March totals', 'February boundary', 'annual summary', 'property selection',
                  'logout and switch account', 'refresh both accounts', 'no browser runtime errors']}
        (output / 'browser-smoke-results.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
        print(json.dumps(report, indent=2))


if __name__ == '__main__':
    run()
