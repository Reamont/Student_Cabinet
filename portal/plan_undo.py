from datetime import date, time

from django.utils import timezone

from .models import Deadline, Lesson


def read_plan_undo(request):
    value = request.session.get('study_undo')
    if not isinstance(value, dict) or value.get('user') != request.user.pk:
        return None
    try:
        expires = float(value['expires'])
        if expires <= timezone.now().timestamp():
            return None
        day = date.fromisoformat(value['date'])
        start, end = time.fromisoformat(value['start']), time.fromisoformat(value['end'])
        lesson = Lesson.objects.filter(pk=value['lesson'], group=request.student.group).first()
        task = Deadline.objects.filter(pk=value['deadline'], user=request.user).first()
        if lesson is None or task is None:
            return None
        return {'lesson': lesson, 'task': task, 'date': day, 'start': start, 'end': end}
    except (KeyError, ValueError, TypeError):
        return None
