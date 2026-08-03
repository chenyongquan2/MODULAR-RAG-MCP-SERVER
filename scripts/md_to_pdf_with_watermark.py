"""Render a Markdown file to PDF with a repeating diagonal watermark.

Flow: Markdown -> HTML (with SVG tiled watermark background) -> Edge headless -> PDF.

Chromium's print engine renders body backgrounds on every page when
`-webkit-print-color-adjust: exact` is set, so a tiled SVG background gives us
a true per-page watermark without per-page positioning hacks.
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from urllib.parse import quote
from urllib.request import pathname2url

import markdown


EDGE_PATHS = [
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
]


def find_edge() -> str:
    for p in EDGE_PATHS:
        if Path(p).exists():
            return p
    raise SystemExit("Microsoft Edge not found in standard locations.")


def build_watermark_svg(text: str) -> str:
    """SVG tile with one watermark string, rotated -30deg, faint gray.

    The tile is wider than tall so two staggered rows give good coverage.
    """
    # 360x240 tile; one text per tile, rotated; opacity ~0.10 = "dark/faint"
    return f"""<svg xmlns='http://www.w3.org/2000/svg' width='420' height='260' viewBox='0 0 420 260'>
  <g transform='rotate(-28 210 130)' fill='#000000' fill-opacity='0.09'
     font-family='Segoe UI, Microsoft YaHei, sans-serif' font-size='22' font-weight='600'>
    <text x='-30' y='90'>{text}</text>
    <text x='40' y='200'>{text}</text>
  </g>
</svg>"""


def build_html(md_text: str, watermark: str, title: str) -> str:
    body_html = markdown.markdown(
        md_text,
        extensions=["extra", "sane_lists", "toc", "tables", "fenced_code"],
        output_format="html5",
    )

    svg = build_watermark_svg(watermark)
    svg_data_url = "data:image/svg+xml;utf8," + quote(svg, safe="")

    css = f"""
    @page {{ size: A4; margin: 18mm 16mm; }}
    html, body {{ background: transparent; }}
    body {{
        font-family: "Microsoft YaHei", "PingFang SC", "Segoe UI", "Helvetica Neue", sans-serif;
        color: #1f2328;
        line-height: 1.65;
        font-size: 11pt;
        margin: 0;
        padding: 0;
        background-image: url("{svg_data_url}");
        background-repeat: repeat;
        -webkit-print-color-adjust: exact;
        print-color-adjust: exact;
    }}
    h1, h2, h3, h4 {{ color: #0b3d91; line-height: 1.3; margin-top: 1.4em; }}
    h1 {{ font-size: 22pt; border-bottom: 2px solid #d0d7de; padding-bottom: 0.2em; }}
    h2 {{ font-size: 16pt; border-bottom: 1px solid #d0d7de; padding-bottom: 0.15em; }}
    h3 {{ font-size: 13pt; }}
    p, li {{ font-size: 11pt; }}
    code {{
        background: rgba(175,184,193,0.2); padding: 1px 5px;
        border-radius: 4px; font-size: 90%;
        font-family: Consolas, "Courier New", monospace;
    }}
    pre {{
        background: #f6f8fa; padding: 10px 14px; border-radius: 6px;
        overflow-x: auto; font-size: 9.5pt;
    }}
    pre code {{ background: transparent; padding: 0; }}
    blockquote {{
        border-left: 4px solid #d0d7de;
        background: rgba(246,248,250,0.85);
        padding: 6px 14px;
        margin: 0.8em 0;
        color: #444;
    }}
    table {{ border-collapse: collapse; margin: 0.6em 0; }}
    th, td {{ border: 1px solid #d0d7de; padding: 6px 10px; font-size: 10pt; }}
    th {{ background: #f6f8fa; }}
    hr {{ border: none; border-top: 1px solid #d0d7de; margin: 1.5em 0; }}
    a {{ color: #0969da; text-decoration: none; }}
    a:hover {{ text-decoration: underline; }}
    img {{ max-width: 100%; }}
    /* page-break friendliness */
    h1, h2, h3 {{ page-break-after: avoid; }}
    pre, blockquote, table {{ page-break-inside: avoid; }}
    """

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<title>{title}</title>
<style>{css}</style>
</head>
<body>
{body_html}
</body>
</html>
"""


def html_to_pdf_with_edge(html_path: Path, pdf_path: Path) -> None:
    edge = find_edge()
    # Use a throwaway user-data-dir to avoid clashing with the user's Edge profile.
    with tempfile.TemporaryDirectory(prefix="edge-pdf-") as udd:
        url = "file:///" + pathname2url(str(html_path.resolve())).lstrip("/")
        cmd = [
            edge,
            "--headless=new",
            "--disable-gpu",
            "--no-pdf-header-footer",
            f"--user-data-dir={udd}",
            f"--print-to-pdf={pdf_path.resolve()}",
            url,
        ]
        # Edge sometimes needs a couple of seconds; give it generous timeout.
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
        if proc.returncode != 0 or not pdf_path.exists():
            sys.stderr.write(proc.stdout)
            sys.stderr.write(proc.stderr)
            raise SystemExit(f"Edge headless failed (rc={proc.returncode}).")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True, help="Path to source markdown file")
    ap.add_argument("--output", required=True, help="Path to output PDF")
    ap.add_argument("--watermark", required=True, help="Watermark text")
    ap.add_argument("--keep-html", action="store_true", help="Keep intermediate HTML next to PDF")
    args = ap.parse_args()

    md_path = Path(args.input)
    pdf_path = Path(args.output)
    md_text = md_path.read_text(encoding="utf-8")

    title = md_path.stem
    html = build_html(md_text, args.watermark, title)

    html_path = pdf_path.with_suffix(".tmp.html")
    html_path.write_text(html, encoding="utf-8")
    try:
        html_to_pdf_with_edge(html_path, pdf_path)
    finally:
        if args.keep_html:
            final_html = pdf_path.with_suffix(".html")
            shutil.copyfile(html_path, final_html)
            print(f"[kept HTML] {final_html}")
        try:
            html_path.unlink()
        except FileNotFoundError:
            pass

    size_kb = pdf_path.stat().st_size / 1024
    print(f"[ok] {pdf_path}  ({size_kb:.1f} KB)")


if __name__ == "__main__":
    main()
