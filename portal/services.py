from django.db import transaction
from django.contrib.auth import get_user_model
from .models import Notification, RequestDraft, RequestHistory, StudentRequest


def lock_request_owner(user):
    # Serialize draft saves with submission: a late autosave must not recreate
    # the draft after it has already become a submitted request.
    get_user_model().objects.select_for_update().get(pk=user.pk)


@transaction.atomic
def save_request_draft(user, form):
    lock_request_owner(user)
    if StudentRequest.objects.filter(idempotency_key=form.idempotency_key).exists():
        return None
    draft, _ = RequestDraft.objects.update_or_create(
        user=user, idempotency_key=form.idempotency_key,
        defaults={field: form.cleaned_data.get(field, '') for field in ('kind', 'destination', 'text')})
    return draft


@transaction.atomic
def record_status(item, actor, comment=''):
    RequestHistory.objects.create(request=item, status=item.status, actor=actor, comment=comment)
    Notification.objects.create(user=item.user, kind=Notification.Kind.REQUEST,
                                title=f'{item.number}: {item.get_status_display()}',
                                body=comment or 'Статус обращения обновлён. Откройте заявку, чтобы узнать подробности.',
                                related_request=item)
