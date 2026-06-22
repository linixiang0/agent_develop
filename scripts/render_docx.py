from __future__ import annotations

import html
import re
import shutil
import struct
import zipfile
from pathlib import Path

from render_report import render_diagram


ROOT = Path(__file__).resolve().parents[1]
REPORT_MD = ROOT / "docs" / "report.md"
REPORT_DOCX = ROOT / "docs" / "CS599_大作业报告_可编辑版.docx"

W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
R_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
WP_NS = "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing"
A_NS = "http://schemas.openxmlformats.org/drawingml/2006/main"
PIC_NS = "http://schemas.openxmlformats.org/drawingml/2006/picture"


def main() -> None:
    markdown = REPORT_MD.read_text(encoding="utf-8")
    title, fields, content = split_cover(markdown)
    body, rels, media = render_body(title, fields, content)
    write_docx(body, rels, media)
    print(REPORT_DOCX)


def split_cover(markdown: str) -> tuple[str, list[tuple[str, str]], str]:
    lines = markdown.splitlines()
    title = lines[0].removeprefix("# ").strip() if lines else "报告"
    fields: list[tuple[str, str]] = []
    content_start = 1
    for index, line in enumerate(lines[1:], start=1):
        if line.startswith("## "):
            content_start = index
            break
        stripped = line.strip()
        if not stripped:
            continue
        key, sep, value = stripped.partition("：")
        if not sep:
            key, sep, value = stripped.partition(":")
        if sep and value:
            fields.append((key.strip(), value.strip()))
    return title, fields, "\n".join(lines[content_start:])


def render_body(title: str, fields: list[tuple[str, str]], markdown: str) -> tuple[str, list[str], list[tuple[Path | bytes, str]]]:
    parts: list[str] = []
    rels: list[str] = []
    media: list[tuple[Path | bytes, str]] = []
    image_counter = 1

    def add_media(source: Path | bytes, extension: str, width_px: int, height_px: int) -> str:
        nonlocal image_counter
        rid = f"rId{image_counter}"
        name = f"image{image_counter}{extension}"
        image_counter += 1
        rels.append(
            f'<Relationship Id="{rid}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" Target="media/{name}"/>'
        )
        media.append((source, name))
        parts.append(image_paragraph(rid, name, width_px, height_px))
        return rid

    parts.append(paragraph(title, style="Title", align="center"))
    parts.append(render_table(fields))
    parts.append(paragraph("", page_break=True))
    parts.append(paragraph("目录", style="Heading1", align="center"))
    for level, heading in collect_toc(markdown):
        parts.append(paragraph(clean_inline(heading), style=f"TOC{level}"))
    parts.append(paragraph("", page_break=True))

    lines = markdown.splitlines()
    paragraph_lines: list[str] = []
    table_lines: list[str] = []
    list_items: list[str] = []
    in_code = False
    code_lang = ""
    code_lines: list[str] = []

    def flush_paragraph() -> None:
        if paragraph_lines:
            parts.append(paragraph(" ".join(paragraph_lines)))
            paragraph_lines.clear()

    def flush_table() -> None:
        if table_lines:
            parts.append(render_markdown_table(table_lines))
            table_lines.clear()

    def flush_list() -> None:
        if list_items:
            for item in list_items:
                parts.append(paragraph(clean_inline(item), style="ListParagraph", bullet=True))
            list_items.clear()

    for raw in lines:
        line = raw.rstrip()
        if line.startswith("```"):
            if in_code:
                if code_lang.startswith("diagram"):
                    name = code_lang.replace("diagram", "", 1).strip() or "architecture"
                    svg = diagram_svg(name)
                    width_px, height_px = svg_size(svg)
                    add_media(svg.encode("utf-8"), ".svg", width_px, height_px)
                else:
                    parts.append(paragraph("\n".join(code_lines), style="Code"))
                in_code = False
                code_lang = ""
                code_lines.clear()
            else:
                flush_paragraph()
                flush_table()
                flush_list()
                in_code = True
                code_lang = line.strip("`").strip()
            continue
        if in_code:
            code_lines.append(line)
            continue
        if not line:
            flush_paragraph()
            flush_table()
            flush_list()
            continue
        image = re.match(r"^!\[([^\]]*)\]\(([^)]+)\)$", line)
        if image:
            flush_paragraph()
            flush_table()
            flush_list()
            alt, src = image.group(1).strip(), image.group(2).strip()
            img_path = (ROOT / "docs" / src).resolve()
            if img_path.exists():
                width_px, height_px = image_size(img_path)
                add_media(img_path, img_path.suffix.lower(), width_px, height_px)
                if alt:
                    parts.append(paragraph(alt, style="Caption", align="center"))
            else:
                parts.append(paragraph(f"【图片占位：{alt or src}】", style="Caption"))
            continue
        heading = re.match(r"^(#{1,6})\s+(.+)$", line)
        if heading:
            flush_paragraph()
            flush_table()
            flush_list()
            level = min(len(heading.group(1)), 3)
            parts.append(paragraph(clean_inline(heading.group(2).strip()), style=f"Heading{level}"))
            continue
        if line.startswith("|") and line.endswith("|"):
            flush_paragraph()
            flush_list()
            table_lines.append(line)
            continue
        bullet = re.match(r"^-\s+(.+)$", line)
        if bullet:
            flush_paragraph()
            flush_table()
            list_items.append(bullet.group(1))
            continue
        paragraph_lines.append(clean_inline(line))

    flush_paragraph()
    flush_table()
    flush_list()
    return "\n".join(parts), rels, media


