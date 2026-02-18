from gitingest import ingest

import django
import os
from datetime import date
from pathlib import Path
from pypdf import PdfReader
import json

from bs4 import BeautifulSoup
import requests
import time

import subprocess
import tempfile
import re
import shutil

from webApp.models import Paper, TokenUsage


os.environ.setdefault(
    "DJANGO_SETTINGS_MODULE",
    os.getenv("DJANGO_SETTINGS_MODULE", "web.settings.development"),
)

django.setup()


def update_token(tokens_used: int, token_var: str) -> int:
    """Update the cumulative token usage for a given LLM model.

    Resets the counter at the beginning of each day and stores usage in the database.

    Args:
        tokens_used: The number of tokens used in the current API call.
        token_var: The environment variable name that tracks the cumulative token usage.
    Returns:
        The updated cumulative token usage for today.
    """
    today = date.today()

    # Get or create today's token usage record
    token_record, created = TokenUsage.objects.get_or_create(
        date=today, model_var=token_var, defaults={"tokens_used": 0}
    )

    # Update the token count
    token_record.tokens_used += tokens_used
    token_record.save()

    return token_record.tokens_used


# Token limits for free tier
TOKEN_LIMITS = {
    "TOTAL_TOKEN_OPENAI": 250000,
    "TOTAL_TOKEN_OPENAI_MINI": 1250000,
}


class TokenLimitExceededError(Exception):
    """Raised when the token usage exceeds the allowed limit."""

    pass


def analyze_code(url: str) -> dict:
    """Ingest code from a repository and run static analysis tools.

    Runs ruff for Python, biome for JS/TS, and shellcheck for shell scripts.

    Args:
        url: URL of the code repository.
    Returns:
        A dictionary with:
            - tree: The file tree structure of the repository
            - content: The formatted content string (SUMMARY + TREE + CONTENT)
            - code_errors: Static analysis results for each language
    """
    patterns = [
        "*.md",
        "docs/",
        "*.ipynb",
        "LICENSE*",
        "main*",
    ]
    # TODO Testing python code linter (ruff)
    patterns.append("eval/mrg_old2.py")

    _, tree, content = ingest(
        url,
        include_patterns=patterns,
    )

    # Parse content to extract individual files
    # Format: ================================================
    #         FILE: filename.ext
    #         ================================================
    #         <content>
    file_pattern = re.compile(
        r"={48}\nFILE: (.+?)\n={48}\n(.*?)(?=\n={48}\nFILE:|\Z)", re.DOTALL
    )

    files_extracted = {}
    for match in file_pattern.finditer(content):
        filename = match.group(1).strip()
        file_content = match.group(2)
        # Skip empty files
        if file_content.strip() and file_content.strip() != "[Empty file]":
            files_extracted[filename] = file_content

    if not files_extracted:
        return {"error": "No files extracted from repository"}

    results = {
        "python": {"files": [], "issues": []},
        "javascript": {"files": [], "issues": []},
        "shell": {"files": [], "issues": []},
    }

    # Create temporary directory to write files for analysis
    with tempfile.TemporaryDirectory() as tmpdir:
        # Write files to temp directory preserving structure
        for filepath, file_content in files_extracted.items():
            # Create subdirectories if needed
            full_path = Path(tmpdir) / filepath
            full_path.parent.mkdir(parents=True, exist_ok=True)
            full_path.write_text(file_content)

            # Track files by type
            if filepath.endswith((".py")):
                results["python"]["files"].append(filepath)
            elif filepath.endswith((".js", ".ts")):
                results["javascript"]["files"].append(filepath)
            elif filepath.endswith(".sh"):
                results["shell"]["files"].append(filepath)

        # Run ruff for Python files
        if results["python"]["files"]:
            try:
                # Build list of Python file paths to check
                python_files = [
                    str(Path(tmpdir) / f) for f in results["python"]["files"]
                ]

                # Run ruff check for linting on specific files
                proc = subprocess.run(
                    [
                        "ruff",
                        "check",
                        "--output-format=json",
                        "--select",
                        "E9,F63,F7,F82",
                    ]
                    + python_files,
                    capture_output=True,
                    text=True,
                    timeout=60,
                )
                if proc.stdout:
                    try:
                        results["python"]["issues"] = json.loads(proc.stdout)
                    except json.JSONDecodeError:
                        results["python"]["issues"] = proc.stdout
                if proc.stderr:
                    results["python"]["stderr"] = proc.stderr
            except FileNotFoundError:
                results["python"]["error"] = "ruff not installed"
            except subprocess.TimeoutExpired:
                results["python"]["error"] = "ruff timed out"

        # Run biome for JavaScript/TypeScript files
        if results["javascript"]["files"]:
            try:
                proc = subprocess.run(
                    ["biome", "check", "--reporter=json", "."],
                    cwd=tmpdir,
                    capture_output=True,
                    text=True,
                    timeout=60,
                )
                if proc.stdout:
                    try:
                        results["javascript"]["issues"] = json.loads(proc.stdout)
                    except json.JSONDecodeError:
                        results["javascript"]["issues"] = proc.stdout
                if proc.stderr:
                    results["javascript"]["stderr"] = proc.stderr
            except FileNotFoundError:
                results["javascript"]["error"] = "biome not installed"
            except subprocess.TimeoutExpired:
                results["javascript"]["error"] = "biome timed out"

        # Run shellcheck for shell scripts
        if results["shell"]["files"]:
            try:
                shell_files = [str(Path(tmpdir) / f) for f in results["shell"]["files"]]
                proc = subprocess.run(
                    ["shellcheck", "--format=json"] + shell_files,
                    capture_output=True,
                    text=True,
                    timeout=60,
                )
                if proc.stdout:
                    try:
                        results["shell"]["issues"] = json.loads(proc.stdout)
                    except json.JSONDecodeError:
                        results["shell"]["issues"] = proc.stdout
                if proc.stderr:
                    results["shell"]["stderr"] = proc.stderr
            except FileNotFoundError:
                results["shell"]["error"] = "shellcheck not installed"
            except subprocess.TimeoutExpired:
                results["shell"]["error"] = "shellcheck timed out"

    return {
        "tree": tree,
        "content": content,
        "code_errors": results,
    }


