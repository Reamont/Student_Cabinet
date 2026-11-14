import re,shlex,uuid,json
from pathlib import Path
from playwright.sync_api import sync_playwright,expect
root=Path(__file__).resolve().parent.parent
cred={k:shlex.split(v)[0] for k,v in (line.split('=',1) for line in (root/'var/dev.env').read_text().splitlines())}
import os
base=os.environ.get('SMOKE_BASE_URL','http://127.0.0.1:8000').rstrip('/')
results=[]
with sync_playwright() as p:
    browser=p.chromium.launch(executable_path='/usr/bin/chromium',args=['--no-sandbox'])
    for width,js in [(1440,True),(360,True),(360,False)]:
        ctx=browser.new_context(viewport={'width':width,'height':800},java_script_enabled=js,reduced_motion='reduce',locale='ru-RU',timezone_id='Europe/Moscow')
        page=ctx.new_page(); errors=[]
        page.on('pageerror',lambda e:errors.append(str(e)))
        page.goto(base+'/login/');page.locator('#id_username').fill('alisa@campus.example.test');page.locator('#id_password').fill(cred['DEMO_STUDENT_PASSWORD']);page.get_by_role('button',name='Войти в кабинет').click()
        page.goto(base+'/study/tasks/')
        overflow=page.evaluate('document.documentElement.scrollWidth-innerWidth')
        page.screenshot(path=str(root/f'var/task-list-{width}-{js}.png'),full_page=True)
        page.get_by_role('link',name='Добавить задачу',exact=True).first.click()
        title='Вымышленная учебная задача '+uuid.uuid4().hex[:7]
        page.locator('#id_title').fill(title);page.locator('#id_discipline').select_option(index=1);page.locator('#id_due').fill('2026-11-26T18:30')
        form_overflow=page.evaluate('document.documentElement.scrollWidth-innerWidth')
        page.get_by_role('button',name='Добавить задачу',exact=True).click()
        task=page.locator('.deadline-row').filter(has_text=title)
        expect(task).to_be_visible()
        task_id=task.get_attribute('id')
        task.get_by_role('link',name='Изменить',exact=True).click()
        expect(page.locator('#id_due')).to_have_value('2026-11-26T18:30')
        page.locator('#id_title').fill(title+' изменена');page.locator('#id_due').fill('2026-11-27T19:00');page.get_by_role('button',name='Сохранить изменения').click()
        page.goto(base+'/semester/?month=2026-11&kind=tasks')
        expect(page.locator('#day-2026-11-27')).to_contain_text(title+' изменена')
        page.goto(base+'/study/tasks/')
        task=page.locator('#'+task_id);task.get_by_role('link',name='Удалить',exact=True).click()
        page.get_by_role('button',name='Удалить задачу',exact=True).click()
        expect(page.locator('#'+task_id)).to_have_count(0)
        results.append({'width':width,'js':js,'list_overflow_px':overflow,'form_overflow_px':form_overflow,'create_edit_semester_delete':'passed','js_errors':errors})
        print(json.dumps(results[-1],ensure_ascii=False),flush=True)
        ctx.close()
    browser.close()