def collect_toc(markdown: str) -> list[tuple[int, str]]:
    items: list[tuple[int, str]] = []
    for line in markdown.splitlines():
        heading = re.match(r"^(#{1,3})\s+(.+)$", line)
        if heading:
            items.append((len(heading.group(1)), heading.group(2).strip()))
    return items


def diagram_svg(name: str) -> str:
    figure = render_diagram(name)
    match = re.search(r"(<svg\b.*?</svg>)", figure, flags=re.DOTALL)
    if not match:
        raise ValueError(f"Could not render diagram SVG: {name}")
    return match.group(1)


def svg_size(svg: str) -> tuple[int, int]:
    match = re.search(r'viewBox="[^"]*?([\d.]+)\s+([\d.]+)"', svg)
    if match:
        return int(float(match.group(1))), int(float(match.group(2)))
    return (900, 480)


def clean_inline(text: str) -> str:
    text = re.sub(r"`([^`]+)`", r"\1", text)
    text = re.sub(r"\*\*([^*]+)\*\*", r"\1", text)
    return text


def esc(text: str) -> str:
    return html.escape(text, quote=False)


def paragraph(
    text: str,
    style: str | None = None,
    align: str | None = None,
    bullet: bool = False,
    page_break: bool = False,
) -> str:
    props = []
    if style:
        props.append(f'<w:pStyle w:val="{style}"/>')
    if align:
        props.append(f'<w:jc w:val="{align}"/>')
    if bullet:
        props.append('<w:numPr><w:ilvl w:val="0"/><w:numId w:val="1"/></w:numPr>')
    ppr = f"<w:pPr>{''.join(props)}</w:pPr>" if props else ""
    if page_break:
        return "<w:p><w:r><w:br w:type=\"page\"/></w:r></w:p>"
    runs = []
    for index, part in enumerate(text.split("\n")):
        if index:
            runs.append("<w:r><w:br/></w:r>")
        runs.append(f"<w:r><w:t xml:space=\"preserve\">{esc(part)}</w:t></w:r>")
    return f"<w:p>{ppr}{''.join(runs)}</w:p>"


def render_table(rows: list[tuple[str, str]]) -> str:
    table_rows = []
    for key, value in rows:
        table_rows.append(
            "<w:tr>"
            f"<w:tc><w:p>{run(key)}</w:p></w:tc>"
            f"<w:tc><w:p>{run(value)}</w:p></w:tc>"
            "</w:tr>"
        )
    return table("".join(table_rows))


def render_markdown_table(lines: list[str]) -> str:
    rows = [[clean_inline(cell.strip()) for cell in line.strip("|").split("|")] for line in lines]
    if len(rows) >= 2 and all(re.fullmatch(r":?-{3,}:?", cell) for cell in rows[1]):
        rows = [rows[0], *rows[2:]]
    table_rows = []
    for row in rows:
        cells = "".join(f"<w:tc><w:p>{run(cell)}</w:p></w:tc>" for cell in row)
        table_rows.append(f"<w:tr>{cells}</w:tr>")
    return table("".join(table_rows))


def table(rows_xml: str) -> str:
    return (
        "<w:tbl>"
        "<w:tblPr><w:tblStyle w:val=\"TableGrid\"/><w:tblW w:w=\"0\" w:type=\"auto\"/>"
        "<w:tblBorders><w:top w:val=\"single\" w:sz=\"4\"/><w:left w:val=\"single\" w:sz=\"4\"/>"
        "<w:bottom w:val=\"single\" w:sz=\"4\"/><w:right w:val=\"single\" w:sz=\"4\"/>"
        "<w:insideH w:val=\"single\" w:sz=\"4\"/><w:insideV w:val=\"single\" w:sz=\"4\"/></w:tblBorders>"
        "</w:tblPr>"
        f"{rows_xml}</w:tbl>"
    )


