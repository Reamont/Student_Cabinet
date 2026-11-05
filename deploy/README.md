# Развёртывание на отдельном VPS с постоянной БД

Этот путь подготовлен для Ubuntu 24.04, Docker Compose v2 и nginx. Локально проверены Docker-сборка, Gunicorn непривилегированным пользователем, реальная PostgreSQL 17, чистые миграции и `check --deploy`. Публичное развёртывание не выполнено: нужны VPS, домен, DNS и право владельца на расходы. Выберите российский дата-центр, если это нужно для аудитории конкурса; реальную доступность проверяют из российской сети без VPN. Провайдер, тариф и цена не подтверждены.

## 1. Сервер, DNS и доступ

Направьте A/AAAA запись своего домена на сервер. Не создавайте AAAA, если IPv6 не настроен. На firewall откройте только SSH для администратора и TCP 80/443 для сайта. PostgreSQL не публикуется; Gunicorn слушает loopback хоста. Работайте отдельным администратором с SSH-ключом.

На новом выделенном сервере установите пакеты из подписанных репозиториев Ubuntu:

```sh
sudo apt-get update
sudo apt-get install -y docker.io docker-compose-v2 nginx certbot python3
sudo systemctl enable --now docker nginx
```

Загрузите исходники в `/srv/campus` через Git с имеющимся доступом или распакуйте предоставленный архив. Не переносите `var/dev.env`, `.venv` и SQLite из разработки в production. Сначала проверьте отсутствие неожиданных файлов и локальных изменений.

## 2. Создайте уникальную конфигурацию

В корне проекта задайте настоящий домен и создайте `.env` без вывода секретов:

```sh
cd /srv/campus
export CAMPUS_DOMAIN=campus.your-domain.ru
python3 - <<'PY'
import os, secrets
from pathlib import Path
domain = os.environ['CAMPUS_DOMAIN']
if not domain or any(c in domain for c in '/\n\r ,:'):
    raise SystemExit('Нужен hostname без схемы и пути')
values = {
    'APP_ENV': 'production', 'DJANGO_DEBUG': '0',
    'DJANGO_SECRET_KEY': secrets.token_urlsafe(64),
    'POSTGRES_PASSWORD': secrets.token_urlsafe(32),
    'DJANGO_ALLOWED_HOSTS': domain + ',localhost',
    'DJANGO_CSRF_TRUSTED_ORIGINS': 'https://' + domain,
    'DEMO_STUDENT_PASSWORD': secrets.token_urlsafe(18),
    'DEMO_SECOND_PASSWORD': secrets.token_urlsafe(18),
    'DEMO_STAFF_PASSWORD': secrets.token_urlsafe(24),
}
fd = os.open('.env', os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
with os.fdopen(fd, 'w') as f:
    f.write(''.join(f'{k}={v}\n' for k, v in values.items()))
print('Создан .env с правами 0600; значения не напечатаны.')
PY
```

Команда не перезаписывает существующий `.env`. Если файл уже есть, сохраните его и внесите необходимые изменения вручную. Не запускайте `docker compose config` без `--quiet` в публикуемых логах: вывод может содержать значения окружения.

## 3. Приложение и PostgreSQL

```sh
sudo docker compose --env-file .env -f deploy/compose.yaml config --quiet
sudo docker compose --env-file .env -f deploy/compose.yaml build
sudo docker compose --env-file .env -f deploy/compose.yaml up -d db
sudo docker compose --env-file .env -f deploy/compose.yaml run --rm web python manage.py migrate --noinput
sudo docker compose --env-file .env -f deploy/compose.yaml run --rm web python manage.py seed_demo
sudo docker compose --env-file .env -f deploy/compose.yaml run --rm web python manage.py check --deploy
sudo docker compose --env-file .env -f deploy/compose.yaml up -d web
sudo docker compose --env-file .env -f deploy/compose.yaml ps
```

Compose ожидает готовности PostgreSQL. Статика собирается в образе. Production использует БД в томе `campus-pulse_postgres_data`, а не файловую систему контейнера. Повторный seed не должен удалять обращения и менять существующие пароли. Передайте два студенческих пароля жюри приватно; пароль `curator` — отдельно ответственному демонстратору. Пароли не включайте в репозиторий и публичные скриншоты.

Если сборка проходит в корпоративной или облачной сети с доверенным TLS-прокси, BuildKit поддерживает необязательный secret `proxy_ca`. Передайте **CA bundle**, а не credential-файл: `docker build --secret id=proxy_ca,src=/etc/ssl/certs/ca-certificates.crt -t campus-pulse-web .`. Он доступен только во время шага pip и не копируется в образ. Сохраняйте наследуемые proxy-настройки среды; не отключайте проверку TLS. Обычному VPS этот secret не нужен.

Сервер внутри пока доступен только администратору. Внутреннюю readiness-проверку выполняйте с заголовками доверенного прокси:

```sh
curl --fail --silent --output /dev/null \
  --header 'Host: localhost' --header 'X-Forwarded-Proto: https' \
  http://127.0.0.1:8000/login/
```