def from_doc_to_code(doc_text: str, url: str) -> list[str]:
    """Extract all code files from a document text.
    This function its designed to be used in the initial stage of the code analysis pipeline,
    to get the subset of the entire repository useful to evaluate the reproducibility of the paper
    Args:
        doc_text: The documentation text extracted from the code repository.
        url: URL of the code repository.
    Returns:
        List of all code files path found in the document text.
    """
    # Step 1: Parse GitHub URL to extract owner and repo name
    github_pattern = re.compile(
        r"https?://(?:www\.)?github\.com/([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+)"
    )
    match = github_pattern.match(url.rstrip("/"))
    if not match:
        return []

    owner, repo = match.groups()
    # Remove .git suffix if present
    repo = repo.removesuffix(".git")

    # Step 2: Fetch repository tree using GitHub API
    api_url = f"https://api.github.com/repos/{owner}/{repo}/git/trees/main?recursive=1"
    headers = {"Accept": "application/vnd.github.v3+json"}

    # Try main branch first, then master
    response = requests.get(api_url, headers=headers, timeout=30)
    if response.status_code != 200:
        api_url = (
            f"https://api.github.com/repos/{owner}/{repo}/git/trees/master?recursive=1"
        )
        response = requests.get(api_url, headers=headers, timeout=30)
        if response.status_code != 200:
            return []

    tree_data = response.json()
    if "tree" not in tree_data:
        return []

    # Build a set of all file paths in the repository
    repo_files = {item["path"] for item in tree_data["tree"] if item["type"] == "blob"}

    # Also build a mapping of filename -> list of full paths for quick lookup
    filename_to_paths: dict[str, list[str]] = {}
    for filepath in repo_files:
        filename = Path(filepath).name
        if filename not in filename_to_paths:
            filename_to_paths[filename] = []
        filename_to_paths[filename].append(filepath)

    # Step 3: Extract filenames mentioned in doc_text
    # Pattern to match common code file references
    # Matches: file.py, path/to/file.py, `file.py`, "file.py", 'file.py'
    file_patterns = [
        # Match paths with extensions (e.g., src/main.py, utils/helper.js)
        r"(?:[\w./\\-]+/)?[\w.-]+\.(?:py|js|ts|sh|yaml|yml|json|toml|cfg|ini|txt|md|rst|ipynb)",
        # Match backtick-quoted filenames
        r"`([\w./\\-]+\.(?:py|js|ts|sh|yaml|yml|json|toml|cfg|ini|txt|md|rst|ipynb))`",
        # Match quoted filenames
        r'["\']([w./\\-]+\.(?:py|js|ts|sh|yaml|yml|json|toml|cfg|ini|txt|md|rst|ipynb))["\']',
    ]

    found_files = set()
    for pattern in file_patterns:
        matches = re.findall(pattern, doc_text, re.IGNORECASE)
        for match in matches:
            # Clean up the match
            cleaned = match.strip("`\"'").strip()
            if cleaned:
                found_files.add(cleaned)

    # Step 4: Resolve found filenames to absolute paths in the repository
    resolved_paths = []
    for found_file in found_files:
        # Check if it's already a full path in the repo
        if found_file in repo_files:
            resolved_paths.append(found_file)
            continue

        # Try to match just the filename
        filename = Path(found_file).name
        if filename in filename_to_paths:
            # If found_file contains a partial path, try to match it
            if "/" in found_file or "\\" in found_file:
                # Normalize the path
                normalized = found_file.replace("\\", "/")
                for full_path in filename_to_paths[filename]:
                    if full_path.endswith(normalized):
                        resolved_paths.append(full_path)
                        break
                else:
                    # If no exact suffix match, add all matching filenames
                    resolved_paths.extend(filename_to_paths[filename])
            else:
                # Just a filename, add all matching paths
                resolved_paths.extend(filename_to_paths[filename])

    # Remove duplicates while preserving order
    seen = set()
    unique_paths = []
    for path in resolved_paths:
        if path not in seen:
            seen.add(path)
            unique_paths.append(path)
    print(unique_paths)
    return unique_paths


