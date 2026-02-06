import json
import sys
from pathlib import Path
from django.db import transaction
import argparse
import requests


import django
from django.core.files.base import ContentFile
import os
from pypdf import PdfReader

os.environ.setdefault(
    "DJANGO_SETTINGS_MODULE",
    os.getenv("DJANGO_SETTINGS_MODULE", "web.settings.development"),
)
django.setup()

from web.settings.base import BASE_DIR, MEDIA_ROOT
from webApp.models import Paper, Dataset, Conference
from dotenv import load_dotenv

sys.path.append(str(BASE_DIR))

load_dotenv(BASE_DIR / ".env.local")

import json


def load_embeddings():
    """Fill missing embeddings for AnnotationCategory entries in the database."""
    from annotator.models import AnnotationCategory

    categories = AnnotationCategory.objects.filter(embedding={})
    print(f"Found {categories.count()} categories without embeddings.")
    with open("categories_embeddings_1536.json") as f:
        embeddings_data = json.load(f)
    for category in categories:
        print(f"Generating embedding for category: {category.name}")
        # Here you would call your embedding generation function
        embedding_vector = embeddings_data.get(category.name, {})

        # Update the category with the new embedding
        category.embedding = embedding_vector
        category.save()
        print(f"Updated category '{category.name}' with new embedding.")


def parseArguments():
    parser = argparse.ArgumentParser(
        description="Load papers from JSON file into the database"
    )
    parser.add_argument(
        "-d",
        "--defaults",
        action="store_true",
        help="Use default values for conference information",
    )
    parser.add_argument(
        "--confName",
        type=str,
        help="Name of the conference",
    )
    parser.add_argument(
        "--confYear",
        type=int,
        help="Year of the conference",
    )
    parser.add_argument(
        "--confUrl",
        type=str,
        help="URL of the conference website",
    )
    parser.add_argument(
        "--file",
        type=str,
        default="papers_info.json",
        help="Path to JSON file",
    )

    args = parser.parse_args()
    return args


def save_supplementary_materials(paper, conference_name, conference_year, supp_url):

    try:
        print(f"  ↓ Downloading supplementary materials from: {supp_url}")
        response = requests.get(supp_url, timeout=30)
        response.raise_for_status()
        # per ottenere i byte che compongono il file
        supp_materials_content = response.content

    except requests.RequestException as e:
        print(f"Error during the download of {supp_url}: {e}")
        exit(1)
    name = supp_url.split("/")[-1]
    name = f"{conference_name}_{conference_year}_{name}"
    supp_materials = ContentFile(supp_materials_content, name=name)
    print(f"File saved: {supp_materials.name}")
    return supp_materials


def save_pdf(paper, conference_name, conference_year):
    """Download and save PDF file for a paper."""
    if not paper.pdf_url:
        print(f"No PDF URL for paper: {paper.title}...")
        return False

    try:
        print(f"  ↓ Downloading PDF from: {paper.pdf_url}")
        response = requests.get(paper.pdf_url, timeout=30)
        response.raise_for_status()
        # per ottenere i byte che compongono il PDF
        pdf_content = response.content

        # Verify it's actually a PDF
        if not pdf_content.startswith(b"%PDF"):
            print(f"Downloaded file is not a valid PDF")
            return False

    except requests.RequestException as e:
        print(f"Error during the download of {paper.pdf_url}: {e}")
        return
    name = paper.pdf_url.split("/")[-1]
    name = f"{conference_name}_{conference_year}_{name}"
    pdf_file = ContentFile(pdf_content, name=name)
    print(f"File saved: {pdf_file.name}")
    return pdf_file


