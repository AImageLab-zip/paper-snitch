from django.shortcuts import render, redirect, get_object_or_404
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods
from django.contrib.auth.decorators import login_required
from django.core.files.base import ContentFile
from django.utils import timezone
from django.contrib import messages
import subprocess
import os
import json
from pathlib import Path
import shutil
import struct

from .models import Document, Annotation, AnnotationCategory
from .forms import DocumentUploadForm
from .utils import get_embedding, cosine_similarity

import logging

logger = logging.getLogger(__name__)


def home(request):
    """Home page showing all documents"""
    documents = Document.objects.all()
    return render(request, "annotator/home.html", {"documents": documents})


def upload_document(request):
    """Upload and convert PDF document"""
    if request.method == "POST":
        form = DocumentUploadForm(request.POST, request.FILES)
        if form.is_valid():
            document = form.save()

            # Convert PDF to HTML
            try:
                document.conversion_status = "processing"
                document.save()
                convert_pdf_to_html(document)
                messages.success(
                    request,
                    f'Document "{document.title}" uploaded and converted successfully!',
                )
                return redirect("annotate_document", pk=document.pk)
            except Exception as e:
                document.conversion_status = "failed"
                document.conversion_error = str(e)
                document.save()
                messages.error(request, f"Error converting PDF: {str(e)}")
                return redirect("document_list")
    else:
        form = DocumentUploadForm()

    return render(request, "annotator/upload.html", {"form": form})


def convert_pdf_to_html(document):
    """Convert PDF to HTML using pdf2htmlEX via Docker (with fallback to pypdf)"""
    from django.conf import settings

    # Get paths
    pdf_path = document.pdf_file.path
    output_dir = os.path.join(settings.MEDIA_ROOT, "htmls")
    os.makedirs(output_dir, exist_ok=True)

    host_project_path = os.environ.get("HOST_PROJECT_PATH")

    # Generate output filename
    base_name = Path(pdf_path).stem.replace(" ", "_")
    output_filename = f"{base_name}_{document.pk}.html"
    output_path = os.path.join(output_dir, output_filename)

    # Try pdf2htmlEX via Docker first (preserves style)
    docker_available = shutil.which("docker") is not None
    if docker_available:
        try:
            rel_pdf_path = os.path.relpath(pdf_path, settings.BASE_DIR)
            rel_output_dir = os.path.relpath(output_dir, settings.BASE_DIR)
            # Get absolute paths
            host_pdf_path = os.path.join(host_project_path, rel_pdf_path)
            pdf_filename = os.path.basename(pdf_path)

            host_output_dir = os.path.join(host_project_path, rel_output_dir)
            host_pdf_dir = os.path.dirname(host_pdf_path)
            pdf_filename = os.path.basename(pdf_path)

            DOCKER_IMAGE = (
                "pdf2htmlex/pdf2htmlex:0.18.8.rc2-master-20200820-ubuntu-20.04-x86_64"
            )
            cmd = [
                "docker",
                "run",
                "--rm",
                "-v",
                f"{host_pdf_dir}:/pdf:ro",
                "-v",
                f"{host_output_dir}:/output",
                DOCKER_IMAGE,
                "--process-outline",
                "0",
                "--zoom",
                "1.7",
                "--dest-dir",
                "/output",
                f"/pdf/{pdf_filename}",
                output_filename,
            ]

            result = subprocess.run(
                cmd, capture_output=True, text=True, check=True, timeout=120
            )

            # Update document with HTML file path
            relative_path = os.path.join("htmls", output_filename)
            document.html_file = relative_path
            document.converted_at = timezone.now()
            document.conversion_status = "success"
            document.conversion_error = None
            document.save()

            return output_path

        except Exception as e:
            error_msg = (
                f"Docker conversion failed!\nSTDOUT: {e.stdout}\nSTDERR: {e.stderr}"
            )
            logger.error(error_msg)
            print(error_msg)  # Stampalo anche a video per debug immediato

            # Salva l'errore nel database per debug futuro
            document.conversion_status = "failed"
            document.conversion_error = (
                e.stderr[:500] if e.stderr else "Unknown Docker Error"
            )
            document.save()

            raise RuntimeError(f"PDF Conversion Failed: {e.stderr}")
    # Fallback to pypdf if pdf2htmlEX not available or failed
    try:
        from pypdf import PdfReader

        pdf_reader = PdfReader(pdf_path)

        # Create HTML content
        html_parts = [
            "<!DOCTYPE html>",
            "<html>",
            "<head>",
            '<meta charset="UTF-8">',
            '<meta name="viewport" content="width=device-width, initial-scale=1.0">',
            "<title>" + document.title + "</title>",
            "<style>",
            "body { font-family: Arial, sans-serif; margin: 20px; background: #f5f5f5; }",
            ".page { background: white; margin: 20px auto; padding: 40px; max-width: 850px; box-shadow: 0 2px 8px rgba(0,0,0,0.1); position: relative; min-height: 800px; }",
            ".page-number { position: absolute; top: 10px; right: 10px; color: #999; font-size: 12px; }",
            ".text-block { margin: 8px 0; line-height: 1.5; }",
            ".warning { background: #fff3cd; padding: 10px; margin: 10px 0; border-left: 4px solid #ffc107; }",
            "</style>",
            "</head>",
            "<body>",
            '<div class="warning">⚠️ Note: This document was converted using basic text extraction. Install Docker and pull bwits/pdf2htmlex image for better style preservation.</div>',
        ]

        # Process each page
        for page_num, page in enumerate(pdf_reader.pages):
            html_parts.append(f'<div class="page" id="page-{page_num + 1}">')
            html_parts.append(
                f'<div class="page-number">Page {page_num + 1} of {len(pdf_reader.pages)}</div>'
            )

            text = page.extract_text()

            if text:
                paragraphs = text.split("\n")
                for para in paragraphs:
                    para = para.strip()
                    if para:
                        para = (
                            para.replace("&", "&amp;")
                            .replace("<", "&lt;")
                            .replace(">", "&gt;")
                        )
                        html_parts.append(f'<div class="text-block">{para}</div>')
            else:
                html_parts.append(
                    '<div class="text-block" style="color: #999; font-style: italic;">No text extracted from this page</div>'
                )

            html_parts.append("</div>")

        html_parts.extend(["</body>", "</html>"])

        # Write HTML file
        with open(output_path, "w", encoding="utf-8") as f:
            f.write("\n".join(html_parts))

        # Update document
        relative_path = os.path.join("htmls", output_filename)
        document.html_file = relative_path
        document.converted_at = timezone.now()
        document.conversion_status = "success"
        document.conversion_error = None
        document.save()

        return output_path
    except Exception as e:
        document.conversion_status = "failed"
        document.conversion_error = str(e)
        document.save()
        raise Exception(f"PDF to HTML conversion failed: {str(e)}")


