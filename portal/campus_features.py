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

from .campus_forms import IdeaForm, StudyBlockForm
from .learning import free_windows, study_blocks, window_is_future, window_key
from .models import (Deadline, Idea, IdeaHistory, IdeaSupport, LearningResult, Lesson,
                     StudyBlock)
from .views import student_required
from .experience import view_option
from .plan_undo import read_plan_undo


def selected_day(value):
    try:
        day = date.fromisoformat(value)
        if abs((day - timezone.localdate()).days) > 3650:
            raise ValueError
        return day
    except (ValueError, TypeError):
        return timezone.localdate()


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
    if kind not in ('lessons', 'tasks', 'exams', 'plan'):
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
    if kind in ('', 'plan'):
        for block in study_blocks(request.student, first, last):
            if block.is_valid:
                events[block.date].append({'title': block.deadline.title, 'label': 'Личный план',
                    'detail': f'{block.start:%H:%M}–{block.end:%H:%M} · ' +
                              ('Задача выполнена' if block.deadline.done else 'Выбрано в «Плане Б»'),
                    'url': reverse('plan_b') + '?date=' + block.date.isoformat(), 'done': block.deadline.done})
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


def plan_b_context(request, day, error='', bound_form=None, bound_lesson=None):
    windows = free_windows(request.student, day)
    blocks = study_blocks(request.student, day, day)
    tasks = list(Deadline.objects.filter(user=request.user, done=False).select_related('discipline'))
    for window in windows:
        key = window_key(window['lesson'].pk, window['start'], window['end'])
        window['block'] = next((block for block in blocks if block.is_valid and
                              window_key(block.lesson_id, block.start, block.end) == key), None)
        window['future'] = window_is_future(day, window['start'])
        window['form'] = StudyBlockForm(user=request.user,
            auto_id=f"window-{window['lesson'].pk}-{window['start']:%H%M}-%s", initial={
            'start': window['start'].strftime('%H:%M'), 'end': window['end'].strftime('%H:%M'),
            'deadline': window['block'].deadline_id if window['block'] and not window['block'].deadline.done else None})
        if (bound_form is not None and bound_lesson == window['lesson'].pk and
                bound_form.cleaned_data.get('start') == window['start'] and
                bound_form.cleaned_data.get('end') == window['end']):
            bound_form.auto_id = window['form'].auto_id
            window['form'] = bound_form
        window['suggestions'] = tasks[:3]
    cancelled = Lesson.objects.filter(group=request.student.group, cancelled=True)
    future = list(cancelled.filter(date__gte=timezone.localdate()).order_by('date', 'start')[:5])
    past = list(cancelled.filter(date__lt=timezone.localdate()).order_by('-date', 'start')[:3])
    undo = read_plan_undo(request)
    return {'nav_section': 'schedule', 'day': day, 'windows': windows, 'error': error,
            'has_tasks': bool(tasks), 'known_cancellations': future + past,
            'undo': undo if undo and undo['date'] == day else None,
            'invalid_blocks': [block for block in blocks if not block.is_valid]}


@student_required
@require_GET
def plan_b(request):
    if request.GET.get('date'):
        day = selected_day(request.GET['date'])
    else:
        now = timezone.localtime()
        upcoming = (Lesson.objects.filter(group=request.student.group, cancelled=True)
                    .filter(Q(date__gt=now.date()) | Q(date=now.date(), start__gt=now.time()))
                    .order_by('date', 'start').values_list('date', flat=True).first())
        day = upcoming or now.date()
    return render(request, 'portal/plan_b.html', plan_b_context(request, day))


