"""Re-use the fonts already embedded in a PDF when text is moved or edited.

Embedded fonts are usually *subsets*: they only contain the glyphs the document
actually draws and often have no usable cmap, so they cannot be loaded as a normal
font.  They can still be used through the PDF itself: the ``/ToUnicode`` CMap (or a
standard simple-font encoding) maps byte codes to characters, and the page's content
streams tell which codes are really drawn - i.e. which glyphs exist in the subset.
Writing those byte codes with the page's own font resource reproduces the original
typeface exactly.

Build a :class:`PageFontIndex` *before* removing the old text (the redaction erases
the only drawing of some codes, but their glyphs stay in the font), then call
:meth:`PageFontIndex.write`.  It returns ``False`` - and writes nothing - whenever the
text cannot be written faithfully, so callers fall back to a substitute font.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Iterator, Optional, Sequence

import pymupdf

_SUBSET = re.compile(r"^[A-Za-z0-9]{6}\+")  # Skia/Chrome write lower-case tags
_WS = b" \t\r\n\x0c\x00"
_DELIM = b"()<>[]{}/%"


def base_font_name(name: str) -> str:
    """Strip the ``ABCDEF+`` subset tag: 'ABCDEF+IPAPGothic' -> 'IPAPGothic'."""
    return _SUBSET.sub("", name or "")


def _truncated_match(embedded: str, reported: str) -> bool:
    """MuPDF keeps at most 31 bytes of '/BaseFont' (subset tag included), so a long
    name such as 'ABCDEF+Droid Sans Fallback Regular' is reported as 'Droid Sans
    Fallback Regu'.  Only names cut at exactly that length may match by prefix -
    otherwise 'HelveticaNeue' would also match 'HelveticaNeue-Bold'."""
    b = base_font_name(reported)
    return len(b.encode()) in (24, 31) and base_font_name(embedded).startswith(b) \
        and base_font_name(embedded) != b


def same_family(embedded: str, reported: str) -> bool:
    return base_font_name(embedded) == base_font_name(reported) or _truncated_match(embedded, reported)


# --------------------------------------------------------------------------- CMaps
def _utf16(hexstr: str) -> str:
    try:
        return bytes.fromhex(hexstr).decode("utf-16-be")
    except (ValueError, UnicodeDecodeError):
        return ""


def parse_tounicode(data: bytes) -> dict[int, str]:
    """``code -> text`` from a ToUnicode CMap stream (bfchar and bfrange)."""
    text = data.decode("latin-1")
    out: dict[int, str] = {}
    for block in re.findall(r"beginbfchar(.*?)endbfchar", text, re.S):
        for src, dst in re.findall(r"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]*)>", block):
            out[int(src, 16)] = _utf16(dst)
    for block in re.findall(r"beginbfrange(.*?)endbfrange", text, re.S):
        for lo, hi, rest in re.findall(r"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>\s*(\[[^\]]*\]|<[0-9A-Fa-f]*>)",
                                       block):
            lo_i, hi_i = int(lo, 16), int(hi, 16)
            if hi_i - lo_i > 0xFFFF:
                continue
            if rest.startswith("["):
                for i, dst in enumerate(re.findall(r"<([0-9A-Fa-f]*)>", rest)):
                    out[lo_i + i] = _utf16(dst)
            else:
                start = _utf16(rest[1:-1])
                if not start:
                    continue
                head, last = start[:-1], ord(start[-1])
                for i in range(hi_i - lo_i + 1):
                    if last + i <= 0x10FFFF:
                        out[lo_i + i] = head + chr(last + i)
    return out


_SIMPLE_ENCODINGS = {"WinAnsiEncoding": "cp1252", "MacRomanEncoding": "mac_roman"}


# ------------------------------------------------------------------ content parsing
def _tokens(data: bytes) -> Iterator[tuple[str, object]]:
    """Tokenise a content stream: yields ('op', name) and ('val', operand) pairs.
    Arrays become Python lists; strings are bytes; names are '/Name' strings."""
    i, n = 0, len(data)
    stack: list[list] = []

    def emit(value):
        if stack:
            stack[-1].append(value)
            return None
        return ("val", value)

    while i < n:
        c = data[i]
        if c in _WS:
            i += 1
            continue
        if c == 0x25:  # % comment
            while i < n and data[i] not in b"\r\n":
                i += 1
            continue
        if c == 0x28:  # ( literal string
            depth, i, buf = 1, i + 1, bytearray()
            while i < n and depth:
                ch = data[i]
                if ch == 0x5C and i + 1 < n:  # backslash
                    nxt = data[i + 1]
                    esc = {0x6E: 10, 0x72: 13, 0x74: 9, 0x62: 8, 0x66: 12}.get(nxt)
                    if esc is not None:
                        buf.append(esc)
                        i += 2
                    elif 0x30 <= nxt <= 0x37:
                        j = i + 1
                        while j < n and j < i + 4 and 0x30 <= data[j] <= 0x37:
                            j += 1
                        buf.append(int(data[i + 1:j], 8) & 0xFF)
                        i = j
                    elif nxt in b"\r\n":
                        i += 2
                        if nxt == 0x0D and i < n and data[i] == 0x0A:
                            i += 1
                    else:
                        buf.append(nxt)
                        i += 2
                    continue
                if ch == 0x28:
                    depth += 1
                elif ch == 0x29:
                    depth -= 1
                    if depth == 0:
                        i += 1
                        break
                buf.append(ch)
                i += 1
            tok = emit(bytes(buf))
            if tok:
                yield tok
            continue
        if c == 0x3C:  # < hex string or <<
            if i + 1 < n and data[i + 1] == 0x3C:
                i += 2
                stack.append([])  # dictionaries are irrelevant: collect and drop
                continue
            j = data.find(b">", i)
            j = n if j < 0 else j
            hexs = re.sub(rb"[^0-9A-Fa-f]", b"", data[i + 1:j])
            if len(hexs) % 2:
                hexs += b"0"
            i = j + 1
            tok = emit(bytes.fromhex(hexs.decode()))
            if tok:
                yield tok
            continue
        if c == 0x3E and i + 1 < n and data[i + 1] == 0x3E:  # >>
            i += 2
            if stack:
                d = stack.pop()
                tok = emit(("dict", d))
                if tok:
                    yield tok
            continue
        if c == 0x5B:  # [
            stack.append([])
            i += 1
            continue
        if c == 0x5D:  # ]
            i += 1
            if stack:
                arr = stack.pop()
                tok = emit(arr)
                if tok:
                    yield tok
            continue
        if c == 0x2F:  # /Name
            j = i + 1
            while j < n and data[j] not in _WS and data[j] not in _DELIM:
                j += 1
            name = re.sub(rb"#([0-9A-Fa-f]{2})", lambda m: bytes([int(m.group(1), 16)]), data[i + 1:j])
            i = j
            tok = emit("/" + name.decode("latin-1"))
            if tok:
                yield tok
            continue
        if c in b"{}":
            i += 1
            continue
        j = i
        while j < n and data[j] not in _WS and data[j] not in _DELIM:
            j += 1
        word = data[i:j].decode("latin-1")
        i = j if j > i else i + 1
        if stack:
            stack[-1].append(word)
            continue
        if word == "ID":  # inline image data: skip to EI
            m = re.compile(rb"[\s\x00]EI(?=[\s\x00]|$)").search(data, i + 1)
            i = m.end() if m else n
            continue
        if re.fullmatch(r"[+-]?(\d+\.?\d*|\.\d+)", word) or word in ("true", "false", "null"):
            yield ("val", word)
        else:
            yield ("op", word)


def drawn_strings(content: bytes, with_mode: bool = False) -> Iterator[tuple]:
    """Yield (font resource name, string bytes) for every text-showing operator;
    with ``with_mode`` also whether it is visible (render mode Tr != 3)."""
    font: Optional[str] = None
    mode = 0
    saved: list[tuple[Optional[str], int]] = []
    operands: list = []
    for kind, value in _tokens(content):
        if kind == "val":
            operands.append(value)
            continue
        op = value
        strings: list[bytes] = []
        if op == "Tf" and len(operands) >= 2 and isinstance(operands[-2], str):
            font = operands[-2][1:]
        elif op == "Tr" and operands:
            try:
                mode = int(float(operands[-1]))
            except (TypeError, ValueError):
                pass
        elif op == "q":
            saved.append((font, mode))
        elif op == "Q":
            font, mode = saved.pop() if saved else (font, mode)
        elif op in ("Tj", "'", '"') and operands and isinstance(operands[-1], bytes):
            strings = [operands[-1]]
        elif op == "TJ" and operands and isinstance(operands[-1], list):
            strings = [part for part in operands[-1] if isinstance(part, bytes)]
        if font:
            for data in strings:
                yield (font, data, mode != 3) if with_mode else (font, data)
        operands = []


# ----------------------------------------------------------------------- font info
@dataclass
class _Font:
    res: str            # resource name used in the content stream, e.g. 'F1.1'
    xref: int
    family: str         # base font name without subset tag
    width: int          # bytes per code (1 simple font, 2 Identity-H)
    to_text: dict[int, str]
    subset: bool        # glyphs limited to the codes actually drawn
    names: tuple[str, ...] = ()   # every name MuPDF may report for this font
    used: set[int] = field(default_factory=set)
    visible: bool = False         # drawn at least once with a visible render mode
    invisible: bool = False       # drawn with Tr 3 (e.g. an OCR text layer)

    def matches(self, reported: str) -> bool:
        return any(base_font_name(n) == base_font_name(reported) for n in self.names)

    def matches_truncated(self, reported: str) -> bool:
        return any(_truncated_match(n, reported) for n in self.names)

    def codes(self, data: bytes) -> list[int]:
        if self.width == 1:
            return list(data)
        return [int.from_bytes(data[k:k + 2], "big") for k in range(0, len(data) - 1, 2)]


def _font_from_xref(doc: pymupdf.Document, res: str, xref: int, basefont: str,
                    embedded: bool = True) -> Optional[_Font]:
    subtype = doc.xref_get_key(xref, "Subtype")[1]
    tu = doc.xref_get_key(xref, "ToUnicode")
    to_text: dict[int, str] = {}
    if tu[0] == "xref":
        try:
            to_text = parse_tounicode(doc.xref_stream(int(tu[1].split()[0])) or b"")
        except Exception:  # noqa: BLE001
            to_text = {}
    if subtype == "/Type0":
        enc = doc.xref_get_key(xref, "Encoding")[1]
        if enc != "/Identity-H" or not to_text:
            return None  # vertical / legacy CJK CMaps are not handled
        width = 2
    elif subtype in ("/TrueType", "/Type1", "/MMType1"):
        width = 1
        if not to_text:
            kind, enc = doc.xref_get_key(xref, "Encoding")
            codec = _SIMPLE_ENCODINGS.get(enc.lstrip("/")) if kind == "name" else None
            if codec is None:
                return None
            for code in range(32, 256):
                try:
                    to_text[code] = bytes([code]).decode(codec)
                except UnicodeDecodeError:
                    pass
    else:
        return None  # Type3 etc.
    names = [basefont]
    if subtype == "/Type0":
        # CID fonts are often named 'CIDFont-CMap' ('ABCDEF+Mincho-Identity-H') while
        # MuPDF reports the descendant font's own name ('Mincho')
        kind, val = doc.xref_get_key(xref, "DescendantFonts")
        try:
            if kind == "array":
                dxref = int(val.strip("[]").split()[0])
                names.append(doc.xref_get_key(dxref, "BaseFont")[1].lstrip("/"))
            elif kind == "xref":
                arr = doc.xref_object(int(val.split()[0]))
                m = re.search(r"(\d+)\s+0\s+R", arr)
                if m:
                    names.append(doc.xref_get_key(int(m.group(1)), "BaseFont")[1].lstrip("/"))
        except Exception:  # noqa: BLE001
            pass
        for suffix in ("-Identity-H", "-UniJIS-UTF16-H"):
            if basefont.endswith(suffix):
                names.append(basefont[: -len(suffix)])
    names = [re.sub(r"#([0-9A-Fa-f]{2})", lambda m: chr(int(m.group(1), 16)), n) for n in names if n]
    # Any embedded font program may be a subset even without the 'ABCDEF+' tag, so only
    # codes that are really drawn count as available; fonts that are not embedded
    # (standard 14) are rendered by the viewer and can show every encoded character.
    subset = embedded or bool(_SUBSET.match(basefont))
    return _Font(res=res, xref=xref, family=base_font_name(basefont), width=width,
                 to_text=to_text, subset=subset, names=tuple(dict.fromkeys(names)))


def _contents(page: pymupdf.Page) -> bytes:
    try:
        return page.read_contents()
    except Exception:  # noqa: BLE001
        return b""


def _drawn_codes(doc: pymupdf.Document, page: pymupdf.Page, fonts: dict[int, "_Font"]) -> None:
    """Add every code drawn on ``page`` - in its content streams and in its form
    XObjects, which have their own font resource names - to ``fonts[xref].used``."""
    names: dict[int, dict[str, int]] = {}       # referencer (0 = page) -> res name -> font xref
    for xref, _e, _t, _b, res, _enc, referencer in page.get_fonts(full=True):
        if xref in fonts and res:
            names.setdefault(referencer, {})[res] = xref
    for referencer, mapping in names.items():
        if referencer == 0:
            content = _contents(page)
        else:
            try:
                content = doc.xref_stream(referencer) or b""
            except Exception:  # noqa: BLE001
                continue
        for res, data, visible in drawn_strings(content, with_mode=True):
            xref = mapping.get(res)
            if xref is not None:
                f = fonts[xref]
                if visible:
                    f.used.update(f.codes(data))
                    f.visible = True
                else:
                    f.invisible = True


class PageFontIndex:
    """Which characters can be drawn with which embedded font of one page."""

    def __init__(self, page: pymupdf.Page):
        self.doc = page.parent
        self.pno = page.number
        self.fonts: dict[int, _Font] = {}            # by font xref
        page_names: dict[int, str] = {}
        for xref, ext, _typ, basefont, res, _enc, referencer in page.get_fonts(full=True):
            if referencer == 0 and res:
                page_names.setdefault(xref, res)
            if xref in self.fonts:
                continue
            f = _font_from_xref(self.doc, res, xref, basefont, embedded=ext not in ("n/a", ""))
            if f is not None:
                self.fonts[xref] = f
        for xref, f in self.fonts.items():
            # fonts only used inside form XObjects get a page-level name when written
            f.res = page_names.get(xref) or f"EzF{xref}"
        self._scanned_others = False
        _drawn_codes(self.doc, page, self.fonts)

    def _scan_other_pages(self) -> None:
        """Glyphs of a shared subset font may only be drawn on other pages."""
        if self._scanned_others:
            return
        self._scanned_others = True
        wanted = {x: f for x, f in self.fonts.items() if f.subset}
        if not wanted:
            return
        for pno in range(self.doc.page_count):
            if pno != self.pno:
                _drawn_codes(self.doc, self.doc[pno], wanted)

    # ------------------------------------------------------------------ queries
    def _candidates(self, family: str) -> list[_Font]:
        """Fonts carrying the reported name: exact matches only, or - when MuPDF cut
        the name short - the fonts it may stand for.  Fonts that are only ever drawn
        invisibly (OCR layers, often with empty glyphs) are never reused."""
        usable = [f for f in self.fonts.values() if not (f.invisible and not f.visible)]
        exact = [f for f in usable if f.matches(family)]
        return exact or [f for f in usable if f.matches_truncated(family)]

    def _lookup(self, family: str) -> dict[str, tuple[_Font, int]]:
        table: dict[str, tuple[_Font, int]] = {}
        for f in self._candidates(family):
            for code, text in f.to_text.items():
                if len(text) != 1:
                    continue
                if f.subset and code not in f.used:
                    continue  # glyph not in the subset
                prev = table.get(text)
                # several codes for one character (variants): prefer one really drawn
                if prev is None or (prev[1] not in prev[0].used and code in f.used):
                    table[text] = (f, code)
        return table

    def plan(self, family: str, text: str) -> Optional[list[tuple[Optional[_Font], bytes]]]:
        """Runs of (font, encoded bytes) for ``text`` or None if a glyph is missing."""
        if not text or not self._candidates(family):
            return None
        table = self._lookup(family)
        text = self._equivalents(text, table)
        if any(ch not in table for ch in text):
            self._scan_other_pages()
            table = self._lookup(family)
            text = self._equivalents(text, table)
            # a space without glyph is emulated with a gap; anything else is fatal
            if any(ch not in table and not ch.isspace() for ch in text):
                return None
        if all(ch not in table for ch in text):
            return None
        runs: list[tuple[Optional[_Font], bytes]] = []
        for ch in text:
            if ch not in table:   # a space with no glyph: handled by the caller as a gap
                runs.append((None, b" "))
                continue
            f, code = table[ch]
            raw = code.to_bytes(f.width, "big")
            if runs and runs[-1][0] is f:
                runs[-1] = (f, runs[-1][1] + raw)
            else:
                runs.append((f, raw))
        return runs

    @staticmethod
    def _equivalents(text: str, table: dict) -> str:
        """Use a normal space for a missing no-break space and vice versa."""
        swap = {"\u00a0": " ", " ": "\u00a0", "\u3000": " "}
        return "".join(swap[ch] if ch not in table and ch in swap and swap[ch] in table else ch
                       for ch in text)

    def can_write(self, family: str, text: str, page: Optional[pymupdf.Page] = None) -> bool:
        if page is not None and (page.rotation or page.number != self.pno):
            return False   # the raw writer only handles unrotated pages
        return "\n" not in text and self.plan(family, text) is not None

    def write(self, page: pymupdf.Page, origin: pymupdf.Point, text: str, family: str,
              size: float, color: Sequence[float] = (0, 0, 0)) -> bool:
        """Draw ``text`` (one line) with the page's own font.  False = nothing written."""
        if "\n" in text or page.rotation or page.number != self.pno:
            return False
        runs = self.plan(family, text)
        if runs is None:
            return False
        space_w = 0.25 * size
        ops = []
        first = next(f for f, _ in runs if f is not None)
        ops.append(f"/{first.res} {size:.3f} Tf")
        cur: Optional[_Font] = first
        for f, raw in runs:
            if f is None:  # missing space glyph: shift by a quarter em
                ops.append(f"[{-space_w / size * 1000:.1f}] TJ")
                continue
            if f is not cur:
                ops.append(f"/{f.res} {size:.3f} Tf")
                cur = f
            ops.append(f"<{raw.hex()}> Tj")
        fonts_used = list({id(f): f for f, _raw in runs if f is not None}.values())
        try:
            for f in fonts_used:
                _ensure_font_resource(page, f.res, f.xref)
        except (ValueError, RuntimeError):  # inherited / clashing resources: use a substitute
            return False
        p = origin * ~page.transformation_matrix
        r, g, b = (tuple(color) + (0, 0, 0))[:3]
        stream = (f"q BT {r:.4f} {g:.4f} {b:.4f} rg 0 Tr 0 Tc 0 Tw 100 Tz 0 Ts "
                  f"1 0 0 1 {p.x:.3f} {p.y:.3f} Tm " + " ".join(ops) + " ET Q\n")
        _append_content(page, stream.encode("latin-1"))
        return True


