import uuid
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core import signing
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from .forms import RequestForm
from .models import Group, Profile, RequestDraft, StudentRequest


@override_settings(
    SECURE_SSL_REDIRECT=False, ALLOWED_HOSTS=['testserver'],
    PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'],
    STORAGES={'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
              'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'}},
)
class RequestFeatureTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.a = get_user_model().objects.create_user('draft-a', password='Test-password-93724')
        cls.b = get_user_model().objects.create_user('draft-b', password='Test-password-57912')
        group = Group.objects.create(name='DRAFT-TEST')
        for user in [cls.a, cls.b]:
            Profile.objects.create(user=user, full_name=f'Студент {user.pk}', group=group,
                                   faculty='Тест', program='Тест', student_number=f'DRAFT-{user.pk}')
        cls.original = StudentRequest.objects.create(user=cls.a, kind='destination',
            destination='Вымышленная мастерская', text='Текст прошлого обращения', status='ready')
        cls.foreign = StudentRequest.objects.create(user=cls.b, kind='application', text='Чужое обращение')

    def setUp(self):
        self.client.force_login(self.a)

    def payload(self, **overrides):
        data = {'kind': 'application', 'text': 'Начало', 'destination': '',
                'token': RequestForm(user=self.a).fields['token'].initial}
        data.update(overrides)
        return data

    def save(self, payload):
        return self.client.post(reverse('draft_save'), payload, HTTP_ACCEPT='application/json')

    def test_partial_draft_saves_updates_and_survives_new_session(self):
        data = self.payload(text='Я')
        response = self.save(data)
        self.assertEqual(response.status_code, 200)
        data['draft_version'] = response.json()['draft_version']
        draft = RequestDraft.objects.get(user=self.a)
        data['text'] = 'Продолжаю черновик'
        self.assertTrue(self.save(data).json()['saved'])
        self.assertEqual(RequestDraft.objects.count(), 1)
        self.client.logout()
        self.client.login(username=self.a.username, password='Test-password-93724')
        response = self.client.get(reverse('draft_edit', args=[draft.idempotency_key]))
        self.assertContains(response, data['text'])
        self.assertEqual(StudentRequest.objects.count(), 2)
        self.assertContains(self.client.get(reverse('requests'), {'tab': 'drafts'}), 'Продолжить')

    def test_draft_accepts_missing_destination_but_review_still_validates_it(self):
        data = self.payload(kind='destination', text='')
        self.assertEqual(self.save(data).status_code, 200)
        response = self.client.post(reverse('request_review'), data)
        self.assertEqual(response.status_code, 422)
        self.assertContains(response, 'Укажите место требования.', status_code=422)
        self.assertEqual(StudentRequest.objects.count(), 2)

    def test_manual_save_works_without_javascript(self):
        response = self.client.post(reverse('draft_save'), self.payload(text='Я'))
        self.assertRedirects(response, reverse('requests') + '?tab=drafts')
        self.assertEqual(RequestDraft.objects.get().text, 'Я')

    def test_review_preserves_latest_snapshot_even_without_autosave(self):
        data = self.payload(text='Полный текст заявления')
        response = self.client.post(reverse('request_review'), data)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(RequestDraft.objects.get(user=self.a).text, data['text'])
        data['draft_version'] = response.context['review_form']['draft_version'].value()
        data['text'] += ' с исправлением'
        self.client.post(reverse('request_review'), {**data, 'edit': '1'})
        self.assertEqual(RequestDraft.objects.get(user=self.a).text, data['text'])

    def test_submission_clears_draft_and_late_autosave_cannot_restore_it(self):
        data = self.payload(text='Готовое заявление для отправки')
        self.save(data)
        self.assertEqual(self.client.post(reverse('request_submit'), data).status_code, 302)
        self.assertFalse(RequestDraft.objects.filter(user=self.a).exists())
        self.assertEqual(self.save(data).status_code, 409)
        self.assertFalse(RequestDraft.objects.filter(user=self.a).exists())
        self.client.post(reverse('request_submit'), data)
        self.assertEqual(StudentRequest.objects.filter(user=self.a, text=data['text']).count(), 1)

    def test_foreign_draft_is_hidden_from_list_edit_and_delete(self):
        draft = RequestDraft.objects.create(user=self.b, kind='application', text='Скрытый черновик')
        self.assertNotContains(self.client.get(reverse('requests'), {'tab': 'drafts'}), draft.text)
        self.assertEqual(self.client.get(reverse('draft_edit', args=[draft.idempotency_key])).status_code, 404)
        self.assertEqual(self.client.post(reverse('draft_delete', args=[draft.idempotency_key])).status_code, 404)
        self.assertTrue(RequestDraft.objects.filter(pk=draft.pk).exists())

    def test_draft_token_is_signed_owner_bound_and_rejects_injected_owner(self):
        data = self.payload(user_id=self.b.pk, status='ready', role='staff')
        self.assertEqual(self.save(data).status_code, 200)
        self.assertEqual(RequestDraft.objects.get().user_id, self.a.pk)
        self.client.force_login(self.b)
        self.assertEqual(self.save(data).status_code, 422)
        self.client.force_login(self.a)
        self.assertEqual(self.save({**data, 'token': 'tampered'}).status_code, 422)
        self.assertEqual(RequestDraft.objects.count(), 1)

    def test_draft_length_limits_and_expired_token_preserve_database(self):
        self.assertEqual(self.save(self.payload(text='x' * 3001)).status_code, 422)
        self.assertEqual(self.save(self.payload(destination='x' * 201)).status_code, 422)
        with patch('django.core.signing.time.time', return_value=1):
            data = self.payload()
        self.assertEqual(self.save(data).status_code, 422)
        self.assertFalse(RequestDraft.objects.exists())

    def test_own_draft_can_be_deleted_only_by_post(self):
        self.save(self.payload())
        draft = RequestDraft.objects.get()
        url = reverse('draft_delete', args=[draft.idempotency_key])
        self.assertEqual(self.client.get(url).status_code, 405)
        self.assertRedirects(self.client.post(url), reverse('requests') + '?tab=drafts')
        self.assertFalse(RequestDraft.objects.exists())

    def test_resuming_renews_token_but_preserves_submission_identity(self):
        draft = RequestDraft.objects.create(user=self.a, text='Черновик', kind='application')
        response = self.client.get(reverse('draft_edit', args=[draft.idempotency_key]))
        token = response.context['form'].fields['token'].initial
        payload = signing.loads(token, salt='request-form', max_age=3600)
        self.assertEqual(payload['user'], self.a.pk)
        self.assertEqual(uuid.UUID(payload['key']), draft.idempotency_key)

    def test_repeat_copies_only_input_into_fresh_form_and_does_not_send(self):
        response = self.client.get(reverse('request_repeat', args=[self.original.pk]))
        form = response.context['form']
        for field in ['kind', 'destination', 'text']:
            self.assertEqual(form.initial[field], getattr(self.original, field))
        token = signing.loads(form.fields['token'].initial, salt='request-form')
        self.assertNotEqual(uuid.UUID(token['key']), self.original.idempotency_key)
        self.assertEqual(StudentRequest.objects.count(), 2)
        self.assertFalse(RequestDraft.objects.exists())
        data = {k: form.initial[k] for k in ['kind', 'destination', 'text']}
        self.client.post(reverse('request_submit'), {**data, 'token': form.fields['token'].initial})
        new = StudentRequest.objects.exclude(pk__in=[self.original.pk, self.foreign.pk]).get()
        self.assertEqual(new.status, 'sent')
        self.original.refresh_from_db()
        self.assertEqual(self.original.status, 'ready')
        self.assertEqual(new.user_id, self.a.pk)

    def test_foreign_request_cannot_be_repeated(self):
        self.assertEqual(self.client.get(reverse('request_repeat', args=[self.foreign.pk])).status_code, 404)

    def test_guide_recommends_all_three_kinds_without_creating_requests(self):
        for params, kind in [({'purpose': 'question'}, 'application'),
                             ({'purpose': 'certificate', 'recipient': 'general'}, 'study'),
                             ({'purpose': 'certificate', 'recipient': 'organization'}, 'destination')]:
            response = self.client.get(reverse('request_guide'), params)
            self.assertContains(response, reverse('request_new') + '?kind=' + kind)
            response = self.client.get(reverse('request_new'), {'kind': kind})
            self.assertEqual(response.context['form'].initial['kind'], kind)
        self.assertEqual(StudentRequest.objects.count(), 2)
        self.assertFalse(RequestDraft.objects.exists())

    def test_guide_questions_and_unknown_choice_have_no_automatic_submission(self):
        response = self.client.get(reverse('request_guide'), {'purpose': 'certificate'})
        self.assertContains(response, 'Для чего нужна справка?')
        response = self.client.get(reverse('request_guide'), {'purpose': 'invalid', 'recipient': 'organization'})
        self.assertContains(response, 'С чем нужна помощь?')
        self.assertFalse(self.client.get(reverse('request_new'), {'kind': 'invalid'}).context['form'].initial)

    def test_help_search_actions_and_safe_output(self):
        response = self.client.get(reverse('student_help'))
        self.assertContains(response, 'Какую справку выбрать?')
        self.assertContains(response, reverse('grades'))
        self.assertContains(response, reverse('request_guide'))
        response = self.client.get(reverse('student_help'), {'q': 'ЗАДОЛЖЕННОСТЬ'})
        self.assertContains(response, 'Появилась академическая задолженность')
        self.assertNotContains(response, 'Как найти важное уведомление?')
        response = self.client.get(reverse('student_help'), {'q': '<script>alert(1)</script>'})
        self.assertNotContains(response, '<script>alert(1)</script>')
        self.assertContains(response, 'Такой ситуации пока нет')

    def test_new_pages_require_login_and_state_changes_require_csrf(self):
        client = Client()
        for name in ['student_help', 'request_guide', 'draft_save']:
            self.assertEqual(client.get(reverse(name)).status_code, 302)
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.a)
        self.assertEqual(client.post(reverse('draft_save'), self.payload()).status_code, 403)
        self.assertEqual(client.get(reverse('draft_save')).status_code, 405)

    def test_draft_user_text_is_escaped(self):
        draft = RequestDraft.objects.create(user=self.a, kind='application', text='<script>alert(1)</script>')
        for url in [reverse('requests') + '?tab=drafts', reverse('draft_edit', args=[draft.idempotency_key])]:
            self.assertNotContains(self.client.get(url), draft.text)

    def test_stale_tab_cannot_overwrite_draft_and_retains_text(self):
        data = self.payload(text='Первая версия заявления')
        initial = self.save(data).json()
        stale = {**data, 'draft_version': initial['draft_version'], 'text': 'Устаревший текст второй вкладки'}
        newer = {**data, 'draft_version': initial['draft_version'], 'text': 'Новый текст первой вкладки'}
        self.assertEqual(self.save(newer).status_code, 200)
        for route in ['draft_save', 'request_review', 'request_submit']:
            response = self.client.post(reverse(route), stale)
            self.assertEqual(response.status_code, 409)
            self.assertContains(response, stale['text'], status_code=409)
            self.assertContains(response, 'актуальный черновик', status_code=409)
        response = self.save(stale)
        self.assertEqual(response.status_code, 409)
        self.assertIn('conflict_url', response.json())
        self.assertEqual(RequestDraft.objects.get(user=self.a).text, newer['text'])
        self.assertFalse(StudentRequest.objects.filter(text=stale['text']).exists())

    def test_autosave_versions_advance_and_identical_retry_is_safe(self):
        data = self.payload(text='Первоначальный текст')
        first = self.save(data).json()['draft_version']
        self.assertEqual(self.save(data).json()['draft_version'], first)
        data.update(draft_version=first, text='Следующая версия текста')
        second = self.save(data).json()['draft_version']
        self.assertNotEqual(first, second)
        self.assertEqual(self.save(data).json()['draft_version'], second)
        data['text'] = 'Неподтверждённое изменение'
        self.assertEqual(self.save(data).status_code, 409)

    def test_reload_latest_draft_allows_edit_review_and_submit_without_js(self):
        data = self.payload(text='Исходное заявление')
        self.save(data)
        draft = RequestDraft.objects.get(user=self.a)
        form = self.client.get(reverse('draft_edit', args=[draft.idempotency_key])).context['form']
        payload = {field.name: field.value() or '' for field in form}
        payload['text'] = 'Заявление после открытия актуальной версии'
        response = self.client.post(reverse('request_review'), payload)
        self.assertEqual(response.status_code, 200)
        form = response.context['review_form']
        payload = {field.name: field.value() or '' for field in form}
        response = self.client.post(reverse('request_submit'), payload)
        self.assertEqual(response.status_code, 302)
        self.assertTrue(StudentRequest.objects.filter(user=self.a, text=payload['text']).exists())
        self.assertFalse(RequestDraft.objects.filter(pk=draft.pk).exists())

    def test_review_then_other_tab_edit_blocks_stale_final_submission(self):
        response = self.client.post(reverse('request_review'), self.payload(text='Текст на экране проверки'))
        form = response.context['review_form']
        reviewed = {field.name: field.value() or '' for field in form}
        self.assertEqual(self.save({**reviewed, 'text': 'Новый текст из другой вкладки'}).status_code, 200)
        self.assertEqual(self.client.post(reverse('request_submit'), reviewed).status_code, 409)
        self.assertEqual(RequestDraft.objects.get(user=self.a).text, 'Новый текст из другой вкладки')

    def test_new_forms_include_empty_version_and_resume_includes_current(self):
        form = self.client.get(reverse('request_new')).context['form']
        self.assertIn('draft_version', form.fields)
        self.assertFalse(form['draft_version'].value())
        self.save(self.payload())
        draft = RequestDraft.objects.get(user=self.a)
        form = self.client.get(reverse('draft_edit', args=[draft.idempotency_key])).context['form']
        self.assertEqual(form['draft_version'].value(), draft.updated_at.isoformat())
