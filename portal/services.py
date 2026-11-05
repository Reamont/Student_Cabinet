from django.db import transaction
from .models import Notification, RequestHistory


@transaction.atomic
def record_status(item, actor, comment=''):
    RequestHistory.objects.create(request=item, status=item.status, actor=actor, comment=comment)
    Notification.objects.create(user=item.user, kind=Notification.Kind.REQUEST,
                                title=f'{item.number}: {item.get_status_display()}',
                                body=comment or 'Статус обращения обновлён. Откройте заявку, чтобы узнать подробности.',
                                related_request=item)
