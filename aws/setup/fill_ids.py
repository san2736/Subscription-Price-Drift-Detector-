"""Fill your account ID and bucket name into the IAM policy templates.

Usage (from the repo root):
    python aws/setup/fill_ids.py 123456789012 pdd-yourname-data

Writes ready-to-paste copies to aws/setup/iam/filled/ (git-ignored).
"""
import pathlib
import re
import sys

PLACEHOLDER_ACCOUNT = "111122223333"
PLACEHOLDER_BUCKET = "pdd-yourname-data"


def main():
    if len(sys.argv) != 3:
        sys.exit("usage: python aws/setup/fill_ids.py <12-digit-account-id> <bucket-name>")
    account, bucket = sys.argv[1].replace("-", ""), sys.argv[2]
    if not re.fullmatch(r"\d{12}", account):
        sys.exit(f"account ID must be 12 digits, got {sys.argv[1]!r}")
    if not bucket.startswith("pdd-"):
        sys.exit("bucket name must start with 'pdd-' or the team policy won't cover it")

    iam_dir = pathlib.Path(__file__).parent / "iam"
    out_dir = iam_dir / "filled"
    out_dir.mkdir(exist_ok=True)
    for src in sorted(iam_dir.glob("*.json")):
        text = src.read_text().replace(PLACEHOLDER_ACCOUNT, account).replace(PLACEHOLDER_BUCKET, bucket)
        (out_dir / src.name).write_text(text)
        print(f"wrote {out_dir / src.name}")


if __name__ == "__main__":
    main()
