from django.urls import path
from . import views

urlpatterns = [
    path('', views.home, name='home'),
    path('upload/', views.upload_document, name='upload_document'),
    path('documents/', views.document_list, name='document_list'),
    path('document/<int:pk>/annotate/', views.annotate_document, name='annotate_document'),
    path('document/<int:pk>/annotations/', views.get_annotations, name='get_annotations'),
    path('document/<int:pk>/annotations/save/', views.save_annotation, name='save_annotation'),
    path('document/<int:pk>/annotations/<int:annotation_id>/delete/', views.delete_annotation, name='delete_annotation'),
    path('document/<int:pk>/export/', views.export_annotations, name='export_annotations'),
    path('document/<int:pk>/retry/', views.retry_conversion, name='retry_conversion'),
    path('category/create/', views.create_category, name='create_category'),
]
