from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from .models import Group, Profile, LoginThrottle


@override_settings(PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'],
    STORAGES={'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'}})
class EmailLoginTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user('student-login', email='student@example.test', password='Test-password-123')
        group = Group.objects.create(name='EMAIL')
        Profile.objects.create(user=self.user, group=group, full_name='Студент', faculty='Тест', program='Тест', student_number='EMAIL')

    def login(self, email, password='Test-password-123'):
        return self.client.post(reverse('login'), {'username': email, 'password': password})

    def test_email_login_normalizes_case_and_whitespace(self):
        self.assertEqual(self.login(' Student@EXAMPLE.test ').status_code, 302)
        self.assertEqual(int(self.client.session['_auth_user_id']), self.user.pk)

    def test_username_is_rejected(self):
        self.assertEqual(self.login(self.user.username).status_code, 200)
        self.assertNotIn('_auth_user_id', self.client.session)

    def test_email_shaped_username_cannot_bypass_email_lookup(self):
        get_user_model().objects.create_user('other@example.test', email='actual@example.test', password='Test-password-123')
        self.login('other@example.test')
        self.assertNotIn('_auth_user_id', self.client.session)

    def test_duplicate_emails_fail_closed(self):
        get_user_model().objects.create_user('duplicate', email='STUDENT@example.test', password='Test-password-123')
        self.assertEqual(self.login(self.user.email).status_code, 200)
        self.assertNotIn('_auth_user_id', self.client.session)

    def test_inactive_wrong_password_unknown_email_have_same_error(self):
        responses = [self.login(self.user.email, 'wrong'), self.login('unknown@example.test')]
        self.user.is_active = False
        self.user.save()
        responses.append(self.login(self.user.email))
        for response in responses:
            self.assertContains(response, 'Неверная почта или пароль.')
            self.assertNotIn('_auth_user_id', self.client.session)

    def test_account_limit_uses_email_case_insensitively_and_resets_on_success(self):
        for i in range(10):
            self.login('STUDENT@example.test' if i % 2 else self.user.email, 'wrong')
        self.assertEqual(self.login(self.user.email).status_code, 429)
        LoginThrottle.objects.all().delete()
        self.login(self.user.email, 'wrong')
        self.assertEqual(self.login(self.user.email).status_code, 302)
        self.assertTrue(LoginThrottle.objects.filter(failures=0).exists())

    def test_email_field_and_password_controls_render(self):
        response = self.client.get(reverse('login'))
        self.assertContains(response, 'type="email"')
        self.assertContains(response, 'Электронная почта')
        self.assertContains(response, 'data-password-toggle')