def load_data(file_path, conference_name, conference_year, conference_url):
    """
    Load papers from JSON file into the database.

    Args:
        file_path: Path to the JSON file containing papers data
        conference_name: Name of the conference
        year: Year of the conference
        conference_url: URL of the conference
    """

    if not Path(file_path).exists():
        print(f"Error: File not found: {file_path}")
        return

    with open(file_path, "r", encoding="utf-8") as f:
        papers = json.load(f)

    print(f"Loading {len(papers)} papers for {conference_name} {conference_year}...")
    print(f"Conference URL: {conference_url}")

    # Create or get conference
    conference, created = Conference.objects.get_or_create(
        name=conference_name,
        year=conference_year,
        url=conference_url,
    )
    if created:
        print(f"✓ Created conference: {conference_name} {conference_year}")
    else:
        conference.save()
        print(f"↻ Using existing conference: {conference_name} {conference_year}")

    created_papers = 0
    updated_papers = 0
    errors = 0

    for paper in papers:

        with transaction.atomic():

            # authors_list = []
            # if paper.get("authors"):
            #     authors = [name.strip() for name in paper["authors"].split(",")]
            #     for author in authors:
            #         if author:
            #             author, created = Author.objects.get_or_create(name=author)
            #             authors_list.append(author)
            #             if created:
            #                 print(f"  ✓ Created author: {author}")

            datasets_list = []
            if paper.get("datasets"):
                if isinstance(paper["datasets"], dict):
                    for name, url in paper["datasets"].items():
                        dataset, created = Dataset.objects.get_or_create(
                            name=name, url=url
                        )
                        datasets_list.append(dataset)
                    paper.pop("datasets")

            exsisting_paper = None
            if paper.get("paper_url"):
                exsisting_paper = Paper.objects.filter(
                    paper_url=paper["paper_url"]
                ).first()

            if not exsisting_paper and paper.get("doi"):
                exsisting_paper = Paper.objects.filter(doi=paper["doi"]).first()
            supp_materials = ""
            if exsisting_paper:
                # Update existing paper
                for key, value in paper.items():
                    setattr(exsisting_paper, key, value)
                exsisting_paper.save()
                updated_papers += 1
                print(f"↻ Updated paper: {exsisting_paper.title}...")
                paper = exsisting_paper
            else:
                # Create new paper
                supp_materials_url = paper.pop("supp_materials", None)
                paper = Paper.objects.create(**paper)
                created_papers += 1
                print(f"✓ Created paper: {paper.title}...")

            pdf_file = save_pdf(paper, conference_name, conference_year)
            if supp_materials_url:
                supp_materials = save_supplementary_materials(
                    paper, conference_name, conference_year, supp_materials_url
                )
                paper.supp_materials.save(
                    supp_materials.name, supp_materials, save=True
                )

            paper.pdf_file.save(pdf_file.name, pdf_file, save=True)
            # Set many-to-many relationship
            # paper.authors.set(authors_list)
            conference.papers.add(paper)
            paper.datasets.set(datasets_list)

    # Summary
    print("\n" + "=" * 50)
    print("Summary:")
    print(f"  Papers created: {created_papers}")
    print(f"  Papers updated: {updated_papers}")
    if errors > 0:
        print(f"  Errors: {errors}")
    print("=" * 50)


# args = parseArguments()
# if args.defaults is None and (
#     args.confName is None or args.confYear is None or args.confUrl is None
# ):
#     print(
#         f"Information about the conference not provided (use -d for defaults values)"
#     )
#     exit(1)

# json_file = MEDIA_ROOT / args.file if args.file else MEDIA_ROOT / "papers_info.json"
# if args.defaults is not None:
#     args.confName = "MICCAI"
#     args.confYear = "2025"
#     args.confUrl = "https://papers.miccai.org/miccai-2025/"

# print(f"Loading papers from: {json_file}")
# # load_data(json_file, args.confName, args.confYear, args.confUrl)

# paper = {"pdf_url": "https://papers.miccai.org/miccai-2025/paper/0752_paper.pdf"}
# response = requests.get(paper["pdf_url"], timeout=30)
# response.raise_for_status()
# # per ottenere i byte che compongono il PDF
# pdf_content = response.content

# name = paper["pdf_url"].split("/")[-1]
# name = f"{args.confName.lower()}_{args.confYear}_{name}"
# with open(MEDIA_ROOT / "pdf" / name, "wb") as f:
#     f.write(pdf_content)

# reader = PdfReader(MEDIA_ROOT / "pdf" / name)
# pages = reader.pages
# text = ""
# for page in pages:
#     text = text + page.extract_text()
# with open(MEDIA_ROOT / "pdf" / f"{name.split('.')[0]}.txt", "w") as text_file:
#     text_file.write(text)