@student_required
@require_POST
def plan_pick(request, pk):
    with transaction.atomic():
        get_user_model().objects.select_for_update().get(pk=request.user.pk)
        lesson = get_object_or_404(Lesson.objects.select_for_update(), pk=pk, group=request.student.group)
        form = StudyBlockForm(request.POST, user=request.user)
        error = 'Проверь выбранную задачу и время окна.'
        if form.is_valid():
            start, end = form.cleaned_data['start'], form.cleaned_data['end']
            exists = any(window_key(w['lesson'].pk, w['start'], w['end']) == window_key(pk, start, end)
                         for w in free_windows(request.student, lesson.date))
            if exists and window_is_future(lesson.date, start):
                others = StudyBlock.objects.filter(user=request.user, date=lesson.date, start__lt=end, end__gt=start)
                others = others.exclude(lesson=lesson, start=start, end=end)
                if not others.exists():
                    StudyBlock.objects.update_or_create(user=request.user, lesson=lesson, date=lesson.date,
                        start=start, end=end, defaults={'deadline': form.cleaned_data['deadline']})
                    task = form.cleaned_data['deadline']
                    messages.success(request, f'«{task.title}» — в личном плане на {lesson.date:%d.%m}, '
                                             f'{start:%H:%M}–{end:%H:%M}. Выполнение задачи отмечается отдельно.')
                    return redirect(reverse('plan_b') + '?date=' + lesson.date.isoformat())
                error = 'На это время уже выбрана другая задача. Сначала убери её из плана.'
            else:
                error = 'Окно уже началось или расписание изменилось. Проверь доступное время заново.'
    return render(request, 'portal/plan_b.html', plan_b_context(request, lesson.date, error, form, lesson.pk), status=422)


@student_required
@require_POST
def plan_remove(request, pk):
    with transaction.atomic():
        get_user_model().objects.select_for_update().get(pk=request.user.pk)
        block = get_object_or_404(StudyBlock.objects.select_for_update(), pk=pk, user=request.user)
        day = block.date
        request.session['study_undo'] = {
            'user': request.user.pk, 'lesson': block.lesson_id, 'deadline': block.deadline_id,
            'date': day.isoformat(), 'start': block.start.isoformat(), 'end': block.end.isoformat(),
            'expires': timezone.now().timestamp() + 120,
        }
        block.delete()
    messages.success(request, 'Задача убрана из этого окна. Учебное обязательство сохранено.')
    return redirect(reverse('plan_b') + '?date=' + day.isoformat())


@student_required
@require_POST
def plan_restore(request):
    with transaction.atomic():
        get_user_model().objects.select_for_update().get(pk=request.user.pk)
        undo = read_plan_undo(request)
        if undo is None:
            messages.info(request, 'Вернуть задачу уже нельзя. При необходимости выбери её в доступном окне заново.')
            return redirect('plan_b')
        day, start, end = undo['date'], undo['start'], undo['end']
        exists = any(window_key(w['lesson'].pk, w['start'], w['end']) ==
                     window_key(undo['lesson'].pk, start, end) for w in free_windows(request.student, day))
        overlap = StudyBlock.objects.filter(user=request.user, date=day, start__lt=end, end__gt=start)
        same = overlap.filter(lesson=undo['lesson'], start=start, end=end, deadline=undo['task']).first()
        if same:
            request.session.pop('study_undo', None)
            messages.info(request, 'Задача уже есть в личном плане.')
            return redirect(reverse('plan_b') + '?date=' + day.isoformat())
        if not exists or not window_is_future(day, start) or undo['task'].done or overlap.exists():
            return render(request, 'portal/plan_b.html', plan_b_context(request, day,
                'Вернуть задачу не получилось: расписание, задача или личный план изменились. Выбери доступное окно.'), status=422)
        StudyBlock.objects.create(user=request.user, lesson=undo['lesson'], deadline=undo['task'],
                                  date=day, start=start, end=end)
        request.session.pop('study_undo', None)
    messages.success(request, f'«{undo["task"].title}» возвращена в личный план на {day:%d.%m}, {start:%H:%M}–{end:%H:%M}.')
    return redirect(reverse('plan_b') + '?date=' + day.isoformat())


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
