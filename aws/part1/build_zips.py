"""Build the three upload zips for Part 1 into aws/part1/dist/.

Usage (from the repo root, any OS):
    python aws/part1/build_zips.py

    dist/pdd-scraping-deps-layer.zip   Lambda layer: requests + beautifulsoup4 for Python 3.12 (Linux)
    dist/pdd-scraper.zip               lambda_function.py + the repo's scraper.py
    dist/pdd-dispatcher.zip            lambda_function.py

Uses pip's --platform flags, so it builds Linux wheels even on Windows or macOS.
"""
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

PART1 = Path(__file__).resolve().parent
REPO = PART1.parent.parent
DIST = PART1 / "dist"


def zip_dir(src_dir, zip_path, arc_prefix=""):
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
        for f in sorted(src_dir.rglob("*")):
            if f.is_file() and "__pycache__" not in f.parts:
                z.write(f, arc_prefix + f.relative_to(src_dir).as_posix())


def main():
    if not (REPO / "scraper.py").is_file():
        sys.exit(f"scraper.py not found in {REPO}; run from inside the repo")
    if DIST.exists():
        shutil.rmtree(DIST)
    DIST.mkdir()

    with tempfile.TemporaryDirectory() as tmp:
        target = Path(tmp) / "python"
        subprocess.run([
            sys.executable, "-m", "pip", "install", "--quiet",
            "--platform", "manylinux2014_x86_64", "--implementation", "cp",
            "--python-version", "3.12", "--only-binary=:all:",
            "--target", str(target), "-r", str(PART1 / "layer" / "requirements.txt"),
        ], check=True)
        zip_dir(Path(tmp), DIST / "pdd-scraping-deps-layer.zip")

    with zipfile.ZipFile(DIST / "pdd-scraper.zip", "w", zipfile.ZIP_DEFLATED) as z:
        z.write(PART1 / "scraper" / "lambda_function.py", "lambda_function.py")
        z.write(REPO / "scraper.py", "scraper.py")
    with zipfile.ZipFile(DIST / "pdd-dispatcher.zip", "w", zipfile.ZIP_DEFLATED) as z:
        z.write(PART1 / "dispatcher" / "lambda_function.py", "lambda_function.py")

    for f in sorted(DIST.iterdir()):
        print(f"{f.name:<32}{f.stat().st_size / 1024:>8.0f} KB")


if __name__ == "__main__":
    main()
