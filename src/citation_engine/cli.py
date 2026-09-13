"""Interactive and CLI runner for Citation Engine.

Usage:
  python src/cite.py "10.1038/s41586-020-2649-2"
  python src/cite.py "https://arxiv.org/abs/1706.03762" --style MLA
  python src/cite.py "978-0132350884" --all
  python src/cite.py --demo
"""

from __future__ import annotations

import argparse
import asyncio
import sys

from citation_engine.models import CitationStyle
from citation_engine.service import CitationService


def format_colored(text: str, color_code: str) -> str:
    """Lightweight ANSI color formatting for terminal output."""
    return f"\033[{color_code}m{text}\033[0m"


async def run_citation(
    target: str,
    style_name: str = "ALL",
    page: str | None = None,
    show_json: bool = False,
):
    print("\n" + "=" * 70)
    print(f"  \033[1mCitation Engine\033[0m - Resolving: {target}")
    print("=" * 70)

    service = CitationService()
    meta = await service.get_metadata(target)

    if not meta:
        print("\n\033[31m[-] Could not resolve metadata for the provided target.\033[0m")
        print("    Please check the URL/DOI/ISBN and internet connection.\n")
        return

    # Metadata summary
    print(f"\n\033[32m[+] Metadata Extracted:\033[0m")
    print(f"  * \033[1mTitle:\033[0m        {meta.title}")
    authors_desc = ", ".join(a.full_name for a in meta.authors) if meta.authors else "(None / Corporate)"
    print(f"  * \033[1mAuthors:\033[0m      {authors_desc}")
    date_desc = f"{meta.date.year or 'n.d.'}" + (f"-{meta.date.month:02d}" if meta.date.month else "")
    print(f"  * \033[1mDate:\033[0m         {date_desc}")
    print(f"  * \033[1mType:\033[0m         {meta.source_type.value}")
    if meta.container_title:
        print(f"  * \033[1mContainer:\033[0m    {meta.container_title}")
    if meta.publisher:
        print(f"  * \033[1mPublisher:\033[0m    {meta.publisher}")
    if meta.doi:
        print(f"  * \033[1mDOI:\033[0m          {meta.doi}")
    if meta.isbn:
        print(f"  * \033[1mISBN:\033[0m         {meta.isbn}")
    if meta.url:
        print(f"  * \033[1mURL:\033[0m          {meta.url}")

    conf_pct = int(meta.confidence_score * 100)
    conf_color = "32" if conf_pct >= 80 else ("33" if conf_pct >= 60 else "31")
    print(f"  * \033[1mConfidence:\033[0m   \033[{conf_color}m{conf_pct}%\033[0m")

    if meta.provenance_warnings:
        print(f"\n  \033[33m[!] Provenance Warnings:\033[0m")
        for w in meta.provenance_warnings:
            print(f"    - {w}")

    # Render citations
    styles_to_render = []
    if style_name.upper() == "ALL":
        styles_to_render = [
            CitationStyle.APA,
            CitationStyle.MLA,
            CitationStyle.CHICAGO,
            CitationStyle.IEEE,
            CitationStyle.BIBTEX,
        ]
    else:
        try:
            styles_to_render = [CitationStyle(style_name.upper())]
        except ValueError:
            styles_to_render = [CitationStyle.APA]

    print("\n" + "-" * 70)
    print("  \033[1mFormatted Citations:\033[0m")
    print("-" * 70)

    for st in styles_to_render:
        res = await service.cite(target, style=st, page_or_loc=page)
        print(f"\n\033[36m[{st.value}]\033[0m")
        print(f"  \033[1mBibliography:\033[0m")
        if st == CitationStyle.BIBTEX:
            for line in res.bibliography_entry.splitlines():
                print(f"    {line}")
        else:
            print(f"    {res.bibliography_entry}")

        if st != CitationStyle.BIBTEX:
            print(f"  \033[1mIn-Text:\033[0m      {res.in_text_citation}")
        else:
            print(f"  \033[1mLaTeX:\033[0m        {res.in_text_citation}")

    print("\n" + "=" * 70 + "\n")


DEMO_TARGETS = [
    ("Academic DOI (Vaswani et al. - Transformers)", "10.5555/3295222.3295349"),
    ("Book ISBN (Clean Code - Robert C. Martin)", "978-0132350884"),
    ("Webpage / Article (Python 3.12 documentation)", "https://docs.python.org/3/whatsnew/3.12.html"),
]


async def interactive_menu():
    print("\n" + "=" * 70)
    print("  \033[1mResearch Assistant - Citation Engine CLI\033[0m")
    print("=" * 70)
    print("  Options:")
    print("    1. Enter custom URL, DOI, or ISBN")
    print("    2. Run quick demo with known Academic DOI")
    print("    3. Run quick demo with Book ISBN")
    print("    4. Run quick demo with Webpage")
    print("    5. Exit")

    choice = input("\nSelect an option [1-5] (default: 1): ").strip() or "1"

    if choice == "1":
        target = input("\nEnter URL, DOI, or ISBN: ").strip()
        if not target:
            print("No target entered. Exiting.")
            return
        style_choice = input("Style (APA / MLA / CHICAGO / IEEE / BIBTEX / ALL) [default: ALL]: ").strip() or "ALL"
        await run_citation(target, style_name=style_choice)
    elif choice in {"2", "3", "4"}:
        idx = int(choice) - 2
        label, target = DEMO_TARGETS[idx]
        print(f"\nRunning demo for: {label} ({target})")
        await run_citation(target, style_name="ALL")
    else:
        print("Goodbye!")


def main():
    parser = argparse.ArgumentParser(
        description="Citation Engine CLI: generate APA, MLA, Chicago, IEEE, and BibTeX citations from URL, DOI, or ISBN."
    )
    parser.add_argument(
        "target",
        nargs="?",
        default=None,
        help="Target DOI (e.g. 10.1038/...), ISBN (e.g. 978-0132350884), or URL.",
    )
    parser.add_argument(
        "-s",
        "--style",
        default="ALL",
        choices=["APA", "MLA", "CHICAGO", "IEEE", "BIBTEX", "ALL", "apa", "mla", "chicago", "ieee", "bibtex", "all"],
        help="Citation style to format (default: ALL).",
    )
    parser.add_argument(
        "-p",
        "--page",
        default=None,
        help="Optional page number or range for in-text citations (e.g. '45' or '12-15').",
    )
    parser.add_argument(
        "--demo",
        action="store_true",
        help="Run a batch demo on sample DOI, ISBN, and URL.",
    )

    args = parser.parse_args()

    if args.demo:
        for label, tgt in DEMO_TARGETS:
            asyncio.run(run_citation(tgt, style_name=args.style, page=args.page))
    elif args.target:
        asyncio.run(run_citation(args.target, style_name=args.style, page=args.page))
    else:
        asyncio.run(interactive_menu())


if __name__ == "__main__":
    main()