def _ensure_font_resource(page: pymupdf.Page, res: str, xref: int) -> None:
    """Make sure the page's /Resources/Font has ``res`` -> ``xref`` (redaction rewrites
    the resources, and fonts used only inside form XObjects are not listed at all).
    Indirect /Resources or /Font dictionaries are followed and edited in place; raises
    when the resources are only inherited, so the caller uses a substitute font."""
    doc = page.parent
    ref = f"{xref} 0 R"
    kind, val = doc.xref_get_key(page.xref, "Resources")
    if kind == "xref":
        owner, key = int(val.split()[0]), "Font"
    elif kind == "dict":
        owner, key = page.xref, "Resources/Font"
    else:
        raise ValueError("inherited page resources")
    fkind, fval = doc.xref_get_key(owner, key)
    if fkind == "xref":
        fx = int(fval.split()[0])
        cur = doc.xref_get_key(fx, res)
        if cur[0] == "null":
            doc.xref_set_key(fx, res, ref)
        elif cur[1] != ref:
            raise ValueError(f"font name {res} taken")
        return
    cur = doc.xref_get_key(owner, f"{key}/{res}")
    if cur[0] == "null":
        doc.xref_set_key(owner, f"{key}/{res}", ref)
    elif cur[1] != ref:
        raise ValueError(f"font name {res} taken")


def _append_content(page: pymupdf.Page, data: bytes) -> None:
    doc = page.parent
    if not page.is_wrapped:
        page.wrap_contents()
    xref = doc.get_new_xref()
    doc.update_object(xref, "<<>>")
    doc.update_stream(xref, data)
    refs = page.get_contents() + [xref]
    doc.xref_set_key(page.xref, "Contents", "[" + " ".join(f"{x} 0 R" for x in refs) + "]")
