from django.urls import path

from . import views

app_name = "demo"

urlpatterns = [
    path("", views.DemoLandingView.as_view(), name="landing"),
    path("upload/", views.DemoUploadView.as_view(), name="upload"),
    path("replay/<int:scenario_id>/", views.DemoReplayView.as_view(), name="replay"),
    path("api/timeline/<int:scenario_id>/", views.DemoTimelineView.as_view(), name="timeline"),
    path("report/<uuid:run_id>/", views.DemoReportView.as_view(), name="report"),
    path("paper/<int:paper_id>/html/", views.DemoPaperHtmlView.as_view(), name="paper_html"),
]