@login_required
def annotate_document(request, pk):
    """View for annotating a document"""
    document = get_object_or_404(Document, pk=pk)

    if not document.html_file:
        messages.error(request, "Document has not been converted to HTML yet.")
        return redirect("home")

    # Get only this user's annotations for this document
    annotations = document.annotations.filter(user=request.user)

    # Enrich annotations with category objects
    annotations_with_categories = []
    for ann in annotations:
        annotations_with_categories.append(
            {
                "id": ann.id,
                "category_name": ann.category.name,
                "category_color": ann.category.color,
                "selected_text": ann.selected_text,
                "created_at": ann.created_at,
                "position_data": (
                    json.dumps(ann.position_data) if ann.position_data else "{}"
                ),
            }
        )

    # Get all categories organized hierarchically
    parent_categories = AnnotationCategory.objects.filter(parent__isnull=True).order_by(
        "order", "name"
    )
    categories_hierarchical = []
    for parent in parent_categories:
        categories_hierarchical.append(parent)
        subcategories = parent.subcategories.all().order_by("name")
        categories_hierarchical.extend(subcategories)

    categories = categories_hierarchical

    # Read HTML content
    html_content = ""
    if document.html_file:
        try:
            with open(document.html_file.path, "r", encoding="utf-8") as f:
                html_content = f.read()
        except Exception as e:
            messages.error(request, f"Error reading HTML file: {str(e)}")

    context = {
        "document": document,
        "annotations": annotations,
        "annotations_data": annotations_with_categories,
        "categories": categories,
        "html_content": html_content,
    }

    return render(request, "annotator/annotate.html", context)


