from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.contrib import messages
from django.views.decorators.http import require_GET, require_POST
from django.urls import reverse

from .forms import RequestDraftForm, RequestForm
from .guidance import student_guides
from django.db import transaction
from .models import DeletedDraft, RequestDraft, StudentRequest
from .services import lock_request_owner, save_request_draft
from .views import student_required


@student_required
@require_POST
def draft_save(request):
    form = RequestDraftForm(request.POST, user=request.user)
    wants_json = 'application/json' in request.headers.get('Accept', '')
    if not form.is_valid():
        if wants_json:
            return JsonResponse({'error': 'Не удалось сохранить черновик. Проверь поля формы.',
                                 'errors': form.errors.get_json_data()}, status=422)
        return render(request, 'portal/request_form.html', {
            'nav_section': 'requests', 'form': form}, status=422)
    draft = save_request_draft(request.user, form)
    if draft is None:
        if wants_json:
            return JsonResponse({'error': 'Эта форма уже отправлена или черновик удалён. Открой новую заявку.'}, status=409)
        messages.info(request, 'Эта форма уже отправлена или черновик удалён. Черновик не создан.')
        return redirect('requests')
    if wants_json:
        return JsonResponse({'saved': True, 'updated_at': draft.updated_at.isoformat()})
    messages.success(request, 'Черновик сохранён. Продолжить можно во вкладке «Черновики» раздела «Заявки».')
    return redirect(reverse('requests') + '?tab=drafts')


@student_required
@require_GET
def draft_edit(request, key):
    draft = get_object_or_404(RequestDraft, idempotency_key=key, user=request.user)
    return render(request, 'portal/request_form.html', {
        'nav_section': 'requests', 'draft': draft,
        'form': RequestForm(user=request.user, draft_key=draft.idempotency_key,
                            initial={k: getattr(draft, k) for k in ('kind', 'destination', 'text')})})


@student_required
@require_POST
def draft_delete(request, key):
    with transaction.atomic():
        lock_request_owner(request.user)
        draft = get_object_or_404(RequestDraft, idempotency_key=key, user=request.user)
        DeletedDraft.objects.get_or_create(user=request.user, key=draft.idempotency_key)
        draft.delete()
    messages.success(request, 'Черновик удалён.')
    return redirect(reverse('requests') + '?tab=drafts')


@student_required
@require_GET
def request_repeat(request, pk):
    item = get_object_or_404(StudentRequest, pk=pk, user=request.user)
    return render(request, 'portal/request_form.html', {
        'nav_section': 'requests', 'repeat_source': item,
        'form': RequestForm(user=request.user,
                            initial={k: getattr(item, k) for k in ('kind', 'destination', 'text')})})


@student_required
@require_GET
def request_guide(request):
    purpose = request.GET.get('purpose', '')
    recipient = request.GET.get('recipient', '')
    kind = None
    explanation = ''
    if purpose == 'question':
        kind = StudentRequest.Kind.APPLICATION
        explanation = 'Для учебного вопроса, исправления сведений или обращения к сотруднику подойдёт заявление в деканат.'
    elif purpose == 'certificate':
        if recipient == 'organization':
            kind = StudentRequest.Kind.DESTINATION
            explanation = 'Укажи название организации, для которой нужна справка. Оно будет видно при проверке обращения.'
        elif recipient == 'general':
            kind = StudentRequest.Kind.STUDY
            explanation = 'Справка об обучении подойдёт, чтобы подтвердить статус студента без указания конкретной организации.'
    else:
        purpose = ''
    return render(request, 'portal/request_guide.html', {
        'nav_section': 'requests', 'purpose': purpose, 'kind': kind,
        'kind_label': dict(StudentRequest.Kind.choices).get(kind), 'explanation': explanation})


@student_required
@require_GET
def student_help(request):
    query = request.GET.get('q', '').strip()[:120]
    guides = student_guides()
    if query:
        guides = [g for g in guides if query.casefold() in (g['title'] + ' ' + g['body']).casefold()]
    return render(request, 'portal/student_help.html', {
        'nav_section': 'more', 'guides': guides, 'query': query})
