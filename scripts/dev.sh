#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p var
if [ ! -f var/dev.env ]; then
  .venv/bin/python - <<'PY'
import os, secrets, shlex
from pathlib import Path
values = {'DJANGO_SECRET_KEY': secrets.token_urlsafe(48),
          'DEMO_STUDENT_PASSWORD': secrets.token_urlsafe(18),
          'DEMO_SECOND_PASSWORD': secrets.token_urlsafe(18),
          'DEMO_STAFF_PASSWORD': secrets.token_urlsafe(24)}
p = Path('var/dev.env')
fd = os.open(p, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
with os.fdopen(fd, 'w') as f:
    f.write(''.join(k+'='+shlex.quote(v)+'\n' for k,v in values.items()))
p = Path('var/demo-access.txt')
fd = os.open(p, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
with os.fdopen(fd, 'w') as f:
    f.write('Локальные демонстрационные аккаунты. Не включать в публичный архив.\n')
    for username, key in [('alisa','DEMO_STUDENT_PASSWORD'),('maks','DEMO_SECOND_PASSWORD'),('curator','DEMO_STAFF_PASSWORD')]:
        f.write(username+': '+values[key]+'\n')
PY
fi
set -a
source var/dev.env
set +a
.venv/bin/python manage.py migrate --noinput
.venv/bin/python manage.py seed_demo
.venv/bin/python manage.py collectstatic --noinput
echo 'Local demo accounts: alisa, maks, curator. Private credentials: var/demo-access.txt'
exec .venv/bin/python manage.py runserver 127.0.0.1:8000 --noreload