def get_pdf_content(
    pdf_path, params={"consolidateHeader": "0", "consolidateCitations": "0"}
):
    """
    Extract clean title and text from a PDF using Grobid and parsed by BeautifulSoup.
    Text field does NOT include metadata and references.
    Args:
        pdf_path: Path to the PDF file.
    Returns:
        title: The title of the paper with spaces replaced by underscores.
        text: The concatenated text including abstract, sections, figures descriptions, and tables.
        sections: Dictionary mapping section names to their content, with figures/tables as separate entries.
    """
    # Use host.docker.internal to reach GROBID running on host from Docker container
    # TODO change the hardcoded link to grobid with the one defined in the environment variable and add error handling if grobid is not reachable
    base_url = os.environ.get("GROBID_URL", "http://grobid:8070")
    grobid_url = f"{base_url}/api/processFulltextDocument"

    try:
        with open(pdf_path, "rb") as pdf_file:
            files = {"input": ("paper.pdf", pdf_file, "application/pdf")}
            response = requests.post(grobid_url, files=files, data=params, timeout=60)

        if response.status_code != 200:
            print(f"Error Grobid: {response.status_code}")
            return None, None, None

        xml_content = response.text

    except Exception as e:
        print(f"Error: {e}")
        return None, None, None

    # 2. BeautifulSoup parsing
    soup = BeautifulSoup(xml_content, "xml")

    # Title extraction
    title_tag = soup.find("title", level="a") or soup.find("title", type="main")

    if not title_tag:
        title_tag = soup.find("title")

    title = title_tag.get_text(strip=True) if title_tag else "Title not Found"

    # Abstract extraction
    abstract_tag = soup.find("abstract")
    abstract_text = None
    if abstract_tag:
        # Get all paragraph text from abstract
        abstract_paragraphs = abstract_tag.find_all("p")
        if abstract_paragraphs:
            abstract_text = "\n\n".join(
                p.get_text(strip=True) for p in abstract_paragraphs
            )
        else:
            abstract_text = abstract_tag.get_text(strip=True)

    body = soup.find("body")

    text_content = []
    sections_dict = {}
    
    # Add abstract at the beginning
    if abstract_text:
        text_content.append("Abstract\n\n" + abstract_text)
        sections_dict["Abstract"] = abstract_text
    
    current_section = None
    section_content = []

    if body:
        # find all paragraph (<p>), section title (<head>), figures and tables
        for tag in body.find_all(["head", "p", "figure"]):
            # Skip head tags that are inside figures (they're handled with the figure)
            if tag.name == "head" and tag.find_parent("figure"):
                continue

            # Remove bibliographic references
            for ref in tag.find_all("ref", type="bibr"):
                ref.decompose()

            # Handle section headers
            if tag.name == "head":
                # Save previous section if exists
                if current_section and section_content:
                    sections_dict[current_section] = "\n\n".join(section_content)
                
                # Start new section
                current_section = tag.get_text(strip=True)
                section_content = []
                text_content.append(current_section)
                continue

            # For figures, extract the caption/description
            elif tag.name == "figure":
                fig_head = tag.find("head")
                fig_desc = tag.find("figDesc")
                table = tag.find("table")

                fig_text_parts = []
                
                # Determine the key for this figure/table
                if fig_head:
                    fig_key = fig_head.get_text(strip=True)
                else:
                    # Generate a key if no head found
                    if table:
                        fig_key = f"Table {len([k for k in sections_dict.keys() if k.startswith('Table')]) + 1}"
                    else:
                        fig_key = f"Figure {len([k for k in sections_dict.keys() if k.startswith('Figure')]) + 1}"

                # Add label (e.g., "Table 1" or "Fig. 1")
                if fig_head and table:
                    fig_text_parts.append(fig_head.get_text(strip=True))

                if fig_desc:
                    fig_text_parts.append(fig_desc.get_text(strip=True))

                # Extract table content with structure
                if table:
                    table_rows = []
                    for row in table.find_all("row"):
                        cells = [
                            cell.get_text(strip=True) for cell in row.find_all("cell")
                        ]
                        table_rows.append(" | ".join(cells))
                    if table_rows:
                        fig_text_parts.append("\n".join(table_rows))

                if fig_text_parts:
                    fig_content = " ".join(fig_text_parts)
                    text_content.append(fig_content)
                    sections_dict[fig_key] = fig_content
            
            # Handle paragraphs
            else:  # tag.name == "p"
                para_text = tag.get_text(strip=True)
                text_content.append(para_text)
                if current_section:
                    section_content.append(para_text)
        
        # Save the last section
        if current_section and section_content:
            sections_dict[current_section] = "\n\n".join(section_content)

    # concatenate all text parts
    text = "\n\n".join(text_content)

    return title, text, sections_dict


