from django.urls import path
from . import views

urlpatterns = [
    path("", views.home, name="home"),
    path("upload/", views.upload_document, name="upload_document"),
    path("documents/", views.document_list, name="document_list"),
    path(
        "document/<int:pk>/annotate/", views.annotate_document, name="annotate_document"
    ),
    path(
        "document/<int:pk>/annotations/", views.get_annotations, name="get_annotations"
    ),
    path(
        "document/<int:pk>/annotations/save/",
        views.save_annotation,
        name="save_annotation",
    ),
    path(
        "document/<int:pk>/annotations/<int:annotation_id>/delete/",
        views.delete_annotation,
        name="delete_annotation",
    ),
    path(
        "document/<int:pk>/annotations/<int:annotation_id>/update/",
        views.update_annotation,
        name="update_annotation",
    ),
    path(
        "document/<int:pk>/export/", views.export_annotations, name="export_annotations"
    ),
    path("document/<int:pk>/retry/", views.retry_conversion, name="retry_conversion"),
    path("document/<int:pk>/delete/", views.delete_document, name="delete_document"),
    path("category/suggest/", views.suggest_categories, name="suggest_categories"),
    # TODO deprecated endpoint, remove in future releases
    path("category/create/", views.create_category, name="create_category"),
]
