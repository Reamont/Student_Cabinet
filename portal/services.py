from django.db import transaction
from django.contrib.auth import get_user_model
from .models import DeletedDraft, IdeaHistory, Notification, RequestDraft, RequestHistory, StudentRequest


def lock_request_owner(user):
    # Serialize draft saves with submission: a late autosave must not recreate
    # the draft after it has already become a submitted request.
    get_user_model().objects.select_for_update().get(pk=user.pk)


class DraftConflict(Exception):
    def __init__(self, draft):
        self.draft = draft
        super().__init__('Черновик изменён в другой вкладке. Твой текст сохранён в форме. Скопируй его перед открытием актуальной версии.')


def check_draft_version(draft, form):
    if draft and draft.updated_at.isoformat() != form.cleaned_data.get('draft_version', ''):
        if any(getattr(draft, field) != form.cleaned_data.get(field, '') for field in ('kind', 'destination', 'text')):
            raise DraftConflict(draft)


def set_draft_version(form, draft):
    data = form.data.copy()
    data['draft_version'] = draft.updated_at.isoformat()
    form.data = data


@transaction.atomic
def save_request_draft(user, form):
    lock_request_owner(user)
    if (StudentRequest.objects.filter(idempotency_key=form.idempotency_key).exists() or
            DeletedDraft.objects.filter(user=user, key=form.idempotency_key).exists()):
        return None
    draft = RequestDraft.objects.filter(user=user, idempotency_key=form.idempotency_key).first()
    check_draft_version(draft, form)
    payload = {field: form.cleaned_data.get(field, '') for field in ('kind', 'destination', 'text')}
    if draft is None:
        draft = RequestDraft.objects.create(user=user, idempotency_key=form.idempotency_key, **payload)
    elif any(getattr(draft, field) != value for field, value in payload.items()):
        for field, value in payload.items():
            setattr(draft, field, value)
        draft.save(update_fields=[*payload, 'updated_at'])
    return draft


@transaction.atomic
def record_status(item, actor, comment=''):
    RequestHistory.objects.create(request=item, status=item.status, actor=actor, comment=comment)
    Notification.objects.create(user=item.user, kind=Notification.Kind.REQUEST,
                                title=f'{item.number}: {item.get_status_display()}',
                                body=comment or 'Статус обращения обновлён. Откройте заявку, чтобы узнать подробности.',
                                related_request=item)


@transaction.atomic
def record_idea_update(item, actor):
    IdeaHistory.objects.create(idea=item, status=item.status, comment=item.response, actor=actor)
    recipients = {item.author_id, *item.supports.values_list('user_id', flat=True)}
    Notification.objects.bulk_create([
        Notification(user_id=user_id, kind='idea', title=f'{item.title}: {item.get_status_display()}',
                     body=item.response, related_idea=item)
        for user_id in recipients
    ])


@transaction.atomic
def sync_task_notification(task):
    title = f'Учебная задача: {task.title}'[:240]
    from django.utils import timezone
    Notification.objects.update_or_create(related_deadline=task, defaults={
        'user': task.user, 'kind': 'deadline', 'title': title,
        'body': f'Срок: {timezone.localtime(task.due):%d.%m.%Y %H:%M}. ' +
                ('Задача выполнена.' if task.done else 'Открой учебную задачу.'),
        'read_at': None, 'created_at': timezone.now()})
