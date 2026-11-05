import uuid

from django import forms
from django.core import signing

from .models import StudentRequest


class RequestForm(forms.Form):
    kind = forms.ChoiceField(label='Тип обращения', choices=StudentRequest.Kind.choices)
    destination = forms.CharField(label='Место требования', max_length=200, required=False,
                                  help_text='Для справки по месту требования укажите организацию.')
    text = forms.CharField(label='Текст обращения', max_length=3000, required=False,
                           widget=forms.Textarea(attrs={'rows': 5}),
                           help_text='Для заявления опишите вопрос (не менее 10 символов). Не указывайте реальные персональные данные.')
    token = forms.CharField(widget=forms.HiddenInput)

    def __init__(self, *args, user, **kwargs):
        self.user = user
        super().__init__(*args, **kwargs)
        if not self.is_bound:
            self.fields['token'].initial = signing.dumps({'user': user.pk, 'key': str(uuid.uuid4())}, salt='request-form')

    def clean_token(self):
        token = self.cleaned_data['token']
        try:
            data = signing.loads(token, salt='request-form', max_age=3600)
            if data['user'] != self.user.pk:
                raise ValueError
            self.idempotency_key = uuid.UUID(data['key'])
        except (signing.BadSignature, ValueError, KeyError, TypeError):
            raise forms.ValidationError('Форма устарела. Откройте новую заявку; введённый текст можно скопировать.')
        return token

    def clean(self):
        data = super().clean()
        if data.get('kind') == StudentRequest.Kind.DESTINATION and not data.get('destination'):
            self.add_error('destination', 'Укажите место требования.')
        if data.get('kind') == StudentRequest.Kind.APPLICATION and len(data.get('text', '')) < 10:
            self.add_error('text', 'Опишите вопрос: не менее 10 символов.')
        return data


class ClarificationForm(forms.Form):
    text = forms.CharField(label='Ответ на уточнение', min_length=5, max_length=2000,
                           widget=forms.Textarea(attrs={'rows': 4}))
