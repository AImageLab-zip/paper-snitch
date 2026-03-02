from bs4 import BeautifulSoup
import requests
from pathlib import Path
from gitingest import ingest


def analyze_code(url: str) -> dict:
    """Ingest code from a repository and run static analysis tools.

    Runs ruff for Python, biome for JS/TS, and shellcheck for shell scripts.

    Args:
        url: URL of the code repository.
    Returns:
        A dictionary with analysis results for each tool.
    """
    import subprocess
    import tempfile
    import re
    import shutil

    _, _, content = ingest(url, include_patterns=["*.py"])

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
            if "main.py" in filepath:
                print(file_content)
            full_path = Path(tmpdir) / filepath
            full_path.parent.mkdir(parents=True, exist_ok=True)
            full_path.write_text(file_content)

            # Track files by type
            if filepath.endswith((".py", ".ipynb")):
                results["python"]["files"].append(filepath)
            elif filepath.endswith((".js", ".ts")):
                results["javascript"]["files"].append(filepath)
            elif filepath.endswith(".sh"):
                results["shell"]["files"].append(filepath)

        # Run ruff for Python files
        if results["python"]["files"]:
            try:
                list = [
                    "ruff",
                    "check",
                    "--output-format=json",
                    ".",
                ]
                print(list)
                proc = subprocess.run(
                    list,
                    cwd=tmpdir,
                    capture_output=True,
                    text=True,
                    timeout=60,
                )
                if proc.stdout:
                    import json

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
                    import json

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
                    import json

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

    return results


def get_clean_content(pdf_path):
    """
    Extract clean title and text from a PDF using Grobid and BeautifulSoup.
    Args:
        pdf_path: Path to the PDF file.
    Returns:
        A tuple containing the title and cleaned text."""
    grobid_url = "http://localhost:8070/api/processFulltextDocument"
    params = {"consolidateHeader": "0", "consolidateCitations": "0"}

    try:
        with open(pdf_path, "rb") as f:
            files = {"input": f}
            response = requests.post(grobid_url, files=files, data=params)

        if response.status_code != 200:
            print("Errore Grobid")
            return None, None

        xml_content = response.text

    except Exception as e:
        print(f"Errore di connessione: {e}")
        return None, None

    # 2. BeautifulSoup parsing
    soup = BeautifulSoup(xml_content, "xml")

    # Title extraction
    title_tag = soup.find("title", level="a") or soup.find("title", type="main")
    # Title Fallback
    if not title_tag:
        title_tag = soup.find("title")

    title = title_tag.get_text(strip=True) if title_tag else "Titolo not Found"

    # Text extraction

    body = soup.find("body")

    text_content = []

    if body:
        # find all paragraph (<p>) and the section title (<head>)
        for tag in body.find_all(["head", "p"]):
            # Remove bibliographic references
            for ref in tag.find_all("ref", type="bibr"):
                ref.decompose()

            text_content.append(tag.get_text(strip=True))

    # concatenate all text parts
    full_text = "\n\n".join(text_content)

    return title, full_text


# --- Utilizzo ---
if __name__ == "__main__":
    # path = Path(
    #     BASE_DIR / "app/media/pdf/20251128163055_0308_paper.pdf"
    # )
    # titolo, testo = get_clean_content(path)

    # print(f"--- TITLE ---\n{titolo}\n")
    # print(
    #     f"--- TEXT ---\n{testo[:500]}..."
    # )  # Stampo solo i primi 500 caratteri per prova
    result = analyze_code("https://github.com/Santuzz/prova_lib")
    print(result)
