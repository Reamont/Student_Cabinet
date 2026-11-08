from django.contrib import admin
from django.contrib.auth.views import LogoutView
from django.urls import path
from portal import views, request_features, campus_features

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
    path('requests/guide/', request_features.request_guide, name='request_guide'),
    path('requests/drafts/save/', request_features.draft_save, name='draft_save'),
    path('requests/drafts/<uuid:key>/', request_features.draft_edit, name='draft_edit'),
    path('requests/drafts/<uuid:key>/delete/', request_features.draft_delete, name='draft_delete'),
    path('requests/review/', views.request_review, name='request_review'),
    path('requests/submit/', views.request_submit, name='request_submit'),
    path('requests/<int:pk>/', views.request_detail, name='request_detail'),
    path('requests/<int:pk>/repeat/', request_features.request_repeat, name='request_repeat'),
    path('requests/<int:pk>/clarify/', views.request_clarify, name='request_clarify'),
    path('notifications/', views.notifications, name='notifications'),
    path('notifications/<int:pk>/', views.notification_detail, name='notification_detail'),
    path('notifications/<int:pk>/read/', views.notification_read, name='notification_read'),
    path('profile/', views.profile, name='profile'),
    path('help/', request_features.student_help, name='student_help'),
    path('semester/', campus_features.semester, name='semester'),
    path('plan-b/', campus_features.plan_b, name='plan_b'),
    path('plan-b/lessons/<int:pk>/choose/', campus_features.plan_pick, name='plan_pick'),
    path('plan-b/blocks/<int:pk>/remove/', campus_features.plan_remove, name='plan_remove'),
    path('ideas/', campus_features.ideas, name='ideas'),
    path('ideas/new/', campus_features.idea_new, name='idea_new'),
    path('ideas/<int:pk>/', campus_features.idea_detail, name='idea_detail'),
    path('ideas/<int:pk>/support/', campus_features.idea_support, name='idea_support'),
]
