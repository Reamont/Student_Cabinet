from datetime import date, timedelta
from functools import wraps

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import LoginView
from django.db import transaction
from django.db.models import Avg, Q
from django.http import HttpResponseNotAllowed
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

from .forms import ClarificationForm, RequestDraftForm, RequestForm
from .models import Deadline, LearningResult, Lesson, Notification, Profile, RequestDraft, StudentRequest
from .services import sync_task_notification, lock_request_owner, record_status, save_request_draft
from .experience import view_option


class StudentLoginView(LoginView):
    template_name = 'portal/login.html'
    redirect_authenticated_user = True

    def get_success_url(self):
        if self.request.user.is_staff and not Profile.objects.filter(user=self.request.user).exists():
            return reverse('admin:index')
        return super().get_success_url()


def student_required(view):
    @login_required
    @wraps(view)
    def inner(request, *args, **kwargs):
        request.student = get_object_or_404(Profile.objects.select_related('group'), user=request.user)
        return view(request, *args, **kwargs)
    return inner


def lessons_for(profile, start, end):
    now = timezone.localtime()
    lessons = list(Lesson.objects.filter(group=profile.group, date__range=(start, end)).select_related('discipline'))
    next_id = (Lesson.objects.filter(group=profile.group, cancelled=False)
               .filter(Q(date__gt=now.date()) | Q(date=now.date(), start__gt=now.time()))
               .order_by('date', 'start').values_list('pk', flat=True).first())
    for lesson in lessons:
        lesson.is_current = not lesson.cancelled and lesson.date == now.date() and lesson.start <= now.time() < lesson.end
        lesson.is_next = lesson.pk == next_id and not lesson.is_current
    return lessons


def average_for(user):
    result = LearningResult.objects.filter(user=user, state='grade').aggregate(value=Avg('grade'))['value']
    return f'{result:.2f}'.replace('.', ',') if result is not None else None


@student_required
def dashboard(request):
    now = timezone.localtime()
    today = now.date()
    lessons = lessons_for(request.student, today, today + timedelta(days=14))
    next_lesson = (Lesson.objects.filter(group=request.student.group, cancelled=False)
                   .filter(Q(date__gt=today) | Q(date=today, end__gt=now.time()))
                   .select_related('discipline').order_by('date', 'start').first())
    if next_lesson:
        next_lesson.is_current = (next_lesson.date == today and
                                  next_lesson.start <= now.time() < next_lesson.end)
    deadlines = list(Deadline.objects.filter(user=request.user, done=False, due__gte=now)
                     .select_related('discipline')[:5])
    active = StudentRequest.objects.filter(user=request.user).exclude(status__in=['ready', 'rejected'])[:4]
    plan = []
    for lesson in lessons:
        if lesson.date == today and not lesson.cancelled:
            if lesson.end <= timezone.localtime().time():
                continue
            plan.append({'title': f'{lesson.start:%H:%M} · {lesson.discipline.name}',
                         'reason': f'{lesson.kind} · {lesson.room}' + (' · расписание изменено' if lesson.change_note else ''),
                         'url': reverse('schedule') + '?date=' + today.isoformat(), 'kind': 'Занятие'})
    for deadline in Deadline.objects.filter(user=request.user, done=False, due__date__lte=today).select_related('discipline'):
        if timezone.localtime(deadline.due).date() <= today:
            plan.append({'title': deadline.title, 'reason': 'Срок прошёл — проверьте выполнение' if deadline.due < now else 'Срок сегодня',
                         'url': reverse('tasks') + f'#deadline-{deadline.pk}', 'kind': 'Дедлайн'})
    for item in StudentRequest.objects.filter(user=request.user, status='clarify'):
        plan.append({'title': f'{item.number} · Ответьте на уточнение', 'reason': 'Деканату нужны дополнительные сведения',
                     'url': reverse('request_detail', args=[item.pk]), 'kind': 'Заявка'})
    clarification = StudentRequest.objects.filter(user=request.user, status='clarify').first()
    overdue = Deadline.objects.filter(user=request.user, done=False, due__lt=now).order_by('due').first()
    debts = LearningResult.objects.filter(user=request.user, state='debt').select_related('discipline')
    next_action = None
    if clarification:
        next_action = {'title': 'Ответить на уточнение', 'reason': f'По заявке {clarification.number} нужны дополнительные сведения.',
                       'url': reverse('request_detail', args=[clarification.pk]) + '#clarification', 'button': 'Ответить на уточнение'}
    elif overdue:
        next_action = {'title': overdue.title, 'reason': 'Срок прошёл. Проверь, что ещё нужно сделать.',
                       'url': reverse('tasks') + f'#deadline-{overdue.pk}', 'button': 'Открыть задачу'}
    elif deadlines:
        next_action = {'title': deadlines[0].title, 'reason': 'Ближайший срок: ' + timezone.localtime(deadlines[0].due).strftime('%d.%m, %H:%M'),
                       'url': reverse('tasks') + f'#deadline-{deadlines[0].pk}', 'button': 'Открыть задачу'}
    elif debts:
        result = debts[0]
        next_action = {'title': result.discipline.name, 'reason': 'Есть академическая задолженность. Прочитай комментарий по дисциплине.',
                       'url': reverse('grades') + f'#result-{result.pk}', 'button': 'Посмотреть результат'}
    return render(request, 'portal/dashboard.html', {
        'nav_section': 'dashboard', 'next_lesson': next_lesson,
        'lessons': [l for l in lessons if l.date == today],
        'changed_lessons': [l for l in lessons if l.cancelled or l.old_start or l.old_room][:3],
        'deadlines': deadlines, 'active_requests': active, 'plan': plan,
        'results_attention': debts, 'next_action': next_action,
        'first_name': request.student.full_name.split()[0] if request.student.full_name.strip() else request.user.username,
        'other_actions': [entry for entry in plan if entry['kind'] != 'Занятие' and
                          (not next_action or entry['url'] not in (next_action['url'], next_action['url'].split('#')[0]))][:3],
        'average': average_for(request.user),
    })


