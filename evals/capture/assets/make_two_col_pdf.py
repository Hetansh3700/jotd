"""Regenerate two-col.pdf — a dependency-free, byte-deterministic two-column PDF.

Left column carries the scene's must-phrases; the right column carries the
COLUMN TWO SENTINEL that the pdf-two-col scene forbids, keeping "the region
selection is the column selector" honest. Run from this directory:
python make_two_col_pdf.py
"""

from pathlib import Path

LEFT = [
    "The pulse enforces a strict interruption",
    "budget: at most three nudges per run and",
    "six per day. The vault runs three pulses",
    "per day by default, and every decision",
    "to stay silent is logged with a reason.",
    "Restraint is the product surface, not",
    "an afterthought bolted on at the end.",
]
RIGHT = [
    "COLUMN TWO SENTINEL. If this text shows",
    "up in a left-column grab, the capture",
    "bled across columns and the scene must",
    "fail: oranges bicycle lantern quartz.",
]


def text_block(x: int, lines: list[str]) -> str:
    body = f"BT /F1 12 Tf 16 TL {x} 730 Td\n"
    for i, line in enumerate(lines):
        escaped = line.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")
        body += f"({escaped}) Tj T*\n" if i < len(lines) - 1 else f"({escaped}) Tj\n"
    return body + "ET\n"


def main() -> None:
    # white page fill first: without it, rasterizers emit black text on a
    # TRANSPARENT background, which OCR engines composite on black and read as blank
    background = "1 1 1 rg 0 0 612 792 re f\n0 0 0 rg\n"
    stream = background + text_block(50, LEFT) + text_block(330, RIGHT)
    objects = [
        "<< /Type /Catalog /Pages 2 0 R >>",
        "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        "/Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
        "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        f"<< /Length {len(stream.encode())} >>\nstream\n{stream}endstream",
    ]
    out = b"%PDF-1.4\n"
    offsets = []
    for n, body in enumerate(objects, 1):
        offsets.append(len(out))
        out += f"{n} 0 obj\n{body}\nendobj\n".encode()
    xref_at = len(out)
    xref = f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n"
    xref += "".join(f"{off:010d} 00000 n \n" for off in offsets)
    trailer = f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref_at}\n%%EOF\n"
    out += xref.encode() + trailer.encode()
    (Path(__file__).parent / "two-col.pdf").write_bytes(out)
    print(f"wrote two-col.pdf ({len(out)} bytes)")


if __name__ == "__main__":
    main()
