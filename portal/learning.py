from datetime import datetime

from django.utils import timezone

from .models import Lesson, StudyBlock


def subtract_intervals(segments, occupied):
    for busy_start, busy_end in occupied:
        next_segments = []
        for start, end in segments:
            if busy_end <= start or busy_start >= end:
                next_segments.append((start, end))
            else:
                if start < busy_start:
                    next_segments.append((start, busy_start))
                if busy_end < end:
                    next_segments.append((busy_end, end))
        segments = next_segments
    return segments


def windows_from_lessons(lessons, day):
    busy = [(item.start, item.end) for item in lessons if not item.cancelled]
    claimed = []
    windows = []
    for lesson in sorted((item for item in lessons if item.cancelled), key=lambda x: (x.start, x.pk)):
        for start, end in subtract_intervals([(lesson.start, lesson.end)], busy + claimed):
            minutes = int((datetime.combine(day, end) - datetime.combine(day, start)).total_seconds() // 60)
            if minutes < 10:
                continue
            windows.append({'lesson': lesson, 'start': start, 'end': end, 'minutes': minutes})
            claimed.append((start, end))
    return windows


def free_windows(profile, day):
    lessons = list(Lesson.objects.filter(group=profile.group, date=day).select_related('discipline'))
    return windows_from_lessons(lessons, day)


def window_is_future(day, start):
    return timezone.make_aware(datetime.combine(day, start)) > timezone.now()


def window_key(lesson_id, start, end):
    return (lesson_id, start, end)


def study_blocks(profile, start, end):
    blocks = list(StudyBlock.objects.filter(user_id=profile.user_id, deadline__user_id=profile.user_id,
                                           date__range=(start, end))
                  .select_related('lesson__discipline', 'deadline__discipline'))
    dates = {block.date for block in blocks}
    lessons = Lesson.objects.filter(group=profile.group, date__in=dates).select_related('discipline')
    by_day = {}
    for lesson in lessons:
        by_day.setdefault(lesson.date, []).append(lesson)
    keys = {day: {window_key(w['lesson'].pk, w['start'], w['end'])
                  for w in windows_from_lessons(by_day.get(day, []), day)} for day in dates}
    for block in blocks:
        block.is_valid = (block.lesson.date == block.date and block.deadline.user_id == profile.user_id and
                          window_key(block.lesson_id, block.start, block.end) in keys[block.date])
    return blocks
