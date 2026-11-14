"""Browser checks for themes and password visibility. Run after scripts/dev.sh.

Uses fictional local accounts; never screenshots or logs a visible password.
Requires requirements-dev.txt and Chromium (as with the other smoke scripts).
"""
import os
import shlex
from pathlib import Path

from playwright.sync_api import expect, sync_playwright


ROOT = Path(__file__).resolve().parent.parent
BASE = os.environ.get('SMOKE_BASE_URL', 'http://127.0.0.1:8000').rstrip('/')
SHOTS = ROOT / 'var' / 'theme-screenshots'
SHOTS.mkdir(parents=True, exist_ok=True)
values = dict(line.split('=', 1) for line in (ROOT / 'var/dev.env').read_text().splitlines() if line)
PASSWORD = shlex.split(values['DEMO_STUDENT_PASSWORD'])[0]


def login(page):
    page.locator('#id_username').fill('alisa@campus.example.test')
    page.locator('#id_password').fill(PASSWORD)
    page.get_by_role('button', name='Войти в кабинет').click()
    page.wait_for_url(BASE + '/')


def no_overflow(page):
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'), page.url


with sync_playwright() as p:
    browser = p.chromium.launch(executable_path=os.environ.get('CHROMIUM_PATH', '/usr/bin/chromium'),
                                args=['--no-sandbox'])
    errors = []
    def new_context(**options):
        context = browser.new_context(**options)
        context.on('page', lambda page: page.on('pageerror', lambda error: errors.append(str(error))))
        return context
    for width in (1440, 360):
        context = new_context(viewport={'width': width, 'height': 900}, color_scheme='light')
        page = context.new_page()
        page.goto(BASE + '/login/')
        expect(page.locator('html')).to_have_attribute('data-theme', 'light')
        page.emulate_media(color_scheme='dark')
        expect(page.locator('html')).to_have_attribute('data-theme', 'dark')
        page.get_by_role('button', name='Включить светлую тему').click()
        page.reload()
        expect(page.locator('html')).to_have_attribute('data-theme', 'light')
        page.screenshot(path=str(SHOTS / f'login-light-{width}.png'), full_page=True)
        page.get_by_role('button', name='Включить тёмную тему').click()
        page.emulate_media(color_scheme='light')
        expect(page.locator('html')).to_have_attribute('data-theme', 'dark')

        password = page.locator('#id_password')
        password.fill('fictional-password-visibility-check')
        eye = page.get_by_role('button', name='Показать пароль', exact=True)
        expect(password).to_have_attribute('type', 'password')
        eye.click()
        expect(password).to_have_attribute('type', 'text')
        expect(password).to_have_value('fictional-password-visibility-check')
        eye = page.get_by_role('button', name='Скрыть пароль', exact=True)
        eye.focus()
        eye.press('Space')
        expect(password).to_have_attribute('type', 'password')
        expect(page.locator('form[data-submit-state]')).not_to_have_attribute('aria-busy', 'true')
        password.fill('')
        no_overflow(page)
        page.screenshot(path=str(SHOTS / f'login-dark-{width}.png'), full_page=True)

        # Invalid credentials still show the normal error and reset visibility.
        page.locator('#id_username').fill('alisa@campus.example.test')
        password.fill('incorrect-fictional-password')
        page.get_by_role('button', name='Показать пароль', exact=True).click()
        page.get_by_role('button', name='Войти в кабинет').click()
        expect(page.locator('.form-error')).to_be_visible()
        expect(password).to_have_attribute('type', 'password')
        expect(password).to_have_value('')
        expect(page.locator('html')).to_have_attribute('data-theme', 'dark')
        login(page)

        for theme in ('dark', 'light'):
            if theme == 'light':
                page.get_by_role('button', name='Включить светлую тему').click()
            for name, route in [('dashboard', '/'), ('schedule', '/schedule/?mode=week'),
                                ('grades', '/grades/'), ('tasks', '/study/tasks/'),
                                ('task-form', '/study/tasks/new/'), ('requests', '/requests/'),
                                ('request-form', '/requests/new/'), ('notifications', '/notifications/'),
                                ('semester', '/semester/'), ('ideas', '/ideas/'),
                                ('idea-form', '/ideas/new/'), ('help', '/help/'),
                                ('profile', '/profile/'), ('about', '/about/')]:
                response = page.goto(BASE + route)
                assert response.status == 200, (route, response.status)
                expect(page.locator('html')).to_have_attribute('data-theme', theme)
                expect(page.locator('html')).to_have_css('color-scheme', theme)
                no_overflow(page)
                if name in ('dashboard', 'request-form', 'semester'):
                    page.screenshot(path=str(SHOTS / f'{name}-{theme}-{width}.png'), full_page=True)

        # Saved choices propagate to other tabs, including the public login page.
        other = context.new_page()
        other.goto(BASE + '/about/')
        other.get_by_role('button', name='Включить тёмную тему').click()
        expect(page.locator('html')).to_have_attribute('data-theme', 'dark')
        page.goto(BASE + '/profile/')
        page.locator('main').get_by_role('button', name='Выйти', exact=True).click()
        expect(page.locator('#id_password')).to_have_attribute('type', 'password')
        expect(page.locator('html')).to_have_attribute('data-theme', 'dark')
        context.close()
        print(f'PASS: {width}px — both themes, password toggle, login, persistence, 14 routes, no overflow')

    # A fresh visitor follows the OS; a manual choice survives a browser restart.
    context = new_context(color_scheme='dark')
    page = context.new_page()
    page.goto(BASE + '/login/')
    expect(page.locator('html')).to_have_attribute('data-theme', 'dark')
    page.get_by_role('button', name='Включить светлую тему').click()
    state = context.storage_state()
    context.close()
    context = new_context(storage_state=state, color_scheme='dark')
    page = context.new_page()
    page.goto(BASE + '/login/')
    expect(page.locator('html')).to_have_attribute('data-theme', 'light')
    context.close()

    context = new_context(color_scheme='light')
    context.add_init_script("""Object.defineProperty(window, 'localStorage', {
        get() { throw new DOMException('Storage disabled', 'SecurityError'); }
    });""")
    page = context.new_page()
    page.goto(BASE + '/login/')
    page.get_by_role('button', name='Включить тёмную тему').click()
    expect(page.locator('html')).to_have_attribute('data-theme', 'dark')
    page.get_by_role('button', name='Показать пароль', exact=True).click()
    expect(page.locator('#id_password')).to_have_attribute('type', 'text')
    login(page)
    context.close()

    context = new_context(java_script_enabled=False)
    page = context.new_page()
    page.goto(BASE + '/login/')
    expect(page.locator('[data-theme-toggle]')).to_be_hidden()
    expect(page.locator('[data-password-toggle]')).to_be_hidden()
    expect(page.locator('#id_password')).to_have_attribute('type', 'password')
    login(page)
    context.close()
    browser.close()
    assert not errors, errors
    print('PASS: system preference, restored storage, blocked storage, no-JavaScript login; no JS errors')