@student_required
def schedule(request):
    try:
        selected = date.fromisoformat(request.GET.get('date', ''))
        if abs((selected - timezone.localdate()).days) > 3650:
            raise ValueError
    except (ValueError, TypeError):
        selected = timezone.localdate()
    mode = view_option(request, 'schedule_mode', 'mode', 'today')
    week_start = selected - timedelta(days=selected.weekday())
    start = week_start if mode == 'week' else selected
    end = start + timedelta(days=6) if mode == 'week' else start
    lessons = lessons_for(request.student, start, end)
    days = [{'date': start + timedelta(days=i), 'lessons': [l for l in lessons if l.date == start + timedelta(days=i)]}
            for i in range(7 if mode == 'week' else 1)]
    delta = timedelta(days=7 if mode == 'week' else 1)
    return render(request, 'portal/schedule.html', {'nav_section': 'schedule', 'mode': mode, 'days': days,
        'selected_date': selected, 'week_start': week_start, 'prev_date': selected-delta, 'next_date': selected+delta,
        'view_memory': {'schedule_mode': mode}})


@student_required
def grades(request):
    return render(request, 'portal/grades.html', {'nav_section': 'study',
        'results': LearningResult.objects.filter(user=request.user).select_related('discipline'),
        'average': average_for(request.user),
        'deadlines': Deadline.objects.filter(user=request.user).select_related('discipline')})


@student_required
@require_POST
def deadline_toggle(request, pk):
    with transaction.atomic():
        deadline = get_object_or_404(Deadline.objects.select_for_update(), pk=pk, user=request.user)
        deadline.done = request.POST.get('done') == '1'
        deadline.save(update_fields=['done'])
        sync_task_notification(deadline)
    messages.success(request, 'Отметка об учебной задаче сохранена.')
    if request.POST.get('return_to') == 'tasks':
        return redirect(reverse('tasks') + f'#deadline-{pk}')
    return redirect('grades')


@student_required
def requests_list(request):
    tab = view_option(request, 'requests_tab', 'tab', 'active')
    items = StudentRequest.objects.filter(user=request.user)
    counts = {'active': items.exclude(status__in=['ready', 'rejected']).count(),
              'history': items.filter(status__in=['ready', 'rejected']).count(),
              'drafts': RequestDraft.objects.filter(user=request.user).count()}
    if tab == 'history':
        items = items.filter(status__in=['ready', 'rejected'])
    else:
        items = items.exclude(status__in=['ready', 'rejected'])
    return render(request, 'portal/requests.html', {'nav_section': 'requests',
        'student_requests': items, 'selected_tab': tab, 'counts': counts,
        'drafts': RequestDraft.objects.filter(user=request.user) if tab == 'drafts' else RequestDraft.objects.none(),
        'view_memory': {'requests_tab': tab}})


@student_required
def request_new(request):
    if request.method != 'GET':
        return HttpResponseNotAllowed(['GET'])
    kind = request.GET.get('kind', '')
    initial = {'kind': kind} if kind in dict(StudentRequest.Kind.choices) else {}
    return render(request, 'portal/request_form.html', {'nav_section': 'requests',
        'form': RequestForm(user=request.user, initial=initial)})


@student_required
@require_POST
def request_review(request):
    draft_form = RequestDraftForm(request.POST, user=request.user)
    if draft_form.is_valid():
        save_request_draft(request.user, draft_form)
    form = RequestForm(request.POST, user=request.user)
    if not form.is_valid():
        return render(request, 'portal/request_form.html', {'nav_section': 'requests', 'form': form}, status=422)
    if request.POST.get('edit') == '1':
        return render(request, 'portal/request_form.html', {'nav_section': 'requests', 'form': form})
    return render(request, 'portal/request_review.html', {'nav_section': 'requests', 'review_form': form,
        'payload': form.cleaned_data, 'kind_label': dict(StudentRequest.Kind.choices)[form.cleaned_data['kind']]})


