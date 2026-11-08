"""Browser regression checks for navigation, view memory, recovery and mobile layout.

Run against an isolated seeded demo; credentials are read from ignored var/dev.env.
"""
import os
import re
import shlex
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parent.parent
BASE = os.environ.get('SMOKE_BASE_URL', 'http://127.0.0.1:8000').rstrip('/')
DAY = os.environ.get('SMOKE_SEMESTER_DATE', '2026-11-11')
credentials = {}
for line in (ROOT / 'var/dev.env').read_text().splitlines():
    key, value = line.split('=', 1)
    credentials[key] = shlex.split(value)[0]
SHOTS = ROOT / 'var/browser/experience'
SHOTS.mkdir(parents=True, exist_ok=True)


def login(page, user='alisa', key='DEMO_STUDENT_PASSWORD'):
    page.goto(BASE + '/login/')
    page.locator('#id_username').fill(user)
    page.locator('#id_password').fill(credentials[key])
    page.get_by_role('button', name='Войти в кабинет').click()
    page.wait_for_load_state('networkidle')
    assert '/login/' not in page.url


def fits(page):
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'), page.url


def remembered(page):
    expect(page.locator('[data-memory-status]')).to_have_text('Вид сохранён')


with sync_playwright() as p:
    browser = p.chromium.launch(executable_path='/usr/bin/chromium', args=['--no-sandbox'])
    errors = []
    for width, height in [(1440, 900), (1366, 650), (360, 800)]:
        context = browser.new_context(viewport={'width': width, 'height': height},
            is_mobile=width == 360, has_touch=width == 360, locale='ru-RU', timezone_id='Europe/Moscow')
        page = context.new_page()
        page.on('pageerror', lambda error: errors.append(str(error)))
        login(page)
        fits(page)
        expect(page.locator('.next-action')).to_be_visible()
        expect(page.locator('.home-lessons')).not_to_have_attribute('open', '')
        nav = page.locator('.mobile-nav' if width == 360 else '.side-nav')
        assert nav.locator('a').all_text_contents() == ['Главная', 'Расписание', 'Учёба', 'Заявки', 'Ещё']
        if width != 360:
            box = page.locator('.sidebar-bottom').bounding_box()
            assert box['y'] >= 0 and box['y'] + box['height'] <= height
        page.screenshot(path=str(SHOTS / f'home-{width}-{height}.png'), full_page=True)
        nav.get_by_role('link', name='Учёба', exact=True).click()
        page.locator('.study-cards').get_by_role('link', name=re.compile('Учебные задачи')).click()
        expect(page.get_by_role('heading', name='Учебные задачи', exact=True)).to_be_visible()
        fits(page)
        page.get_by_role('link', name='Мой семестр', exact=True).first.click()
        remembered(page)
        fits(page)
        nav.get_by_role('link', name='Ещё', exact=True).click()
        page.locator('.destination-grid').get_by_role('link', name=re.compile('Профиль')).click()
        page.get_by_role('link', name='О проекте и данных', exact=False).first.click()
        expect(page.get_by_role('heading', name='О проекте и данных', exact=True)).to_be_visible()
        expect(page.locator('main')).not_to_contain_text('Студенческий билет')
        fits(page)
        page.get_by_role('link', name='Открыть профиль', exact=True).click()
        expect(page.get_by_role('heading', name='Профиль', exact=True)).to_be_visible()
        print(f'PASS {width}x{height}: five destinations, study, tasks, semester, more, profile, separate about')

        page.goto(BASE + '/schedule/?mode=week&date=' + DAY)
        remembered(page)
        page.goto(BASE + '/more/')
        nav.get_by_role('link', name='Расписание', exact=True).click()
        expect(page.locator('.segmented a.selected')).to_have_text('Неделя')
        remembered(page)
        page.goto(BASE + '/schedule/?mode=today&date=' + DAY)
        remembered(page)
        details = page.locator('.lesson-expand').first
        expect(details).not_to_have_attribute('open', '')
        details.locator('summary').click()
        expect(details.locator('p').first).to_be_visible()
        # Failed preference write keeps the chosen view and offers a working retry.
        def fail_save(route):
            route.fulfill(status=503, content_type='application/json', body='{}')
        page.route('**/preferences/', fail_save)
        page.goto(BASE + '/requests/?tab=history')
        expect(page.locator('[data-memory-status]')).to_contain_text('Не удалось запомнить вид')
        expect(page.locator('.request-tabs a[aria-current=page]')).to_contain_text('История')
        page.unroute('**/preferences/', fail_save)
        page.get_by_role('button', name='Повторить сохранение вида').click()
        remembered(page)
        page.goto(BASE + '/requests/')
        expect(page.locator('.request-tabs a[aria-current=page]')).to_contain_text('История')
        page.get_by_role('link', name=re.compile('Черновики')).click()
        remembered(page)
        expect(page.locator('.request-content')).to_have_attribute('id', 'drafts')
        page.get_by_role('link', name=re.compile('Активные')).click()
        remembered(page)
        fits(page)

        # Store only a numeric list position and restore after opening a row.
        rows = page.locator('.request-entry')
        for index in range(max(0, 8 - rows.count())):
            page.goto(BASE + '/requests/new/?kind=application')
            page.locator('#id_text').fill(f'Вымышленное обращение для проверки возврата к списку, пример {index + 1}.')
            page.get_by_role('button', name='Проверить данные').click()
            page.get_by_role('button', name='Отправить заявку', exact=False).click()
            page.wait_for_url(re.compile(r'/requests/\d+/$'))
        page.goto(BASE + '/requests/?tab=active')
        remembered(page)
        target = page.evaluate('Math.min(650, document.documentElement.scrollHeight - innerHeight)')
        page.evaluate('(target) => window.scrollTo(0, target)', target)
        page.wait_for_function('(target) => Math.abs(window.scrollY - target) < 8', arg=target)
        offset = page.evaluate('window.scrollY')
        # Navigate without scrolling the row into view so the snapshot is deterministic.
        page.goto(BASE + rows.first.locator('a.request-row').get_attribute('href'))
        page.get_by_role('link', name='← Мои заявки', exact=True).click()
        page.wait_for_function('(expected) => Math.abs(window.scrollY - expected) < 8', arg=offset)
        remembered(page)
        print(f'PASS {width}x{height}: request tabs, failed preference retry, scroll restoration')

        page.goto(BASE + '/notifications/?kind=request&unread=1')
        remembered(page)
        page.goto(BASE + '/notifications/')
        expect(page.locator('#notification-kind')).to_have_value('request')
        expect(page.locator('input[type=checkbox][name=unread]')).to_be_checked()
        page.locator('#notification-kind').select_option('')
        page.locator('input[type=checkbox][name=unread]').uncheck()
        page.get_by_role('button', name='Показать', exact=True).click()
        remembered(page)
        expect(page.locator('#notification-kind')).to_have_value('')
        expect(page.locator('input[type=checkbox][name=unread]')).not_to_be_checked()
        page.goto(BASE + '/profile/')
        page.locator('main').get_by_role('button', name='Выйти', exact=True).click()
        login(page, 'maks', 'DEMO_SECOND_PASSWORD')
        assert page.evaluate('Object.keys(sessionStorage).filter(k => k.startsWith("student-position:")).length') == 0
        expect(page.locator('main')).not_to_contain_text('Алиса Андреевна Лебедева')
        print(f'PASS {width}x{height}: remembered notification filters, explicit reset, logout/account isolation')
        context.close()

    context = browser.new_context(java_script_enabled=False, reduced_motion='reduce', viewport={'width':360, 'height':800})
    page = context.new_page()
    login(page)
    page.goto(BASE + '/schedule/?mode=week')
    page.get_by_role('button', name='Запомнить этот вид', exact=True).click()
    page.goto(BASE + '/schedule/')
    expect(page.locator('.segmented a.selected')).to_have_text('Неделя')
    page.goto(BASE + '/requests/?tab=history')
    page.get_by_role('button', name='Запомнить этот вид', exact=True).click()
    page.goto(BASE + '/requests/')
    expect(page.locator('.request-tabs a[aria-current=page]')).to_contain_text('История')
    fits(page)
    print('PASS without JavaScript: native POST view memory and request tabs')
    assert not errors, errors
    browser.close()
