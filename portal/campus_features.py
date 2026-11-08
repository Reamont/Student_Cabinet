import calendar
from collections import Counter, defaultdict
from datetime import date, timedelta

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import Count, Exists, Max, Min, OuterRef, Q
from django.http import Http404, HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

from .campus_forms import IdeaForm
from .models import (Deadline, Idea, IdeaHistory, IdeaSupport, LearningResult, Lesson,
                     Notification)
from .views import student_required
from .experience import view_option




def month_start(value):
    try:
        day = date.fromisoformat(value + '-01')
        if abs((day - timezone.localdate()).days) > 3650:
            raise ValueError
        return day
    except (ValueError, TypeError):
        return timezone.localdate().replace(day=1)


@student_required
@require_GET
def semester(request):
    first = month_start(request.GET.get('month', ''))
    last = first.replace(day=calendar.monthrange(first.year, first.month)[1])
    kind = view_option(request, 'semester_kind', 'kind', '')
    if kind not in ('lessons', 'tasks', 'exams'):
        kind = ''
    events = defaultdict(list)
    lessons = list(Lesson.objects.filter(group=request.student.group, date__range=(first, last))
                   .select_related('discipline'))
    by_day = defaultdict(list)
    for lesson in lessons:
        by_day[lesson.date].append(lesson)
    if kind in ('', 'lessons'):
        for day, items in by_day.items():
            cancelled = sum(item.cancelled for item in items)
            events[day].append({'title': f'Занятия: {len(items) - cancelled} · отмены: {cancelled}',
                'label': 'Расписание', 'url': reverse('schedule') + '?date=' + day.isoformat(),
                'detail': ' · '.join(item.discipline.name for item in items), 'done': False})
    tasks = list(Deadline.objects.filter(user=request.user, due__date__range=(first, last))
                 .select_related('discipline'))
    if kind in ('', 'tasks'):
        for task in tasks:
            day = timezone.localtime(task.due).date()
            late = not task.done and task.due < timezone.now()
            events[day].append({'title': task.title, 'label': 'Учебная задача',
                'detail': task.discipline.name + ' · ' + timezone.localtime(task.due).strftime('%H:%M') +
                          (' · Выполнено' if task.done else ' · Срок прошёл' if late else ' · Предстоит'),
                'url': reverse('tasks') + f'#deadline-{task.pk}', 'done': task.done})
    results = list(LearningResult.objects.filter(user=request.user).select_related('discipline'))
    if kind in ('', 'exams'):
        for result in results:
            if result.exam_date and first <= result.exam_date <= last:
                events[result.exam_date].append({'title': result.discipline.name, 'label': 'Экзамен',
                    'detail': result.get_state_display(), 'url': reverse('grades') + f'#result-{result.pk}',
                    'done': result.state in ('grade', 'pass')})
    weeks = [[{'date': day, 'in_month': day.month == first.month, 'count': len(events.get(day, []))}
              for day in week] for week in calendar.Calendar().monthdatescalendar(first.year, first.month)]
    period = Lesson.objects.filter(group=request.student.group).aggregate(start=Min('date'), end=Max('date'))
    counts = Counter(result.state for result in results)
    return render(request, 'portal/semester.html', {
        'nav_section': 'study', 'month': first, 'prev_month': (first - timedelta(days=1)).replace(day=1),
        'next_month': (last + timedelta(days=1)), 'weeks': weeks, 'selected_kind': kind,
        'days': [{'date': day, 'events': items} for day, items in sorted(events.items())],
        'period': period, 'done_tasks': sum(task.done for task in tasks), 'total_tasks': len(tasks),
        'graded': counts['grade'], 'passed': counts['pass'], 'debts': counts['debt'],
        'view_memory': {'semester_kind': kind},
    })












def idea_queryset(user):
    return Idea.objects.annotate(support_count=Count('supports', distinct=True),
        is_supported=Exists(IdeaSupport.objects.filter(idea_id=OuterRef('pk'), user=user)))


@student_required
@require_GET
def ideas(request):
    items = idea_queryset(request.user)
    status = view_option(request, 'ideas_status', 'status', '')
    if status in dict(Idea.Status.choices):
        items = items.filter(status=status)
    else:
        status = ''
    sort = view_option(request, 'ideas_sort', 'sort', 'new')
    popular = sort == 'popular'
    if popular:
        items = items.order_by('-support_count', '-created_at', '-pk')
    return render(request, 'portal/ideas.html', {'nav_section': 'more', 'ideas': items,
        'statuses': Idea.Status.choices, 'selected_status': status, 'popular': popular,
        'view_memory': {'ideas_status': status, 'ideas_sort': sort}})


@student_required
def idea_new(request):
    if request.method not in ('GET', 'POST'):
        from django.http import HttpResponseNotAllowed
        return HttpResponseNotAllowed(['GET', 'POST'])
    form = IdeaForm(request.POST if request.method == 'POST' else None, user=request.user)
    status = 200
    if request.method == 'POST':
        if form.is_valid():
            with transaction.atomic():
                item, created = Idea.objects.get_or_create(idempotency_key=form.idempotency_key, defaults={
                    'author': request.user, 'title': form.cleaned_data['title'],
                    'description': form.cleaned_data['description']})
                if item.author_id != request.user.pk:
                    raise Http404
                if not created and (item.title != form.cleaned_data['title'] or
                                    item.description != form.cleaned_data['description']):
                    form.add_error(None, 'Эта форма уже опубликована с другим текстом. Открой новую форму.')
                    status = 409
                else:
                    if created:
                        IdeaHistory.objects.create(idea=item, status='new', comment='Предложение опубликовано.',
                                                   actor=request.user)
                    messages.success(request, 'Предложение опубликовано.' if created else 'Предложение уже опубликовано. Дубликат не создан.')
                    return redirect('idea_detail', pk=item.pk)
        else:
            status = 422
    return render(request, 'portal/idea_form.html', {'nav_section': 'more', 'form': form}, status=status)


@student_required
@require_GET
def idea_detail(request, pk):
    item = get_object_or_404(idea_queryset(request.user).prefetch_related('history'), pk=pk)
    return render(request, 'portal/idea_detail.html', {'nav_section': 'more', 'idea': item,
                                                    'is_owner': item.author_id == request.user.pk})


@student_required
@require_POST
def idea_support(request, pk):
    item = get_object_or_404(Idea, pk=pk)
    if item.author_id == request.user.pk:
        return HttpResponseForbidden('Свои предложения поддерживать нельзя.')
    action = request.POST.get('support')
    if action not in ('1', '0'):
        return HttpResponseForbidden('Выбери действие поддержки.')
    with transaction.atomic():
        get_user_model().objects.select_for_update().get(pk=request.user.pk)
        if action == '1':
            IdeaSupport.objects.get_or_create(idea=item, user=request.user)
        else:
            IdeaSupport.objects.filter(idea=item, user=request.user).delete()
    return redirect('idea_detail', pk=item.pk)