def run(text: str) -> str:
    return f"<w:r><w:t xml:space=\"preserve\">{esc(text)}</w:t></w:r>"


def toc_field() -> str:
    return (
        "<w:p><w:r><w:fldChar w:fldCharType=\"begin\"/></w:r>"
        "<w:r><w:instrText xml:space=\"preserve\"> TOC \\o \"1-3\" \\h \\z \\u </w:instrText></w:r>"
        "<w:r><w:fldChar w:fldCharType=\"separate\"/></w:r>"
        "<w:r><w:t>右键更新目录</w:t></w:r>"
        "<w:r><w:fldChar w:fldCharType=\"end\"/></w:r></w:p>"
    )


def image_paragraph(rid: str, name: str, width_px: int, height_px: int) -> str:
    width_emu = 6_250_000
    height_emu = int(width_emu * height_px / max(width_px, 1))
    return f"""
<w:p>
  <w:pPr><w:jc w:val="center"/></w:pPr>
  <w:r><w:drawing><wp:inline distT="0" distB="0" distL="0" distR="0">
    <wp:extent cx="{width_emu}" cy="{height_emu}"/>
    <wp:docPr id="1" name="{esc(name)}"/>
    <a:graphic xmlns:a="{A_NS}"><a:graphicData uri="{PIC_NS}">
      <pic:pic xmlns:pic="{PIC_NS}">
        <pic:nvPicPr><pic:cNvPr id="0" name="{esc(name)}"/><pic:cNvPicPr/></pic:nvPicPr>
        <pic:blipFill><a:blip r:embed="{rid}" xmlns:r="{R_NS}"/><a:stretch><a:fillRect/></a:stretch></pic:blipFill>
        <pic:spPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="{width_emu}" cy="{height_emu}"/></a:xfrm><a:prstGeom prst="rect"><a:avLst/></a:prstGeom></pic:spPr>
      </pic:pic>
    </a:graphicData></a:graphic>
  </wp:inline></w:drawing></w:r>
</w:p>
"""


def image_size(path: Path) -> tuple[int, int]:
    with path.open("rb") as fh:
        header = fh.read(24)
    if header[:8] != b"\x89PNG\r\n\x1a\n":
        return (1200, 800)
    return struct.unpack(">II", header[16:24])


