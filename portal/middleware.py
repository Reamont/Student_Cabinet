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



def login_keys(request, username):
    identifiers = [('account:' + username.strip().casefold(), 10)]
    if not settings.LOGIN_RATE_LIMIT_AT_PROXY:
        identifiers.append(('address:' + request.META.get('REMOTE_ADDR', ''), 40))
    return [(hmac.new(settings.SECRET_KEY.encode(), value.encode(), hashlib.sha256).hexdigest(), limit)
            for value, limit in identifiers]


def is_login_request(request):
    return request is not None and request.method == 'POST' and request.path in ('/login/', '/admin/login/')


from django.contrib.auth.signals import user_login_failed, user_logged_in
from django.dispatch import receiver


@receiver(user_login_failed, dispatch_uid='campus_failed_login')
def failed_login(sender, credentials, request=None, **kwargs):
    if not is_login_request(request):
        return
    now = timezone.now()
    with transaction.atomic():
        for key, limit in login_keys(request, credentials.get('username', '')):
            LoginThrottle.objects.get_or_create(key=key)
            row = LoginThrottle.objects.select_for_update().get(key=key)
            if now - row.started_at >= timedelta(minutes=15):
                row.failures = 0
                row.started_at = now
            row.failures += 1
            row.save(update_fields=['failures', 'started_at'])


@receiver(user_logged_in, dispatch_uid='campus_successful_login')
def successful_login(sender, request, user, **kwargs):
    if is_login_request(request):
        # Clear this account only; failed attempts from the address remain limited.
        key, _ = login_keys(request, request.POST.get('username', user.username))[0]
        LoginThrottle.objects.filter(key=key).delete()


class LoginRateLimitMiddleware:
    """Check failed logins; never trust client-supplied forwarded addresses.

    The bundled nginx handles per-connection traffic limits when configured;
    account failures are always tracked in the shared database.
    """
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        return self.get_response(request)

    def process_view(self, request, view_func, view_args, view_kwargs):
        if not is_login_request(request):
            return None
        now = timezone.now()
        wait = 0
        for key, limit in login_keys(request, request.POST.get('username', '')):
            row = LoginThrottle.objects.filter(key=key).first()
            if row and row.failures >= limit:
                remaining = 900 - (now - row.started_at).total_seconds()
                wait = max(wait, int(remaining) + 1 if remaining > 0 else 0)
        if wait:
            response = HttpResponse(
                '<!doctype html><html lang="ru"><meta name="viewport" content="width=device-width, initial-scale=1">'
                '<title>Попробуйте позже</title><h1>Слишком много неудачных попыток входа</h1>'
                '<p>Подождите до 15 минут и повторите вход.</p><a href="/login/">Вернуться ко входу</a></html>', status=429)
            response['Retry-After'] = str(wait)
            return response
