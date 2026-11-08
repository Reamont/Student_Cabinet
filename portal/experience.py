from .models import Idea, Notification, ViewPreference


VIEW_CHOICES = {
    'schedule_mode': ('today', 'week'),
    'requests_tab': ('active', 'drafts', 'history'),
    'notifications_kind': ('', *dict(Notification.Kind.choices)),
    'notifications_unread': ('0', '1'),
    'ideas_status': ('', *dict(Idea.Status.choices)),
    'ideas_sort': ('new', 'popular'),
    'semester_kind': ('', 'lessons', 'tasks', 'exams'),
}


def view_option(request, field, query_key, default):
    if not hasattr(request, '_view_preferences'):
        record = ViewPreference.objects.filter(user=request.user).first()
        request._view_preferences = record.values if record and isinstance(record.values, dict) else {}
    supplied = request.GET.get(query_key)
    if supplied in VIEW_CHOICES[field]:
        return supplied
    remembered = request._view_preferences.get(field)
    return remembered if remembered in VIEW_CHOICES[field] else default