@login_required
@require_http_methods(["POST"])
def save_annotation(request, pk):
    """API endpoint to save annotations"""
    document = get_object_or_404(Document, pk=pk)

    try:
        # Log the request for debugging
        print(f"Save annotation request for document {pk}")
        print(f"Request body: {request.body[:200]}")

        data = json.loads(request.body)

        # Validate required fields
        if not data.get("category"):
            return JsonResponse(
                {"status": "error", "message": "Category is required"}, status=400
            )

        if not data.get("selectedText"):
            return JsonResponse(
                {"status": "error", "message": "Selected text is required"}, status=400
            )

        # Find the category by name
        category_name = data.get("category")
        try:
            category = AnnotationCategory.objects.get(name=category_name)
        except AnnotationCategory.DoesNotExist:
            return JsonResponse(
                {"status": "error", "message": f'Category "{category_name}" not found'},
                status=400,
            )

        # Calculate embedding and similarity
        embedding = data.get("embedding")
        similarity_score = None
        embedding_binary = None

        try:
            # Get embedding for selected text if not provided

            # Check if we have an embedding
            if embedding:
                # Calculate similarity if category has embedding
                if category.embedding and isinstance(category.embedding, list):
                    similarity_score = cosine_similarity(embedding, category.embedding)

                # Pack embedding to binary
                try:
                    embedding_binary = struct.pack(f"{len(embedding)}f", *embedding)
                except Exception as e:
                    logger.error(f"Error packing embedding: {e}")

        except Exception as e:
            logger.error(f"Error calculating embedding/similarity: {e}")

        annotation = Annotation.objects.create(
            document=document,
            user=request.user,
            category=category,
            selected_text=data.get("selectedText"),
            html_selector=data.get("htmlSelector", ""),
            position_data=data.get("positionData", {}),
            embedding=embedding_binary,
            similarity_score=similarity_score,
        )

        print(f"Annotation created successfully: {annotation.id}")

        return JsonResponse(
            {
                "status": "success",
                "annotation_id": annotation.id,
                "message": "Annotation saved successfully",
            }
        )
    except json.JSONDecodeError as e:
        print(f"JSON decode error: {e}")
        return JsonResponse(
            {"status": "error", "message": f"Invalid JSON: {str(e)}"}, status=400
        )
    except Exception as e:
        print(f"Error saving annotation: {e}")
        import traceback

        traceback.print_exc()
        return JsonResponse({"status": "error", "message": str(e)}, status=400)


@login_required
@require_http_methods(["DELETE"])
def delete_annotation(request, pk, annotation_id):
    """API endpoint to delete an annotation - only delete own annotations"""
    annotation = get_object_or_404(Annotation, pk=annotation_id, document_id=pk, user=request.user)
    annotation.delete()

    return JsonResponse(
        {"status": "success", "message": "Annotation deleted successfully"}
    )


@login_required
@require_http_methods(["GET"])
def get_annotations(request, pk):
    """API endpoint to get all annotations for a document - only user's own annotations"""
    document = get_object_or_404(Document, pk=pk)
    annotations = document.annotations.filter(user=request.user)

    data = [
        {
            "id": ann.id,
            "category": ann.category,
            "selectedText": ann.selected_text,
            "htmlSelector": ann.html_selector,
            "positionData": ann.position_data,
            "createdAt": ann.created_at.isoformat(),
        }
        for ann in annotations
    ]

    return JsonResponse({"annotations": data})


def document_list(request):
    """List all documents with their annotation counts"""
    documents = Document.objects.all()

    # Add annotation count to each document
    for doc in documents:
        doc.annotation_count = doc.annotations.count()

    return render(request, "annotator/document_list.html", {"documents": documents})


@login_required
def export_annotations(request, pk):
    """Export annotations as JSON - only user's own annotations"""
    document = get_object_or_404(Document, pk=pk)
    annotations = document.annotations.filter(user=request.user)

    data = {
        "document": {
            "id": document.id,
            "title": document.title,
            "uploaded_at": document.uploaded_at.isoformat(),
        },
        "annotations": [
            {
                "id": ann.id,
                "category": ann.category,
                "selectedText": ann.selected_text,
                "htmlSelector": ann.html_selector,
                "positionData": ann.position_data,
                "createdAt": ann.created_at.isoformat(),
            }
            for ann in annotations
        ],
    }

    response = JsonResponse(data)
    response["Content-Disposition"] = (
        f'attachment; filename="annotations_{document.pk}.json"'
    )
    return response


def retry_conversion(request, pk):
    """Retry PDF to HTML conversion for failed documents"""
    document = get_object_or_404(Document, pk=pk)

    try:
        document.conversion_status = "processing"
        document.conversion_error = None
        document.save()

        convert_pdf_to_html(document)
        messages.success(
            request, f'Document "{document.title}" converted successfully!'
        )
    except Exception as e:
        messages.error(request, f"Conversion failed: {str(e)}")

    return redirect("document_list")


@require_http_methods(["POST"])
def delete_document(request, pk):
    """Delete a document"""
    document = get_object_or_404(Document, pk=pk)
    try:
        # Delete files from filesystem (Django signals usually handle this but let's be safe for custom logic if needed)
        # Using default behavior of Django FileField/OneToOneField on_delete=CASCADE should be enough for DB models
        title = document.title
        document.delete()
        messages.success(request, f'Document "{title}" deleted successfully.')
    except Exception as e:
        messages.error(request, f"Error deleting document: {str(e)}")

    return redirect("document_list")


