"""
URL configuration for web project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/5.2/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""

from django.contrib import admin
from django.urls import path, include
from .views import (
    HomePageView,
    PaperSnitchLoginView,
    SignUpView,
    AnalyzePaperView,
    AnalysisStatusView,
    AnalysisCleanupView,
    ProfileView,
    AnalysisDetailView,
    BugReportView,
    CheckPastAnalysesView,
    AnnotatePaperView,
    ConferenceListView,
    ConferenceDetailView,
    ConferencePaperStatusView,
    ConferenceNodeStatisticsView,
    ActiveWorkflowsView,
    PaperDetailView,
    RerunWorkflowView,
    WorkflowStatusView,
    LatestWorkflowStatusView,
    WorkflowNodeDetailView,
    RerunSingleNodeView,
    RerunFromNodeView,
    BulkRerunWorkflowsView,
    BulkRerunPreviewView,
)

from .scraping_views import (
    StartScrapingView,
    ScrapingStatusView,
    ScrapingLogView,
    StopScrapingView,
    CreateAndScrapeConferenceView,
)

from django.contrib.auth import views as auth_views

urlpatterns = [
    path("", ConferenceListView.as_view(), name="home"),
    path("conferences/", ConferenceListView.as_view(), name="conference_list"),
    path("conference/<int:conference_id>/", ConferenceDetailView.as_view(), name="conference_detail"),
    path("conference/<int:conference_id>/paper-statuses/", ConferencePaperStatusView.as_view(), name="conference_paper_statuses"),
    path("conference/<int:conference_id>/node-statistics/", ConferenceNodeStatisticsView.as_view(), name="conference_node_statistics"),
    path("workflows/active/", ActiveWorkflowsView.as_view(), name="active_workflows"),
    path("conference/<int:conference_id>/bulk-rerun-workflows/", BulkRerunWorkflowsView.as_view(), name="bulk_rerun_workflows"),
    path("conference/<int:conference_id>/bulk-rerun-preview/", BulkRerunPreviewView.as_view(), name="bulk_rerun_preview"),
    path("paper/<int:paper_id>/", PaperDetailView.as_view(), name="paper_detail"),
    path("paper/<int:paper_id>/rerun-workflow/", RerunWorkflowView.as_view(), name="rerun_workflow"),
    path("workflow/status/<uuid:workflow_run_id>/", WorkflowStatusView.as_view(), name="workflow_status"),
    path("workflow/status/<int:paper_id>/latest/", LatestWorkflowStatusView.as_view(), name="latest_workflow_status"),
    path("workflow/node/<uuid:node_id>/", WorkflowNodeDetailView.as_view(), name="workflow_node_detail"),
    path("workflow/node/<uuid:node_id>/rerun/", RerunSingleNodeView.as_view(), name="rerun_single_node"),
    path("workflow/node/<uuid:node_id>/rerun-from/", RerunFromNodeView.as_view(), name="rerun_from_node"),
    
    # Scraping operations
    path("conference/create-and-scrape/", CreateAndScrapeConferenceView.as_view(), name="create_and_scrape_conference"),
    path("conference/<int:conference_id>/scrape/start/", StartScrapingView.as_view(), name="start_scraping"),
    path("conference/<int:conference_id>/scrape/status/", ScrapingStatusView.as_view(), name="scraping_status"),
    path("conference/<int:conference_id>/scrape/log/", ScrapingLogView.as_view(), name="scraping_log"),
    path("conference/<int:conference_id>/scrape/stop/", StopScrapingView.as_view(), name="stop_scraping"),
    
    path("accounts/", include("django.contrib.auth.urls")),
    path("accounts/login/", auth_views.LoginView.as_view(), name="login"),
    path("accounts/signup/", SignUpView.as_view(), name="signup"),
    # path("home/", HomePageView.as_view(), name="homepage"),
    path("profile/", ProfileView.as_view(), name="profile"),
    path(
        "analysis/<int:analysis_id>/",
        AnalysisDetailView.as_view(),
        name="analysis_detail",
    ),
    path("analyze/", AnalyzePaperView.as_view(), name="analyze"),
    path(
        "analyze/status/<str:task_id>/",
        AnalysisStatusView.as_view(),
        name="analysis_status",
    ),
    path(
        "analyze/cleanup/<str:task_id>/",
        AnalysisCleanupView.as_view(),
        name="analysis_cleanup",
    ),
    path(
        "analyze/check-past/",
        CheckPastAnalysesView.as_view(),
        name="check_past_analyses",
    ),
    path("report-bug/", BugReportView.as_view(), name="bug_report"),
    path(
        "annotate/<int:paper_id>/", AnnotatePaperView.as_view(), name="annotate_paper"
    ),
]
