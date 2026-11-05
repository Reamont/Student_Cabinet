from django.contrib import admin
from django.contrib.auth.views import LogoutView
from django.urls import path
from portal import views

urlpatterns = [
    path('admin/', admin.site.urls),
    path('login/', views.StudentLoginView.as_view(), name='login'),
    path('logout/', LogoutView.as_view(), name='logout'),
    path('', views.dashboard, name='dashboard'),
    path('schedule/', views.schedule, name='schedule'),
    path('grades/', views.grades, name='grades'),
    path('deadlines/<int:pk>/done/', views.deadline_toggle, name='deadline_toggle'),
    path('requests/', views.requests_list, name='requests'),
    path('requests/new/', views.request_new, name='request_new'),
    path('requests/review/', views.request_review, name='request_review'),
    path('requests/submit/', views.request_submit, name='request_submit'),
    path('requests/<int:pk>/', views.request_detail, name='request_detail'),
    path('requests/<int:pk>/clarify/', views.request_clarify, name='request_clarify'),
    path('notifications/', views.notifications, name='notifications'),
    path('notifications/<int:pk>/', views.notification_detail, name='notification_detail'),
    path('notifications/<int:pk>/read/', views.notification_read, name='notification_read'),
    path('profile/', views.profile, name='profile'),
]
