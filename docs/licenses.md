# Сторонние материалы и лицензии

Собственный код и графика проекта распространяются по [MIT](../LICENSE). Интерфейс использует собственные стили, SVG и системные шрифты. Внешних фотографий, шрифтовых CDN, официальных университетских логотипов и платных графических наборов нет. Данные и название вуза вымышлены.

Версии и лицензии ниже сверены с метаданными реально установленного Python-окружения. Полные тексты лицензий входят в установленные пакеты; их уведомления нельзя удалять при распространении зависимостей. Исходники приложения поставляются отдельно от `.venv`.

| Зависимость | Версия | Лицензия | Источник |
| --- | --- | --- | --- |
| Django | 5.2.19 | BSD-3-Clause; дополнительные Python notices | [PyPI](https://pypi.org/project/Django/5.2.19/), [документация](https://docs.djangoproject.com/en/5.2/) |
| asgiref | 3.13.0 | BSD-3-Clause | [PyPI](https://pypi.org/project/asgiref/3.13.0/) |
| dj-database-url | 3.1.2 | BSD-3-Clause | [PyPI](https://pypi.org/project/dj-database-url/3.1.2/) |
| gunicorn | 26.2.0 | MIT | [PyPI](https://pypi.org/project/gunicorn/26.2.0/) |
| psycopg | 3.3.8 | LGPL-3.0-only | [PyPI](https://pypi.org/project/psycopg/3.3.8/) |
| psycopg-binary | 3.3.8 | LGPL-3.0-only | [PyPI](https://pypi.org/project/psycopg-binary/3.3.8/) |
| sqlparse | 0.6.1 | BSD (текст в LICENSE пакета) | [PyPI](https://pypi.org/project/sqlparse/0.6.1/) |
| typing_extensions | 4.16.0 | PSF-2.0 | [PyPI](https://pypi.org/project/typing-extensions/4.16.0/) |
| whitenoise | 6.12.0 | MIT | [PyPI](https://pypi.org/project/whitenoise/6.12.0/) |
| Playwright (только разработка) | 1.62.0 | Apache-2.0 | [PyPI](https://pypi.org/project/playwright/1.62.0/) |

`psycopg-binary` включает нативные библиотеки; их отдельные уведомления, в том числе PostgreSQL/libpq и OpenSSL, сохраняются в дистрибутиве. LGPL-компоненты не объявляются собственным кодом проекта; исходные пакеты доступны по указанным ссылкам. Для отдельной поставки изменённых/встроенных бинарных сборок нужно дополнительно проверить условия LGPL, доступность исходников и возможность замены библиотеки.

## Статика административной панели

Вместе с Django admin поставляются jQuery 3.7.1, Select2 4.0.13 и XRegExp — MIT. SVG-иконки admin происходят из Font-Awesome-SVG-PNG (Code Charm Ltd) и имеют MIT-уведомление в `django/contrib/admin/static/admin/img/LICENSE`. README Django также указывает Font Awesome / SIL OFL 1.1; шрифт Font Awesome в студенческую часть не добавлен. Уведомления поставляются со статикой Django и сохраняются `collectstatic`.

## Инструменты и серверная среда

Python — PSF, PostgreSQL — PostgreSQL License, nginx — BSD-2-Clause; Docker Official Images содержат компоненты ОС со своими лицензиями. Они не становятся частью собственного кода приложения. Демо-проверки могут использовать Chromium и Playwright как инструменты разработчика; их нет в production-зависимостях. Полные условия бинарных образов проверяйте при выборе версии и распространении образов.

MIT для собственного кода не заменяет отдельные лицензии зависимостей. Этот перечень не меняет авторство и условия сторонних компонентов.
