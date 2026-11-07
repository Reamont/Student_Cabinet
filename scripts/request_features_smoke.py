"""Browser regression checks for request drafts, repeat, guide and student help.

Requires a running local demo and ignored var/dev.env credentials. Creates only
fictional requests; screenshots and other artifacts stay under ignored var/.
"""
import os
import re
import shlex
import uuid
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parent.parent
BASE = os.environ.get('SMOKE_BASE_URL', 'http://127.0.0.1:8000').rstrip('/')
credentials = {}
for line in (ROOT / 'var/dev.env').read_text().splitlines():
    key, value = line.split('=', 1)
    credentials[key] = shlex.split(value)[0]


def login(page, username, variable):
    page.goto(BASE + '/login/')
    page.locator('#id_username').fill(username)
    page.locator('#id_password').fill(credentials[variable])
    page.get_by_role('button', name='Войти в кабинет').click()
    page.wait_for_load_state('networkidle')
    assert '/login/' not in page.url


def fits(page):
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'), page.url


with sync_playwright() as p:
    browser = p.chromium.launch(executable_path='/usr/bin/chromium', args=['--no-sandbox'])
    errors = []
    for width in [1440, 360]:
        context = browser.new_context(viewport={'width': width, 'height': 900 if width == 1440 else 800},
                                      is_mobile=width == 360, has_touch=width == 360,
                                      locale='ru-RU', timezone_id='Europe/Moscow')
        page = context.new_page()
        page.on('pageerror', lambda e: errors.append(str(e)))
        login(page, 'alisa', 'DEMO_STUDENT_PASSWORD')
        page.goto(BASE + '/requests/')
        page.get_by_role('link', name='Помочь выбрать обращение').click()
        page.get_by_role('link', name=re.compile('Получить справку')).click()
        page.get_by_role('link', name=re.compile('Предъявить в организации')).click()
        page.get_by_role('link', name='Заполнить обращение').click()
        expect(page.locator('#id_kind')).to_have_value('destination')
        destination = 'Демо-мастерская ' + uuid.uuid4().hex[:8]
        page.locator('#id_destination').fill(destination)
        page.locator('#id_text').fill('Вымышленное обращение для браузерной проверки.')
        expect(page.locator('[data-draft-status]')).to_contain_text('Черновик сохранён')
        first_token = page.locator('#id_token').input_value()
        fits(page)

        page.goto(BASE + '/profile/')
        page.locator('main').get_by_role('button', name='Выйти', exact=True).click()
        login(page, 'alisa', 'DEMO_STUDENT_PASSWORD')
        page.goto(BASE + '/requests/')
        page.locator('.draft-row').filter(has_text=destination).get_by_role('link', name='Продолжить').click()
        draft_url = page.url
        expect(page.locator('#id_destination')).to_have_value(destination)
        expect(page.locator('#id_text')).to_have_value('Вымышленное обращение для браузерной проверки.')
        fits(page)

        # An autosave failure must be visible and keep the text editable.
        def fail_save(route):
            route.fulfill(status=503, content_type='application/json',
                          body='{"error":"Сохранение временно недоступно."}')
        page.route('**/requests/drafts/save/', fail_save)
        text = 'Вымышленный текст сохранён после проверки ошибки соединения.'
        page.locator('#id_text').fill(text)
        expect(page.locator('[data-draft-status]')).to_contain_text('Сохранение временно недоступно.')
        expect(page.locator('#id_text')).to_have_value(text)
        page.unroute('**/requests/drafts/save/', fail_save)
        page.get_by_role('button', name='Сохранить черновик и выйти').click()
        page.locator('.draft-row').filter(has_text=destination).get_by_role('link', name='Продолжить').click()
        expect(page.locator('#id_text')).to_have_value(text)
        page.get_by_role('button', name='Проверить данные').click()
        fits(page)
        page.get_by_role('button', name='Отправить заявку', exact=False).click()
        page.wait_for_url(re.compile(r'/requests/\d+/$'))
        original_url = page.url
        expect(page.locator('.badge-large')).to_have_text('Отправлена')
        page.get_by_role('link', name='Повторить заявку', exact=True).click()
        expect(page.locator('#id_destination')).to_have_value(destination)
        expect(page.locator('#id_text')).to_have_value(text)
        assert page.locator('#id_token').input_value() != first_token
        page.locator('#id_destination').fill('Повтор: ' + destination)
        page.get_by_role('button', name='Проверить данные').click()
        page.get_by_role('button', name='Отправить заявку', exact=False).click()
        page.wait_for_url(re.compile(r'/requests/\d+/$'))
        assert page.url != original_url
        expect(page.locator('.badge-large')).to_have_text('Отправлена')
        page.goto(BASE + '/requests/')
        expect(page.locator('.draft-row').filter(has_text=destination)).to_have_count(0)
        print(f'PASS {width}px: guide, autosave, relogin/resume, failure/manual save, submit, repeat')

        page.get_by_role('link', name='Справочник студента', exact=True).first.click()
        page.locator('#help-query').fill('задолженность')
        page.get_by_role('button', name='Найти', exact=True).click()
        fits(page)
        page.locator('summary').filter(has_text='Появилась академическая задолженность').click()
        page.get_by_role('link', name='Открыть успеваемость', exact=True).click()
        expect(page.get_by_role('heading', name='Успеваемость', exact=True)).to_be_visible()
        page.goto(BASE + '/help/#clarification')
        expect(page.locator('#clarification')).to_have_attribute('open', '')
        fits(page)
        page.goto(BASE + '/requests/guide/?purpose=question')
        page.get_by_role('link', name='Заполнить обращение').click()
        expect(page.locator('#id_kind')).to_have_value('application')
        print(f'PASS {width}px: help search, disclosure, real action link and application recommendation')

        other_context = browser.new_context(viewport={'width': width, 'height': 800})
        other = other_context.new_page()
        login(other, 'maks', 'DEMO_SECOND_PASSWORD')
        assert other.goto(draft_url).status == 404
        assert other.goto(original_url.rstrip('/') + '/repeat/').status == 404
        other_context.close()
        context.close()

    no_js = browser.new_context(java_script_enabled=False, viewport={'width': 360, 'height': 800})
    page = no_js.new_page()
    login(page, 'alisa', 'DEMO_STUDENT_PASSWORD')
    page.goto(BASE + '/requests/new/?kind=application')
    page.locator('#id_text').fill('Я')
    page.get_by_role('button', name='Сохранить черновик и выйти').click()
    page.locator('.draft-row').filter(has_text='Заявление в деканат').first.get_by_role('link', name='Продолжить').click()
    expect(page.locator('#id_text')).to_have_value('Я')
    page.goto(BASE + '/help/')
    page.locator('summary').first.click()
    expect(page.get_by_role('link', name='Подобрать обращение')).to_be_visible()
    print('PASS without JavaScript: partial draft manual save/resume and help disclosure')
    assert not errors, errors
    browser.close()
