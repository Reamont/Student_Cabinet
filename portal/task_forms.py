from django import forms
from django.db.models import Q

from .models import Deadline, Discipline


class TaskForm(forms.ModelForm):
    title = forms.CharField(label='Название задачи', min_length=3, max_length=240,
                            widget=forms.TextInput(attrs={'placeholder': 'Например, подготовить доклад'}))
    due = forms.DateTimeField(label='Срок', input_formats=['%Y-%m-%dT%H:%M'],
        widget=forms.DateTimeInput(format='%Y-%m-%dT%H:%M', attrs={'type': 'datetime-local'}),
        help_text='Дата и время по Москве. Если срок уже прошёл, задача будет просроченной.')

    class Meta:
        model = Deadline
        fields = ['title', 'discipline', 'due']
        labels = {'discipline': 'Дисциплина'}

    def __init__(self, *args, user, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['discipline'].queryset = Discipline.objects.filter(
            Q(lesson__group__profile__user=user) | Q(learningresult__user=user) |
            Q(deadline__user=user)).distinct().order_by('name')
        self.fields['discipline'].empty_label = 'Выбери дисциплину'
        self.fields['discipline'].help_text = 'Дисциплины из твоего расписания, результатов и учебных задач.'
