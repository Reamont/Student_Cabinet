from django.contrib import messages
from django.contrib.auth import get_user_model
from django.db import transaction
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_GET, require_POST

from .experience import VIEW_CHOICES
from .models import Deadline, LearningResult, ViewPreference
from .views import student_required


@student_required
@require_POST
def preference_save(request):
    updates = {key: request.POST[key] for key in VIEW_CHOICES if key in request.POST}
    if not updates or any(value not in VIEW_CHOICES[key] for key, value in updates.items()):
        return JsonResponse({'error': 'Не удалось запомнить вид. Проверь выбранные фильтры.'}, status=422)
    with transaction.atomic():
        get_user_model().objects.select_for_update().get(pk=request.user.pk)
        record, _ = ViewPreference.objects.get_or_create(user=request.user)
        current = record.values if isinstance(record.values, dict) else {}
        record.values = {**{k: v for k, v in current.items() if k in VIEW_CHOICES and v in VIEW_CHOICES[k]},
                         **updates}
        record.save(update_fields=['values'])
    if 'application/json' in request.headers.get('Accept', ''):
        return JsonResponse({'saved': True})
    target = request.POST.get('next', '')
    if not url_has_allowed_host_and_scheme(target, allowed_hosts={request.get_host()}, require_https=request.is_secure()):
        target = reverse('dashboard')
    messages.success(request, 'Вид сохранён для твоего аккаунта.')
    return redirect(target)


@student_required
@require_GET
def study(request):
    return render(request, 'portal/study.html', {'nav_section': 'study',
        'unfinished': Deadline.objects.filter(user=request.user, done=False).count(),
        'result_count': LearningResult.objects.filter(user=request.user).count()})


@student_required
@require_GET
def tasks(request):
    return render(request, 'portal/tasks.html', {'nav_section': 'study',
        'deadlines': Deadline.objects.filter(user=request.user).select_related('discipline')})


@student_required
@require_GET
def more(request):
    return render(request, 'portal/more.html', {'nav_section': 'more'})


@require_GET
def about(request):
    return render(request, 'portal/about.html', {'nav_section': 'more'})