def write_docx(body: str, rels: list[str], media: list[tuple[Path | bytes, str]]) -> None:
    if REPORT_DOCX.exists():
        REPORT_DOCX.unlink()
    with zipfile.ZipFile(REPORT_DOCX, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", content_types(media))
        archive.writestr("_rels/.rels", package_rels())
        archive.writestr("word/document.xml", document_xml(body))
        archive.writestr("word/styles.xml", styles_xml())
        archive.writestr("word/numbering.xml", numbering_xml())
        archive.writestr("word/settings.xml", settings_xml())
        archive.writestr("word/_rels/document.xml.rels", document_rels(rels))
        for source, target in media:
            if isinstance(source, Path):
                archive.write(source, f"word/media/{target}")
            else:
                archive.writestr(f"word/media/{target}", source)


def content_types(media: list[tuple[Path | bytes, str]]) -> str:
    defaults = {
        "png": "image/png",
        "jpg": "image/jpeg",
        "jpeg": "image/jpeg",
        "svg": "image/svg+xml",
    }
    image_defaults = "".join(
        f'<Default Extension="{extension}" ContentType="{content_type}"/>'
        for extension, content_type in defaults.items()
        if any(target.lower().endswith(f".{extension}") for _, target in media)
    )
    return f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  {image_defaults}
  <Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
  <Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>
  <Override PartName="/word/numbering.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.numbering+xml"/>
  <Override PartName="/word/settings.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.settings+xml"/>
</Types>"""


def package_rels() -> str:
    return """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
</Relationships>"""


def document_rels(image_rels: list[str]) -> str:
    rels = [
        '<Relationship Id="rStyles" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>',
        '<Relationship Id="rNumbering" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/numbering" Target="numbering.xml"/>',
        '<Relationship Id="rSettings" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/settings" Target="settings.xml"/>',
        *image_rels,
    ]
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        + "".join(rels)
        + "</Relationships>"
    )


def document_xml(body: str) -> str:
    return f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="{W_NS}" xmlns:r="{R_NS}" xmlns:wp="{WP_NS}" xmlns:a="{A_NS}" xmlns:pic="{PIC_NS}">
  <w:body>
    {body}
    <w:sectPr><w:pgSz w:w="11906" w:h="16838"/><w:pgMar w:top="1021" w:right="907" w:bottom="1021" w:left="907"/></w:sectPr>
  </w:body>
</w:document>"""


def styles_xml() -> str:
    return f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:styles xmlns:w="{W_NS}">
  <w:style w:type="paragraph" w:default="1" w:styleId="Normal"><w:name w:val="Normal"/><w:pPr><w:spacing w:after="80" w:line="400" w:lineRule="auto"/><w:jc w:val="both"/></w:pPr><w:rPr><w:rFonts w:ascii="Microsoft YaHei" w:eastAsia="Microsoft YaHei"/><w:sz w:val="21"/></w:rPr></w:style>
  <w:style w:type="paragraph" w:styleId="Title"><w:name w:val="Title"/><w:rPr><w:rFonts w:eastAsia="Microsoft YaHei"/><w:b/><w:sz w:val="32"/></w:rPr></w:style>
  <w:style w:type="paragraph" w:styleId="Heading1"><w:name w:val="heading 1"/><w:basedOn w:val="Normal"/><w:pPr><w:outlineLvl w:val="0"/><w:spacing w:before="280" w:after="120"/><w:jc w:val="left"/></w:pPr><w:rPr><w:b/><w:sz w:val="28"/></w:rPr></w:style>
  <w:style w:type="paragraph" w:styleId="Heading2"><w:name w:val="heading 2"/><w:basedOn w:val="Normal"/><w:pPr><w:outlineLvl w:val="1"/><w:spacing w:before="220" w:after="90"/><w:jc w:val="left"/></w:pPr><w:rPr><w:b/><w:sz w:val="24"/></w:rPr></w:style>
  <w:style w:type="paragraph" w:styleId="Heading3"><w:name w:val="heading 3"/><w:basedOn w:val="Normal"/><w:pPr><w:outlineLvl w:val="2"/><w:spacing w:before="160" w:after="70"/><w:jc w:val="left"/></w:pPr><w:rPr><w:b/><w:sz w:val="22"/></w:rPr></w:style>
  <w:style w:type="paragraph" w:styleId="TOC1"><w:name w:val="toc 1"/><w:basedOn w:val="Normal"/><w:pPr><w:spacing w:after="80"/><w:ind w:left="0"/></w:pPr><w:rPr><w:sz w:val="22"/></w:rPr></w:style>
  <w:style w:type="paragraph" w:styleId="TOC2"><w:name w:val="toc 2"/><w:basedOn w:val="Normal"/><w:pPr><w:spacing w:after="60"/><w:ind w:left="360"/></w:pPr><w:rPr><w:sz w:val="21"/></w:rPr></w:style>
  <w:style w:type="paragraph" w:styleId="TOC3"><w:name w:val="toc 3"/><w:basedOn w:val="Normal"/><w:pPr><w:spacing w:after="40"/><w:ind w:left="720"/></w:pPr><w:rPr><w:sz w:val="20"/></w:rPr></w:style>
  <w:style w:type="paragraph" w:styleId="ListParagraph"><w:name w:val="List Paragraph"/><w:basedOn w:val="Normal"/><w:pPr><w:ind w:left="720"/></w:pPr></w:style>
  <w:style w:type="paragraph" w:styleId="Code"><w:name w:val="Code"/><w:basedOn w:val="Normal"/><w:rPr><w:rFonts w:ascii="Consolas" w:eastAsia="Consolas"/><w:sz w:val="18"/></w:rPr></w:style>
  <w:style w:type="paragraph" w:styleId="Caption"><w:name w:val="Caption"/><w:basedOn w:val="Normal"/><w:rPr><w:i/><w:color w:val="475569"/></w:rPr></w:style>
</w:styles>"""


def numbering_xml() -> str:
    return f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:numbering xmlns:w="{W_NS}">
  <w:abstractNum w:abstractNumId="0"><w:lvl w:ilvl="0"><w:start w:val="1"/><w:numFmt w:val="bullet"/><w:lvlText w:val="•"/><w:lvlJc w:val="left"/></w:lvl></w:abstractNum>
  <w:num w:numId="1"><w:abstractNumId w:val="0"/></w:num>
</w:numbering>"""


def settings_xml() -> str:
    return f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:settings xmlns:w="{W_NS}"><w:updateFields w:val="true"/></w:settings>"""


if __name__ == "__main__":
    main()
