"""Real-browser demonstration smoke. Requires local dev.sh + Python Playwright.

Reads ignored generated credentials without logging them. Creates one fictional
request and changes ONLY that request. Screenshots contain no passwords.
"""
import json
import os
import re
import shlex
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from playwright.sync_api import sync_playwright, expect


ROOT = Path(__file__).resolve().parent.parent
BASE = os.environ.get('SMOKE_BASE_URL', 'http://127.0.0.1:8000').rstrip('/')
SHOTS = ROOT / 'docs' / 'screenshots'
SHOTS.mkdir(parents=True, exist_ok=True)
values = {}
for line in (ROOT / 'var' / 'dev.env').read_text().splitlines():
    if line.strip() and not line.lstrip().startswith('#'):
        key, value = line.split('=', 1)
        values[key] = shlex.split(value)[0]

checks = []
errors = []
resources = []
mobile_routes = []


def record(text):
    checks.append(text)
    print('PASS:', text)


def watch(page):
    page.on('pageerror', lambda error: errors.append(str(error)))
    page.on('console', lambda message: errors.append(message.text) if message.type == 'error' and
            not re.search(r'\b(404|422)\b', message.text) else None)
    page.on('response', lambda response: resources.append({'url': response.url, 'status': response.status})
            if response.status >= 400 and response.request.resource_type in ('stylesheet', 'script', 'image', 'font') else None)


def login(page, user, variable, admin=False):
    page.goto(BASE + ('/admin/login/' if admin else '/login/'))
    page.locator('#id_username').fill(user)
    page.locator('#id_password').fill(values[variable])
    page.locator('input[type=submit], button[type=submit]').first.click()
    page.wait_for_load_state('networkidle')
    assert '/login/' not in page.url, page.url


def shot(page, name):
    page.screenshot(path=str(SHOTS / name), full_page=True, animations='disabled')


def no_overflow(page, name):
    metrics = page.evaluate('({width: innerWidth, scroll: document.documentElement.scrollWidth})')
    assert metrics['scroll'] <= metrics['width'], (name, metrics)
    mobile_routes.append(name)


