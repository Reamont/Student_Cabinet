import hashlib
import hmac
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.http import HttpResponse
from django.utils import timezone

from .models import LoginThrottle


class PrivateResponseMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        if not request.path.startswith('/static/'):
            response['Cache-Control'] = 'no-store, private'
            response['Content-Security-Policy'] = (
                "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
                "font-src 'self'; object-src 'none'; base-uri 'self'; frame-ancestors 'none'; form-action 'self'"
            )
        return response


class LoginRateLimitMiddleware:
    """Shared DB-backed window for student and built-in employee login.

    Count all POST attempts, including successful ones. Never trust X-Forwarded-For;
    deployment proxy must preserve source isolation or enforce its own edge limit.
    """
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        return self.get_response(request)

    def process_view(self, request, view_func, view_args, view_kwargs):
        if request.method != 'POST' or request.path not in ('/login/', '/admin/login/'):
            return None
        identifiers = [('account:' + request.POST.get('username', '').strip().casefold(), 10),
                       ('address:' + request.META.get('REMOTE_ADDR', ''), 40)]
        blocked = False
        now = timezone.now()
        with transaction.atomic():
            for identifier, limit in identifiers:
                key = hmac.new(settings.SECRET_KEY.encode(), identifier.encode(), hashlib.sha256).hexdigest()
                row, _ = LoginThrottle.objects.get_or_create(key=key)
                row = LoginThrottle.objects.select_for_update().get(pk=row.pk)
                if now - row.started_at >= timedelta(minutes=15):
                    row.failures = 0
                    row.started_at = now
                if row.failures >= limit:
                    blocked = True
                else:
                    row.failures += 1
                row.save(update_fields=['failures', 'started_at'])
        if blocked:
            response = HttpResponse(
                '<!doctype html><html lang="ru"><meta name="viewport" content="width=device-width, initial-scale=1">'
                '<title>Попробуйте позже</title><h1>Слишком много попыток входа</h1>'
                '<p>Подождите 15 минут. Это временная защита аккаунта.</p><a href="/login/">Вернуться ко входу</a></html>',
                status=429,
            )
            response['Retry-After'] = '900'
            return response
