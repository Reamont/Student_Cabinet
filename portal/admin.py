from django import forms
from django.contrib import admin
from django.utils import timezone
from .models import StudentRequest
from .services import record_status


class StatusForm(forms.ModelForm):
    comment = forms.CharField(label='Комментарий для студента', max_length=2000,
                              required=False, widget=forms.Textarea)

    class Meta:
        model = StudentRequest
        fields = ['status']

    def clean(self):
        data = super().clean()
        if data.get('status') in ('clarify', 'rejected') and not data.get('comment', '').strip():
            self.add_error('comment', 'При уточнении или отказе объясните причину студенту.')
        return data


@admin.register(StudentRequest)
class RequestAdmin(admin.ModelAdmin):
    form = StatusForm
    fields = ['user', 'kind', 'destination', 'text', 'status', 'comment', 'created_at', 'status_history']
    readonly_fields = ['user', 'kind', 'destination', 'text', 'created_at', 'status_history']
    list_display = ['number', 'user', 'kind', 'status', 'created_at']
    list_filter = ['status', 'kind']
    search_fields = ['user__username', 'destination']
    actions = None

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    @admin.display(description='История')
    def status_history(self, obj):
        return '\n'.join(f'{timezone.localtime(h.created_at):%d.%m.%Y %H:%M} · {h.get_status_display()} · {h.comment}' for h in obj.history.all())

    def save_model(self, request, obj, form, change):
        old_status = StudentRequest.objects.select_for_update().get(pk=obj.pk).status
        super().save_model(request, obj, form, change)
        if obj.status != old_status or form.cleaned_data.get('comment'):
            record_status(obj, request.user, form.cleaned_data.get('comment', ''))


admin.site.site_header = 'Пульс Кампуса · Деканат'
admin.site.site_title = 'Конкурсный прототип'
admin.site.index_title = 'Работа с обращениями'
