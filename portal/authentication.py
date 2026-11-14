from django import forms
from django.contrib.auth import authenticate, get_user_model
from django.contrib.auth.backends import ModelBackend
from django.contrib.auth.forms import AuthenticationForm


class EmailBackend(ModelBackend):
    def authenticate(self, request, username=None, password=None, email=None, **kwargs):
        # Django Admin keeps its standard username login.
        if email is None:
            return super().authenticate(request, username=username, password=password, **kwargs)
        User = get_user_model()
        try:
            user = User.objects.get(email__iexact=email.strip())
        except (User.DoesNotExist, User.MultipleObjectsReturned):
            User().set_password(password)
            return None
        if user.check_password(password) and self.user_can_authenticate(user):
            return user


class EmailAuthenticationForm(AuthenticationForm):
    # Keep the standard field name for password managers and login throttling.
    username = forms.EmailField(label='Электронная почта', max_length=254,
        widget=forms.EmailInput(attrs={'autofocus': True, 'autocomplete': 'username',
                                      'placeholder': 'student@example.ru'}))
    error_messages = {
        'invalid_login': 'Неверная почта или пароль.',
        'inactive': 'Неверная почта или пароль.',
    }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['username'].max_length = 254
        self.fields['username'].widget.attrs['maxlength'] = 254

    def clean(self):
        email = self.cleaned_data.get('username')
        password = self.cleaned_data.get('password')
        if email and password:
            self.user_cache = authenticate(self.request, email=email, password=password)
            if self.user_cache is None:
                raise self.get_invalid_login_error()
            self.confirm_login_allowed(self.user_cache)
        return self.cleaned_data
