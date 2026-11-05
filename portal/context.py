from django.utils import timezone
from .models import Lesson, Notification, Profile


def common(request):
    profile = None
    unread = 0
    period = None
    if request.user.is_authenticated:
        profile = Profile.objects.filter(user=request.user).select_related('group').first()
        unread = Notification.objects.filter(user=request.user, read_at__isnull=True).count()
        if profile:
            qs = Lesson.objects.filter(group=profile.group, date__gte=timezone.localdate()).order_by('date')
            first, last = qs.first(), qs.last()
            if first:
                period = {'start': first.date, 'end': last.date}
    return {'profile': profile, 'unread_count': unread, 'today': timezone.localdate(),
            'now': timezone.localtime(), 'demo_period': period}