@student_required
@require_POST
def request_submit(request):
    form = RequestForm(request.POST, user=request.user)
    if not form.is_valid():
        return render(request, 'portal/request_form.html', {'nav_section': 'requests', 'form': form}, status=422)
    payload = {k: form.cleaned_data[k] for k in ('kind', 'destination', 'text')}
    with transaction.atomic():
        lock_request_owner(request.user)
        item, created = StudentRequest.objects.get_or_create(idempotency_key=form.idempotency_key,
            defaults={'user': request.user, **payload})
        if item.user_id != request.user.pk:
            # Signed form tokens are owner-bound; defense in depth for database collisions.
            from django.http import Http404
            raise Http404
        if not created and any(getattr(item, k) != v for k, v in payload.items()):
            form.add_error(None, 'Эта форма уже отправлена с другими данными. Откройте новую заявку.')
            return render(request, 'portal/request_form.html', {'nav_section': 'requests', 'form': form}, status=409)
        if created:
            record_status(item, request.user, 'Обращение принято. Следите за статусом здесь.')
        RequestDraft.objects.filter(user=request.user, idempotency_key=form.idempotency_key).delete()
    messages.success(request, f'Заявка {item.number} отправлена.' if created else f'Заявка {item.number} уже была отправлена. Дубликат не создан.')
    return redirect('request_detail', pk=item.pk)


@student_required
def request_detail(request, pk):
    item = get_object_or_404(StudentRequest.objects.prefetch_related('history'), pk=pk, user=request.user)
    return render(request, 'portal/request_detail.html', {'nav_section': 'requests', 'item': item,
        'clarification_note': item.history.filter(status='clarify').last() if item.status == 'clarify' else None,
        'clarification_form': ClarificationForm() if item.status == 'clarify' else None})


@student_required
@require_POST
def request_clarify(request, pk):
    form = ClarificationForm(request.POST)
    with transaction.atomic():
        item = get_object_or_404(StudentRequest.objects.select_for_update(), pk=pk, user=request.user)
        if item.status != 'clarify':
            messages.info(request, 'Для этой заявки уточнение сейчас не требуется.')
            return redirect('request_detail', pk=pk)
        if not form.is_valid():
            return render(request, 'portal/request_detail.html', {'nav_section': 'requests', 'item': item,
                'clarification_form': form, 'clarification_note': item.history.filter(status='clarify').last()}, status=422)
        item.status = 'sent'
        item.save(update_fields=['status'])
        record_status(item, request.user, 'Ответ студента: ' + form.cleaned_data['text'])
    messages.success(request, 'Уточнение отправлено в деканат.')
    return redirect('request_detail', pk=pk)


@student_required
def notifications(request):
    items = Notification.objects.filter(user=request.user)
    kind = view_option(request, 'notifications_kind', 'kind', '')
    if kind in dict(Notification.Kind.choices):
        items = items.filter(kind=kind)
    else:
        kind = ''
    unread_only = view_option(request, 'notifications_unread', 'unread', '0') == '1'
    if unread_only:
        items = items.filter(read_at__isnull=True)
    return render(request, 'portal/notifications.html', {'nav_section': 'notifications', 'notifications': items,
        'kinds': Notification.Kind.choices, 'selected_kind': kind, 'unread_only': unread_only,
        'view_memory': {'notifications_kind': kind, 'notifications_unread': '1' if unread_only else '0'}})


@student_required
@require_GET
def notification_detail(request, pk):
    item = get_object_or_404(Notification, pk=pk, user=request.user)
    if item.read_at is None:
        Notification.objects.filter(pk=item.pk, user=request.user, read_at__isnull=True).update(read_at=timezone.now())
        item.refresh_from_db()
    return render(request, 'portal/notification_detail.html', {'nav_section': 'notifications', 'notification': item})


@student_required
@require_POST
def notification_read(request, pk):
    item = get_object_or_404(Notification, pk=pk, user=request.user)
    if not item.read_at:
        item.read_at = timezone.now()
        item.save(update_fields=['read_at'])
    messages.success(request, 'Уведомление отмечено прочитанным.')
    return redirect('notifications')


@student_required
@require_POST
def notifications_read_all(request):
    Notification.objects.filter(user=request.user, read_at__isnull=True).update(read_at=timezone.now())
    messages.success(request, 'Все уведомления отмечены прочитанными.')
    return redirect('notifications')


@student_required
def profile(request):
    return render(request, 'portal/profile.html', {'nav_section': 'more'})