# TODO Deprecated endpoint, remove in future releases
@require_http_methods(["POST"])
def create_category(request):
    """API endpoint to create a new annotation category"""
    try:
        data = json.loads(request.body)

        # Validate required fields
        if not data.get("name"):
            return JsonResponse(
                {"status": "error", "message": "Category name is required"}, status=400
            )

        # Check if category already exists
        if AnnotationCategory.objects.filter(name=data["name"]).exists():
            return JsonResponse(
                {
                    "status": "error",
                    "message": f'Category "{data["name"]}" already exists',
                },
                status=400,
            )

        # Get parent category if specified
        parent = None
        if data.get("parent_id"):
            try:
                parent = AnnotationCategory.objects.get(id=data["parent_id"])
            except AnnotationCategory.DoesNotExist:
                return JsonResponse(
                    {"status": "error", "message": "Parent category not found"},
                    status=400,
                )

        # Create the category
        category = AnnotationCategory.objects.create(
            name=data["name"],
            parent=parent,
            color=data.get("color", "#3498db"),
            description=data.get("description", ""),
            order=AnnotationCategory.objects.filter(parent=parent).count(),
        )

        return JsonResponse(
            {
                "status": "success",
                "category_id": category.id,
                "message": "Category created successfully",
            }
        )

    except json.JSONDecodeError as e:
        return JsonResponse(
            {"status": "error", "message": f"Invalid JSON: {str(e)}"}, status=400
        )
    except Exception as e:
        return JsonResponse(
            {"status": "error", "message": f"Error creating category: {str(e)}"},
            status=500,
        )


@require_http_methods(["POST"])
def suggest_categories(request):
    """
    Computes embedding for input text and returns top 3 similar categories.
    """
    try:
        data = json.loads(request.body)
        text = data.get("text", "")

        if not text:
            return JsonResponse(
                {"status": "error", "message": "No text provided"}, status=400
            )

        # Get embedding for the text
        text_embedding = get_embedding(text)

        if text_embedding is None or len(text_embedding) == 0:
            return JsonResponse(
                {"status": "error", "message": "Failed to generate embedding"},
                status=500,
            )

        # Get all categories with embeddings
        # We fetch all and filter in python to be safe with JSONField quirks across DBs
        categories = AnnotationCategory.objects.all()

        scored_categories = []
        for cat in categories:
            # Skip if embedding is empty or not a list/valid structure
            if not cat.embedding or not isinstance(cat.embedding, list):
                continue

            score = cosine_similarity(text_embedding, cat.embedding)
            scored_categories.append(
                {
                    "id": cat.id,
                    "name": cat.name,
                    "color": cat.color,
                    "score": score,
                    "parent_name": cat.parent.name if cat.parent else None,
                    "description": cat.description,
                }
            )

        # Sort by score descending and take top 3
        scored_categories.sort(key=lambda x: x["score"], reverse=True)
        top_categories = scored_categories[:3]

        return JsonResponse(
            {
                "status": "success",
                "suggestions": top_categories,
                "embedding": text_embedding.tolist(),
            }
        )

    except Exception as e:
        logger.error(f"Error in suggest_categories: {e}")
        return JsonResponse({"status": "error", "message": str(e)}, status=500)


@login_required
@require_http_methods(["POST"])
def update_annotation(request, pk, annotation_id):
    """API endpoint to update an annotation's category - only own annotations"""
    document = get_object_or_404(Document, pk=pk)
    annotation = get_object_or_404(Annotation, pk=annotation_id, document=document, user=request.user)

    try:
        data = json.loads(request.body)
        new_category_name = data.get("category")

        if not new_category_name:
            return JsonResponse(
                {"status": "error", "message": "Category is required"}, status=400
            )

        try:
            category = AnnotationCategory.objects.get(name=new_category_name)
        except AnnotationCategory.DoesNotExist:
            return JsonResponse(
                {
                    "status": "error",
                    "message": f'Category "{new_category_name}" not found',
                },
                status=400,
            )

        # Update category
        annotation.category = category

        # Recalculate similarity if possible
        if (
            annotation.embedding
            and category.embedding
            and isinstance(category.embedding, list)
        ):
            try:
                # Unpack embedding (assuming it's a list of floats)
                # length is len(annotation.embedding) / 4 (since float is 4 bytes)
                num_floats = len(annotation.embedding) // 4
                embedding_vector = struct.unpack(f"{num_floats}f", annotation.embedding)

                similarity_score = cosine_similarity(
                    list(embedding_vector), category.embedding
                )
                annotation.similarity_score = similarity_score
            except Exception as e:
                logger.error(f"Error recalculating similarity during update: {e}")

        annotation.save()

        return JsonResponse(
            {
                "status": "success",
                "message": "Annotation updated successfully",
                "category_name": category.name,
                "category_color": category.color,
            }
        )

    except Exception as e:
        logger.error(f"Error updating annotation: {e}")
        return JsonResponse({"status": "error", "message": str(e)}, status=400)
