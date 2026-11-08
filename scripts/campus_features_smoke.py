"""Browser checks for semester, Plan B and the shared idea board.

Use an isolated seeded demo database. SMOKE_PLAN_DATE must name a future date
with a cancelled lesson and unfinished tasks. Credentials stay in var/dev.env.
"""
import os
import re
import shlex
import uuid
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parent.parent
BASE = os.environ.get('SMOKE_BASE_URL', 'http://127.0.0.1:8000').rstrip('/')
DAY = os.environ.get('SMOKE_PLAN_DATE', '')
if not re.fullmatch(r'\d{4}-\d{2}-\d{2}', DAY):
    raise SystemExit('Set SMOKE_PLAN_DATE to a future date with a cancelled lesson in the test database.')
credentials = {}
for line in (ROOT / 'var/dev.env').read_text().splitlines():
    key, value = line.split('=', 1)
    credentials[key] = shlex.split(value)[0]
SHOTS = ROOT / 'var/browser/campus'
SHOTS.mkdir(parents=True, exist_ok=True)


def login(page, user, key, staff=False):
    page.goto(BASE + ('/admin/login/' if staff else '/login/'))
    page.locator('#id_username').fill(user)
    page.locator('#id_password').fill(credentials[key])
    page.locator('button[type=submit],input[type=submit]').first.click()
    page.wait_for_load_state('networkidle')
    assert '/login/' not in page.url


def fits(page):
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'), page.url


with sync_playwright() as p:
    browser = p.chromium.launch(executable_path='/usr/bin/chromium', args=['--no-sandbox'])
    errors = []
    for width in (1440, 360):
        context = browser.new_context(viewport={'width':width, 'height':900 if width == 1440 else 800},
                                      is_mobile=width == 360, has_touch=width == 360,
                                      locale='ru-RU', timezone_id='Europe/Moscow')
        page = context.new_page()
        page.on('pageerror', lambda e: errors.append(str(e)))
        login(page, 'alisa', 'DEMO_STUDENT_PASSWORD')
        page.locator('.campus-tools').get_by_role('link', name=re.compile('Мой семестр')).click()
        expect(page.get_by_role('heading', name='Мой семестр', exact=True)).to_be_visible()
        page.locator('#semester-month').fill(DAY[:7])
        page.get_by_role('button', name='Показать', exact=True).click()
        fits(page)
        page.locator(f'.month-cell.has-events[href="#day-{DAY}"]').click()
        expect(page.locator('#day-' + DAY)).to_be_visible()
        page.screenshot(path=str(SHOTS / f'semester-{width}.png'), full_page=True)

        page.goto(BASE + '/plan-b/?date=' + DAY)
        fits(page)
        window = page.locator('.plan-window').first
        if window.locator('.selected-study').count():
            window.locator('.selected-study').get_by_role('button', name='Убрать из плана').click()
        choice = window.locator('select')
        choice.select_option(index=1)
        selected_task = choice.locator('option:checked').inner_text().split(' · ')[0]
        window.get_by_role('button', name='Добавить в личный план').click()
        expect(page.locator('.selected-study')).to_contain_text(selected_task)
        remove_url = page.locator('.selected-study form').get_attribute('action')
        page.goto(BASE + '/profile/')
        page.locator('main').get_by_role('button', name='Выйти', exact=True).click()
        login(page, 'alisa', 'DEMO_STUDENT_PASSWORD')
        page.goto(BASE + '/semester/?month=' + DAY[:7] + '&kind=plan')
        expect(page.locator('.journey-event')).to_contain_text(selected_task)
        page.locator('.journey-event').first.click()
        expect(page.locator('.selected-study')).to_contain_text(selected_task)
        fits(page)
        page.screenshot(path=str(SHOTS / f'plan-b-{width}.png'), full_page=True)
        print(f'PASS {width}px: semester navigation, Plan B selection, relogin and private map')

        page.goto(BASE + '/ideas/')
        page.get_by_role('link', name='Предложить улучшение', exact=True).click()
        title = 'Демо-идея для учебного кампуса ' + uuid.uuid4().hex[:8]
        page.locator('#id_title').fill(title)
        page.locator('#id_description').fill('Предлагаю добавить понятную схему обращения по учебным вопросам. Все примеры вымышлены.')
        page.locator('#id_publish').check()
        fits(page)
        page.get_by_role('button', name='Опубликовать предложение').click()
        page.wait_for_url(re.compile(r'/ideas/\d+/$'))
        idea_url = page.url
        pk = re.search(r'/ideas/(\d+)/', idea_url).group(1)
        expect(page.get_by_text('Твоё предложение', exact=False).first).to_be_visible()

        other_context = browser.new_context(viewport={'width':width, 'height':800})
        other = other_context.new_page()
        login(other, 'maks', 'DEMO_SECOND_PASSWORD')
        other.goto(idea_url)
        assert 'Алиса Андреевна Лебедева' not in other.locator('main').inner_text()
        other.get_by_role('button', name='Поддержать идею', exact=True).click()
        expect(other.get_by_text('Поддержали: 1', exact=True)).to_be_visible()
        csrf = other.locator('input[name=csrfmiddlewaretoken]').first.input_value()
        assert other.request.post(BASE + remove_url, form={'csrfmiddlewaretoken':csrf}).status == 404
        other.goto(BASE + '/semester/?month=' + DAY[:7] + '&kind=plan')
        expect(other.get_by_text('Выбрано в «Плане Б»', exact=False)).to_have_count(0)

        staff_context = browser.new_context(locale='ru-RU', timezone_id='Europe/Moscow')
        staff = staff_context.new_page()
        login(staff, 'curator', 'DEMO_STAFF_PASSWORD', staff=True)
        staff.goto(BASE + f'/admin/portal/idea/{pk}/change/')
        for status, response in [('planned','Демонстрационная идея включена в план.'),
                                 ('done','Реализация демонстрационной идеи завершена.')]:
            staff.locator('#id_status').select_option(status)
            staff.locator('#id_response').fill(response)
            staff.locator('input[name=_continue]').click()
            expect(staff.locator('#id_status')).to_have_value(status)
        page.goto(idea_url)
        expect(page.locator('.badge-large')).to_have_text('Реализовано')
        expect(page.locator('.timeline li')).to_have_count(3)
        expect(page.locator('.idea-response')).to_contain_text('Реализация демонстрационной идеи завершена.')
        fits(page)
        page.screenshot(path=str(SHOTS / f'idea-{width}.png'), full_page=True)
        other.goto(BASE + '/notifications/?kind=idea')
        other.get_by_role('link', name='Открыть →').first.click()
        other.get_by_role('link', name='Открыть предложение', exact=True).click()
        expect(other.get_by_role('heading', name=title, exact=True)).to_be_visible()
        print(f'PASS {width}px: public proposal, private authorship, support, staff decisions and notifications')

        page.goto(BASE + '/plan-b/?date=' + DAY)
        page.locator('.selected-study').get_by_role('button', name='Убрать из плана').click()
        expect(page.locator('.selected-study')).to_have_count(0)
        page.goto(BASE + '/ideas/?status=done&sort=popular')
        expect(page.get_by_role('link', name=title, exact=True)).to_be_visible()
        fits(page)
        staff_context.close()
        other_context.close()
        context.close()
    assert not errors, errors
    browser.close()
    print('All campus feature browser checks passed.')
