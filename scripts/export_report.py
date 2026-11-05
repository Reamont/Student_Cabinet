"""Export the factual Markdown report with local screenshots to HTML and PDF.

Run: python scripts/export_report.py (requires requirements-dev.txt + Chromium).
Small renderer intentionally supports only the syntax used by process-report.md.
"""
import html
import base64
import re
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / 'docs'


def inline(text):
    text = html.escape(text)
    text = re.sub(r'`([^`]+)`', r'<code>\1</code>', text)
    text = re.sub(r'\*\*([^*]+)\*\*', r'<strong>\1</strong>', text)
    text = re.sub(r'\[([^]]+)\]\(([^)]+)\)', r'<a href="\2">\1</a>', text)
    return text


def render(source):
    parts = []
    in_table = False
    for line in source.splitlines():
        if not line.startswith('|') and in_table:
            parts.append('</tbody></table>')
            in_table = False
        if line.startswith('|'):
            cells = [c.strip() for c in line.strip('|').split('|')]
            if all(re.fullmatch(r'[-: ]+', c) for c in cells):
                continue
            if not in_table:
                parts.append('<table><tbody>')
                in_table = True
            parts.append('<tr>' + ''.join('<td>'+inline(c)+'</td>' for c in cells) + '</tr>')
        elif match := re.fullmatch(r'!\[([^]]*)\]\(([^)]+)\)', line.strip()):
            path = (DOCS / match[2]).resolve()
            if not path.is_relative_to(DOCS) or not path.is_file():
                raise ValueError('Missing or unsafe screenshot: ' + match[2])
            parts.append(f'<figure><img src="{html.escape(match[2])}" alt="{html.escape(match[1])}"><figcaption>{html.escape(match[1])}</figcaption></figure>')
        elif line.startswith('#'):
            level = len(line) - len(line.lstrip('#'))
            parts.append(f'<h{level}>{inline(line[level:].strip())}</h{level}>')
        elif line.strip():
            parts.append('<p>'+inline(line)+'</p>')
    if in_table:
        parts.append('</tbody></table>')
    return '\n'.join(parts)


if __name__ == '__main__':
    content = render((DOCS / 'process-report.md').read_text())
    style = '''body{font:13px/1.65 Arial,sans-serif;color:#213333;max-width:900px;margin:auto}h1{font-size:32px}h2{margin-top:32px;font-size:22px;break-after:avoid}table{width:100%;border-collapse:collapse;font-size:11px}td{border:1px solid #dce1d7;padding:8px}tr{break-inside:avoid}figure{margin:24px 0;break-inside:avoid}img{display:block;max-width:100%;max-height:225mm;margin:auto;object-fit:contain}figcaption{font-size:11px;color:#4d5e57;text-align:center}code{font-size:11px}a{color:#285d42}p{orphans:3;widows:3}'''
    output = DOCS / 'process-report.html'
    output.write_text('<!doctype html><html lang="ru"><meta charset="utf-8"><title>Пульс Кампуса — отчёт</title><style>'+style+'</style><body>'+content+'</body></html>')
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path='/usr/bin/chromium', args=['--no-sandbox'])
        page = browser.new_page()
        # Managed browsers may disallow file:// navigation. Embed only the
        # already-validated report screenshots; no server or external fetches.
        printable = output.read_text()
        def embed(match):
            data = base64.b64encode((DOCS / match[1]).read_bytes()).decode()
            return 'src="data:image/png;base64,' + data + '"'
        printable = re.sub(r'src="(screenshots/[^\"]+\.png)"', embed, printable)
        page.set_content(printable, wait_until='load')
        assert page.locator('img').evaluate_all('(images)=>images.every(i=>i.complete && i.naturalWidth>0)'), 'Screenshot failed to load'
        page.pdf(path=str(DOCS / 'process-report.pdf'), format='A4', print_background=True,
                 margin={'top':'16mm', 'bottom':'16mm', 'left':'15mm', 'right':'15mm'})
        browser.close()
    print('Exported docs/process-report.html and docs/process-report.pdf with real screenshots.')