with sync_playwright() as playwright:
    browser = playwright.chromium.launch(executable_path='/usr/bin/chromium', args=['--no-sandbox'])
    browser_version = browser.version
    previous_file = ROOT / 'var' / 'browser-check.json'
    if previous_file.exists():
        previous = json.loads(previous_file.read_text())
        persisted_context = browser.new_context(viewport={'width': 1440, 'height': 1000}, locale='ru-RU', timezone_id='Europe/Moscow')
        persisted = persisted_context.new_page()
        watch(persisted)
        login(persisted, previous['user'], 'DEMO_STUDENT_PASSWORD')
        persisted.goto(BASE + previous['request_url'])
        expect(persisted.get_by_text(previous['destination'], exact=True)).to_be_visible()
        expect(persisted.locator('.badge-large')).to_have_text('Готова')
        expect(persisted.locator('.timeline li')).to_have_count(5)
        shot(persisted, 'request-persisted.png')
        record('После перезапуска сервера: ранее созданная заявка, Готова и 5 записей истории сохранились')
        persisted_context.close()
    context = browser.new_context(viewport={'width': 1440, 'height': 1000}, locale='ru-RU', timezone_id='Europe/Moscow')
    page = context.new_page()
    watch(page)
    page.goto(BASE + '/login/')
    expect(page.get_by_text('Не является официальным сервисом вуза.', exact=False)).to_be_visible()
    shot(page, 'login.png')
    page.keyboard.press('Tab')
    focus = page.evaluate("({tag: document.activeElement.tagName, outline: getComputedStyle(document.activeElement).outlineStyle, width: getComputedStyle(document.activeElement).outlineWidth})")
    assert focus['outline'] != 'none' and focus['width'] != '0px', focus
    record('Клавиатурный фокус виден на странице входа')
    page.locator('#id_username').fill('alisa')
    page.locator('#id_password').fill('incorrect-browser-check')
    page.get_by_role('button', name='Войти в кабинет').click()
    expect(page.locator('.form-error')).to_be_visible()
    record('Неверный пароль отклонён, показана ошибка входа')
    login(page, 'alisa', 'DEMO_STUDENT_PASSWORD')
    expect(page.get_by_role('heading', name=re.compile('Алиса'))).to_be_visible()
    shot(page, 'dashboard-alisa.png')
    record('Алиса: вход и персональная главная страница')
    page.goto(BASE + '/schedule/?mode=week')
    shot(page, 'schedule.png')
    expect(page.get_by_text('10:40 → 11:45', exact=False).first).to_be_visible()
    record('Недельное расписание показывает переносы и прежние значения')
    today = datetime.now(ZoneInfo('Europe/Moscow')).date()
    sunday = today + timedelta(days=(6-today.weekday()) % 7)
    page.goto(BASE + '/schedule/?date=' + sunday.isoformat())
    expect(page.locator('.empty-state')).to_be_visible()
    record('Пустой выходной день отображается явно')
    page.goto(BASE + '/grades/')
    expect(page.get_by_text('Академическая задолженность', exact=False)).to_be_visible()
    alisa_grades = page.locator('main').inner_text()
    record('Успеваемость: оценки, зачёт, ожидание, отсутствие данных и долг')
    page.goto(BASE + '/requests/new/')
    page.locator('#id_kind').select_option('destination')
    page.locator('#id_text').fill('Проверка сохранения формы при ошибке. Все данные вымышлены.')
    page.get_by_role('button', name='Проверить данные').click()
    expect(page.locator('.field-errors')).to_be_visible()
    expect(page.locator('#id_text')).to_have_value('Проверка сохранения формы при ошибке. Все данные вымышлены.')
    record('Валидация места требования сохраняет введённый текст')
    destination = 'Вымышленная мастерская интерактивных образовательных интерфейсов и студенческих инициатив'
    page.locator('#id_destination').fill(destination)
    page.get_by_role('button', name='Проверить данные').click()
    expect(page.get_by_role('heading', name='Всё верно?')).to_be_visible()
    shot(page, 'request-review.png')
    page.get_by_role('button', name='Изменить', exact=True).click()
    expect(page.locator('#id_destination')).to_have_value(destination)
    page.get_by_role('button', name='Проверить данные').click()
    page.get_by_role('button', name='Отправить заявку', exact=False).click()
    page.wait_for_url(re.compile(r'/requests/\d+/$'))
    request_url = page.url.replace(BASE, '')
    request_pk = int(re.search(r'/requests/(\d+)/', request_url).group(1))
    request_number = f'ПК-{request_pk:05d}'
    expect(page.get_by_text(request_number, exact=True).first).to_be_visible()
    page.reload()
    expect(page.get_by_text(destination, exact=True)).to_be_visible()
    shot(page, 'request-detail.png')
    (ROOT / 'var' / 'browser-check.json').write_text(json.dumps({
        'user': 'alisa', 'request_url': request_url, 'request_pk': request_pk,
        'request_number': request_number, 'destination': destination,
    }, ensure_ascii=False, indent=2))
    record('Заявка: заполнение → проверка → редактирование → отправка → повторное открытие')

    staff_context = browser.new_context(viewport={'width': 1440, 'height': 1000}, locale='ru-RU', timezone_id='Europe/Moscow')
    staff = staff_context.new_page()
    watch(staff)
    login(staff, 'curator', 'DEMO_STAFF_PASSWORD', admin=True)
    admin_url = BASE + f'/admin/portal/studentrequest/{request_pk}/change/'
    staff.goto(admin_url)
    staff.locator('#id_status').select_option('work')
    staff.locator('#id_comment').fill('Браузерная проверка: обращение передано специалисту. Данные вымышлены.')
    staff.locator('input[name="_continue"]').click()
    expect(staff.locator('#id_status')).to_have_value('work')
    staff.locator('#id_status').select_option('clarify')
    staff.locator('#id_comment').fill('')
    staff.locator('input[name="_continue"]').click()
    expect(staff.locator('.errorlist')).to_be_visible()
    staff.locator('#id_comment').fill('Уточните учебную цель обращения для демонстрационной мастерской.')
    staff.locator('input[name="_continue"]').click()
    expect(staff.locator('#id_status')).to_have_value('clarify')
    shot(staff, 'admin-status.png')
    page.goto(BASE + request_url)
    expect(page.get_by_role('heading', name='Деканату нужно уточнение')).to_be_visible()
    page.locator('#id_text').fill('Это вымышленная справка для участия в учебном проекте. Проверка ответа студента.')
    page.get_by_role('button', name='Отправить уточнение').click()
    expect(page.get_by_text('Уточнение отправлено в деканат.', exact=True)).to_be_visible()
    staff.goto(admin_url)
    staff.locator('#id_status').select_option('ready')
    staff.locator('#id_comment').fill('Демонстрационная справка готова. Выдача настоящих документов не предусмотрена.')
    staff.locator('input[name="_continue"]').click()
    page.goto(BASE + request_url)
    expect(page.locator('.badge-large')).to_have_text('Готова')
    expect(page.locator('.timeline li')).to_have_count(5)
    shot(page, 'request-ready.png')
    record('Сотрудник: В работе → обязательное уточнение; ответ студента; Готова и полная история')

    page.goto(BASE + '/notifications/')
    page.locator('#notification-kind').select_option('request')
    page.get_by_role('button', name='Показать', exact=True).click()
    assert 'kind=request' in page.url
    page.get_by_role('link', name='Открыть →').first.click()
    page.get_by_role('button', name='Отметить прочитанным').click()
    expect(page.get_by_text('Уведомление отмечено прочитанным.', exact=True)).to_be_visible()
    record('Уведомления: фильтр, открытие и сохранение прочтения')

    mobile_context = browser.new_context(viewport={'width': 360, 'height': 800}, is_mobile=True, has_touch=True,
                                          locale='ru-RU', timezone_id='Europe/Moscow')
    mobile = mobile_context.new_page()
    watch(mobile)
    mobile.goto(BASE + '/login/')
    no_overflow(mobile, 'login')
    login(mobile, 'alisa', 'DEMO_STUDENT_PASSWORD')
    for name, route in [('dashboard','/'), ('schedule','/schedule/?mode=week'), ('grades','/grades/'),
                        ('requests','/requests/'), ('profile','/profile/'), ('notifications','/notifications/'),
                        ('request-new','/requests/new/'), ('request-detail',request_url)]:
        mobile.goto(BASE + route)
        no_overflow(mobile, name)
        if name == 'dashboard':
            expect(mobile.locator('.mobile-nav')).to_be_visible()
            shot(mobile, 'mobile-dashboard.png')
        if name == 'request-new':
            mobile.locator('#id_destination').fill(destination)
            mobile.locator('#id_text').fill('Длинный вымышленный текст для проверки переноса на мобильном экране.')
            shot(mobile, 'mobile-request.png')
    # Test actual bottom navigation, not only direct routes.
    mobile.locator('.mobile-nav').get_by_role('link', name='Расписание', exact=True).click()
    expect(mobile.get_by_role('heading', name='Расписание', exact=True)).to_be_visible()
    mobile.locator('.mobile-nav').get_by_role('link', name='Профиль', exact=True).click()
    mobile.locator('main').get_by_role('button', name='Выйти', exact=True).click()
    mobile.goto(BASE + '/profile/')
    assert '/login/' in mobile.url
    record('360 px: вход, 5 разделов, уведомления и формы без горизонтального скролла; нижняя навигация и выход')

    second_context = browser.new_context(viewport={'width':1440, 'height':1000}, locale='ru-RU', timezone_id='Europe/Moscow')
    second = second_context.new_page()
    watch(second)
    login(second, 'maks', 'DEMO_SECOND_PASSWORD')
    expect(second.get_by_role('heading', name=re.compile('Максим'))).to_be_visible()
    shot(second, 'dashboard-maks.png')
    second.goto(BASE + '/profile/')
    expect(second.get_by_text('ДИЗ-04-24', exact=True).first).to_be_visible()
    second.goto(BASE + '/grades/')
    assert second.locator('main').inner_text() != alisa_grades
    response = second.goto(BASE + request_url)
    assert response.status == 404
    second.goto(BASE + '/profile/')
    second.locator('main').get_by_role('button', name='Выйти', exact=True).click()
    second.goto(BASE + '/requests/')
    assert '/login/' in second.url
    record('Максим: другой профиль и успеваемость; чужая заявка 404; выход закрывает доступ')

    summary = {'run_at': datetime.now(ZoneInfo('Europe/Moscow')).isoformat(), 'browser': 'Chromium '+browser_version,
               'base': BASE, 'checks': checks, 'mobile_routes': mobile_routes, 'page_errors': errors,
               'resource_errors': resources, 'request_url': request_url}
    (ROOT / 'var' / 'browser-summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2))
    browser.close()

assert not errors, errors
assert not resources, resources
print('All browser smoke checks passed; screenshots saved in docs/screenshots/.')