Это проверяет ответ приложения; функциональные сценарии ниже всё равно обязательны.

## 4. Сертификат и nginx

Сначала подготовьте каталог ACME:

```sh
sudo mkdir -p /var/www/letsencrypt
```

Создайте `/etc/nginx/sites-available/campus` со своим доменом:

```nginx
server {
    listen 80;
    server_name campus.your-domain.ru;
    location /.well-known/acme-challenge/ {
        root /var/www/letsencrypt;
    }
    location / { return 200 'HTTPS setup in progress'; }
}
```

Активируйте конфигурацию, проверьте DNS и выпустите сертификат (укажите настоящую почту владельца):

```sh
sudo ln -s /etc/nginx/sites-available/campus /etc/nginx/sites-enabled/campus
sudo nginx -t
sudo systemctl reload nginx
sudo certbot certonly --webroot -w /var/www/letsencrypt \
  -d campus.your-domain.ru --email owner@your-domain.ru --agree-tos --non-interactive
```

Если символьная ссылка уже существует, не создавайте её повторно. Замените временный server блок содержимым `deploy/nginx.conf`, **во всех местах** заменив `campus.example.org` своим доменом, включая пути сертификатов. Затем:

```sh
sudo nginx -t
sudo systemctl reload nginx
sudo certbot renew --dry-run
```

Для перезагрузки nginx после обновления сертификата создайте исполняемый deploy-hook `/etc/letsencrypt/renewal-hooks/deploy/reload-nginx`:

```sh
#!/bin/sh
set -eu
nginx -t
systemctl reload nginx
```

Проверьте работу системного таймера обновления сертификатов. На домене и его поддоменах должен работать HTTPS: приложение включает HSTS с `includeSubDomains`. Не используйте этот шаблон на домене с неподготовленными поддоменами.

## 5. Проверка перед передачей

Проверьте реальный HTTPS-адрес снаружи, сертификат, перенаправление с HTTP и отсутствие внешнего доступа к 8000/5432. В браузере выполните сценарий из `docs/demo-script.md` для двух студентов и сотрудника. Создайте новую заявку, перезапустите только web-контейнер и убедитесь, что запись осталась. Проверьте, что после выхода закрытые страницы требуют входа.

Попросите владельца или уполномоченного тестировщика открыть сайт из российской сети **без VPN**; запишите дату, сеть/регион без персональных данных и результат. Проверка из облачного контейнера не доказывает доступность из России.

До 28 ноября (срок взят из задания, официальный источник ещё не предоставлен) обеспечьте оплату сервера и домена, свободное место, отсутствие спящего режима, мониторинг HTTPS/срока сертификата и ежедневное резервное копирование. Конкретный дедлайн подачи неизвестен.

## 6. Резервная копия и обновление

Резервную копию держите отдельно от единственного VPS, зашифрованной, с ограниченным доступом. Например, локальный дамп:

```sh
cd /srv/campus
umask 077
mkdir -p /srv/backups/campus
sudo docker compose --env-file .env -f deploy/compose.yaml exec -T db \
  pg_dump -U campus -d campus -Fc > /srv/backups/campus/campus.dump
test -s /srv/backups/campus/campus.dump
```

Используйте уникальные имена файлов в ежедневном задании и политику хранения; пример выше перезаписывает один локальный дамп. Проверяйте восстановление в **отдельную пустую БД**, не поверх рабочей. Сам факт наличия файла не доказывает восстанавливаемость.

Перед обновлением сохраните дамп и прежний образ/версию исходников. Затем соберите новый образ, выполните миграции и перезапустите web:

```sh
sudo docker compose --env-file .env -f deploy/compose.yaml build web
sudo docker compose --env-file .env -f deploy/compose.yaml run --rm web python manage.py migrate --noinput
sudo docker compose --env-file .env -f deploy/compose.yaml up -d web
```

**Не запускайте `docker compose down -v`: это удаляет том БД.** Изменение `POSTGRES_PASSWORD` в `.env` не меняет автоматически пароль уже созданного пользователя PostgreSQL; ротацию делайте согласованно на сервере БД и в конфигурации. Не обновляйте major-версию образа PostgreSQL без отдельного плана миграции.

Ограничения: Docker/HTTPS на внешнем VPS и резервное восстановление должны быть проверены владельцем. Эта инструкция не означает выполненную публикацию или эксплуатационную аттестацию.

## Ограничение входа

Compose включает `LOGIN_RATE_LIMIT_AT_PROXY=1`. Установите весь `deploy/nginx.conf`, включая `map` и `limit_req_zone` в контексте `http` (обычно через `sites-enabled`). nginx ограничивает POST `/login/` и `/admin/login/` по адресу клиента: 3 запроса в минуту, всплеск до 40, затем HTTP 429. Лимит аккаунта 10/15 минут остаётся в приложении. Не открывайте порт приложения извне и не включайте этот флаг без ограничения на прокси. Заголовки клиента не определяют адрес для лимита. При добавлении CDN/другого прокси отдельно настройте real_ip только для доверенных адресов. Проверьте два разных клиентских IP: превышение лимита одним не должно блокировать другой.
