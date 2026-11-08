import uuid

from django import forms
from django.core import signing





class IdeaForm(forms.Form):
    title = forms.CharField(label='Что предлагаешь улучшить?', min_length=5, max_length=140)
    description = forms.CharField(label='Как это поможет студентам?', min_length=15, max_length=2000,
                                   widget=forms.Textarea(attrs={'rows': 6}),
                                   help_text='Опиши проблему и своё решение. Используй только вымышленные примеры, без ФИО, контактов и личных обращений.')
    publish = forms.BooleanField(label='Опубликовать текст для других студентов. Автор будет виден только сотруднику деканата.')
    token = forms.CharField(widget=forms.HiddenInput)

    def __init__(self, *args, user, **kwargs):
        self.user = user
        super().__init__(*args, **kwargs)
        if not self.is_bound:
            self.fields['token'].initial = signing.dumps(
                {'user': user.pk, 'key': str(uuid.uuid4())}, salt='idea-form')

    def clean_token(self):
        token = self.cleaned_data['token']
        try:
            payload = signing.loads(token, salt='idea-form', max_age=3600)
            if payload['user'] != self.user.pk:
                raise ValueError
            self.idempotency_key = uuid.UUID(payload['key'])
        except (signing.BadSignature, ValueError, KeyError, TypeError):
            raise forms.ValidationError('Форма устарела. Открой новую форму; введённый текст можно скопировать.')
        return token