def get_text(pdf_file):
    """Extract text from a PDF file object.
    Args:
        pdf_file: File object of the PDF.
    Returns:
        Extracted text from all pages.
    """
    reader = PdfReader(pdf_file)
    pages = reader.pages
    text = ""
    for page in pages:
        text = text + page.extract_text()
    return text


# def upload_pdf(pdf_file):
#     """Upload a PDF file in the DB
#     pdf_file comes from request.FILES["pdf_file"]"""

#     # Read first bytes to check if it's a valid PDF
#     first_bytes = pdf_file.read(4)
#     pdf_file.seek(0)  # Reset file pointer

#     if not first_bytes.startswith(b"%PDF"):
#         print(f"Downloaded file is not a valid PDF")
#         return None

#     title, text = get_pdf_content(pdf_file)

#     # get the paper from db using name
#     existing_paper = Paper.objects.filter(title=title).first()

#     if existing_paper:
#         return existing_paper

#     # Extract text from the PDF
#     pdf_file.seek(0)  # Reset file pointer for saving

#     # Read file content for storage
#     pdf_content = pdf_file.read()
#     pdf_content = ContentFile(pdf_content, name=title + ".pdf")

#     paper = Paper.objects.create(title=title, file=pdf_content, text=text)

#     return paper
{
    "python": {
        "files": ["Constants.py", "main.py", "Responses.py"],
        "issues": [
            {
                "cell": None,
                "code": "F706",
                "end_location": {"column": 36, "row": 20},
                "filename": "/tmp/tmpiyrcdv6i/main.py",
                "fix": None,
                "location": {"column": 1, "row": 20},
                "message": "`return` statement outside of a function/method",
                "noqa_row": 20,
                "url": "https://docs.astral.sh/ruff/rules/return-outside-function",
            },
            {
                "cell": None,
                "code": "F632",
                "end_location": {"column": 15, "row": 24},
                "filename": "/tmp/tmpiyrcdv6i/main.py",
                "fix": {
                    "applicability": "safe",
                    "edits": [
                        {
                            "content": "==",
                            "end_location": {"column": 8, "row": 24},
                            "location": {"column": 6, "row": 24},
                        }
                    ],
                    "message": "Replace `is` with `==`",
                },
                "location": {"column": 4, "row": 24},
                "message": "Use `==` to compare constant literals",
                "noqa_row": 24,
                "url": "https://docs.astral.sh/ruff/rules/is-literal",
            },
            {
                "cell": None,
                "code": "F704",
                "end_location": {"column": 9, "row": 28},
                "filename": "/tmp/tmpiyrcdv6i/main.py",
                "fix": None,
                "location": {"column": 1, "row": 28},
                "message": "`yield` statement outside of a function",
                "noqa_row": 28,
                "url": "https://docs.astral.sh/ruff/rules/yield-outside-function",
            },
        ],
    },
}
{
    "python": {
        "files": ["Constants.py", "main.py", "Responses.py"],
        "issues": [
            {
                "cell": None,
                "code": "invalid-syntax",
                "end_location": {"column": 5, "row": 33},
                "filename": "/tmp/tmpamzgm23o/main.py",
                "fix": None,
                "location": {"column": 1, "row": 33},
                "message": "Unexpected indentation",
                "noqa_row": None,
                "url": None,
            },
            {
                "cell": None,
                "code": "invalid-syntax",
                "end_location": {"column": 1, "row": 35},
                "filename": "/tmp/tmpamzgm23o/main.py",
                "fix": None,
                "location": {"column": 1, "row": 35},
                "message": "Expected a statement",
                "noqa_row": None,
                "url": None,
            },
        ],
    }
}
