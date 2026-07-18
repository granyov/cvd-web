"""Извлечение текстового слоя из PDF средствами stdlib.

Рассчитан на типовые PDF, которые выгружают пациенты из ЕМИАС.ИНФО и mos.ru:
документы, сгенерированные печатью из браузера или reporting-движками
(Type0-шрифты с Identity-H и ToUnicode CMap, потоки FlateDecode).
Сканы без текстового слоя не распознаются — это сообщается вызывающему коду.

Парсер сознательно консервативен: любые непонятные конструкции пропускаются,
цель — достать читаемый текст, а не полная поддержка спецификации PDF.
"""
from __future__ import annotations

import re
import zlib
from dataclasses import dataclass, field


MAX_PDF_BYTES = 20 * 1024 * 1024
MAX_TEXT_CHARS = 200_000


class PDFTextError(Exception):
    pass


_OBJ_RE = re.compile(rb"(\d+)\s+(\d+)\s+obj\b(.*?)endobj", re.S)
_STREAM_RE = re.compile(rb"stream\r?\n(.*?)\r?\nendstream", re.S)
_HEX_ITEM_RE = re.compile(rb"<([0-9A-Fa-f\s]*)>")
_BFCHAR_RE = re.compile(rb"beginbfchar(.*?)endbfchar", re.S)
_BFRANGE_RE = re.compile(rb"beginbfrange(.*?)endbfrange", re.S)
_TOUNICODE_REF_RE = re.compile(rb"/ToUnicode\s+(\d+)\s+\d+\s+R")
_FONT_RES_RE = re.compile(rb"/(\w+)\s+(\d+)\s+\d+\s+R")
_FONT_DICT_RE = re.compile(rb"/Font\s*<<(.*?)>>", re.S)
_CONTENTS_REF_RE = re.compile(rb"/Contents\s+(?:\[(.*?)\]|(\d+)\s+\d+\s+R)", re.S)
_REF_RE = re.compile(rb"(\d+)\s+\d+\s+R")


@dataclass
class _PdfObject:
    number: int
    raw: bytes
    stream: bytes | None = None
    decoded: bytes | None = field(default=None, repr=False)


def _decode_stream(raw_dict: bytes, stream: bytes) -> bytes | None:
    if b"/FlateDecode" in raw_dict:
        try:
            return zlib.decompress(stream)
        except zlib.error:
            try:
                return zlib.decompressobj().decompress(stream)
            except zlib.error:
                return None
    if b"/Filter" not in raw_dict:
        return stream
    # Прочие фильтры (DCTDecode-картинки и т.п.) текст не содержат.
    return None


def _parse_objects(data: bytes) -> dict[int, _PdfObject]:
    objects: dict[int, _PdfObject] = {}
    for match in _OBJ_RE.finditer(data):
        number = int(match.group(1))
        body = match.group(3)
        stream_match = _STREAM_RE.search(body)
        raw_dict = body[: stream_match.start()] if stream_match else body
        obj = _PdfObject(number=number, raw=raw_dict)
        if stream_match:
            obj.stream = stream_match.group(1)
            obj.decoded = _decode_stream(raw_dict, stream_match.group(1))
        objects[number] = obj
    return objects


def _parse_tounicode_cmap(cmap: bytes) -> dict[int, str]:
    mapping: dict[int, str] = {}

    def hex_to_int(chunk: bytes) -> int:
        return int(re.sub(rb"\s", b"", chunk) or b"0", 16)

    def hex_to_text(chunk: bytes) -> str:
        cleaned = re.sub(rb"\s", b"", chunk)
        if not cleaned:
            return ""
        raw = bytes.fromhex(cleaned.decode("ascii"))
        try:
            return raw.decode("utf-16-be")
        except UnicodeDecodeError:
            return ""

    for block in _BFCHAR_RE.findall(cmap):
        items = _HEX_ITEM_RE.findall(block)
        for src, dst in zip(items[0::2], items[1::2]):
            mapping[hex_to_int(src)] = hex_to_text(dst)

    for block in _BFRANGE_RE.findall(cmap):
        pos = 0
        while True:
            triple = _HEX_ITEM_RE.search(block, pos)
            if not triple:
                break
            second = _HEX_ITEM_RE.search(block, triple.end())
            if not second:
                break
            # Третий элемент: либо <hex>, либо массив [<hex> <hex> ...]
            rest = block[second.end():].lstrip()
            if rest.startswith(b"["):
                end = rest.find(b"]")
                array_body = rest[1:end if end != -1 else len(rest)]
                targets = [_ for _ in _HEX_ITEM_RE.findall(array_body)]
                start_code = hex_to_int(triple.group(1))
                for offset, target in enumerate(targets):
                    mapping[start_code + offset] = hex_to_text(target)
                pos = second.end() + (end + 1 if end != -1 else len(rest))
            else:
                third = _HEX_ITEM_RE.search(block, second.end())
                if not third:
                    break
                start_code = hex_to_int(triple.group(1))
                end_code = hex_to_int(second.group(1))
                base_target = re.sub(rb"\s", b"", third.group(1))
                if base_target and end_code - start_code < 65536:
                    base_value = int(base_target, 16)
                    width = len(base_target)
                    for code in range(start_code, end_code + 1):
                        target_hex = format(base_value + code - start_code, f"0{width}x").encode("ascii")
                        mapping[code] = hex_to_text(target_hex)
                pos = third.end()
    return mapping


def _font_maps(objects: dict[int, _PdfObject]) -> dict[bytes, dict[int, str]]:
    """Имя шрифта в ресурсах страницы -> CID->Unicode отображение."""
    fonts: dict[bytes, dict[int, str]] = {}
    for obj in objects.values():
        for font_block in _FONT_DICT_RE.findall(obj.raw):
            for name, ref in _FONT_RES_RE.findall(font_block):
                font_obj = objects.get(int(ref))
                if font_obj is None:
                    continue
                tounicode_ref = _TOUNICODE_REF_RE.search(font_obj.raw)
                cmap: dict[int, str] = {}
                if tounicode_ref:
                    cmap_obj = objects.get(int(tounicode_ref.group(1)))
                    if cmap_obj is not None and cmap_obj.decoded:
                        cmap = _parse_tounicode_cmap(cmap_obj.decoded)
                key = b"/" + name
                if cmap or key not in fonts:
                    fonts[key] = cmap
    return fonts


_STRING_TOKEN_RE = re.compile(
    rb"\((?P<literal>(?:\\.|[^\\()])*)\)|<(?P<hex>[0-9A-Fa-f\s]*)>|(?P<op>Tf|TJ|Tj|T\*|Td|TD|Tm|'|\")|/(?P<name>[A-Za-z0-9]+)"
)

_LITERAL_ESCAPES = {
    b"n": b"\n", b"r": b"\r", b"t": b"\t", b"b": b"\b", b"f": b"\f",
    b"(": b"(", b")": b")", b"\\": b"\\",
}


def _decode_literal(raw: bytes) -> bytes:
    out = bytearray()
    i = 0
    while i < len(raw):
        ch = raw[i:i + 1]
        if ch == b"\\" and i + 1 < len(raw):
            nxt = raw[i + 1:i + 2]
            if nxt in _LITERAL_ESCAPES:
                out += _LITERAL_ESCAPES[nxt]
                i += 2
                continue
            if nxt.isdigit():
                octal = raw[i + 1:i + 4]
                digits = re.match(rb"[0-7]{1,3}", octal)
                if digits:
                    out.append(int(digits.group(0), 8) & 0xFF)
                    i += 1 + len(digits.group(0))
                    continue
            i += 2
            continue
        out += ch
        i += 1
    return bytes(out)


def _decode_with_cmap(codes: bytes, cmap: dict[int, str], two_byte: bool) -> str:
    if two_byte:
        pairs = [codes[i:i + 2] for i in range(0, len(codes) - len(codes) % 2, 2)]
        return "".join(cmap.get(int.from_bytes(pair, "big"), "") for pair in pairs)
    return "".join(cmap.get(byte, "") for byte in codes)


def _decode_simple(codes: bytes) -> str:
    # Простые шрифты без ToUnicode: пробуем cp1251 (частый случай для кириллицы), затем latin-1.
    for encoding in ("cp1251", "latin-1"):
        try:
            return codes.decode(encoding)
        except UnicodeDecodeError:
            continue
    return codes.decode("latin-1", errors="ignore")


def _extract_content_text(content: bytes, fonts: dict[bytes, dict[int, str]]) -> str:
    parts: list[str] = []
    current_cmap: dict[int, str] = {}
    pending_font: bytes | None = None

    def emit(codes: bytes, is_hex: bool) -> None:
        if current_cmap:
            two_byte = max(current_cmap, default=0) > 255
            decoded = _decode_with_cmap(codes, current_cmap, two_byte)
            if not decoded and not is_hex:
                decoded = _decode_simple(codes)
            parts.append(decoded)
        else:
            parts.append(_decode_simple(codes))

    for match in _STRING_TOKEN_RE.finditer(content):
        if match.group("name") is not None:
            pending_font = b"/" + match.group("name")
            continue
        op = match.group("op")
        if op == b"Tf":
            if pending_font is not None:
                current_cmap = fonts.get(pending_font, {})
            continue
        if op in (b"T*", b"Td", b"TD", b"Tm"):
            if parts and not parts[-1].endswith("\n"):
                parts.append("\n")
            continue
        if op in (b"'", b'"'):
            if parts and not parts[-1].endswith("\n"):
                parts.append("\n")
            continue
        if match.group("literal") is not None:
            emit(_decode_literal(match.group("literal")), is_hex=False)
        elif match.group("hex") is not None:
            cleaned = re.sub(rb"\s", b"", match.group("hex"))
            if len(cleaned) % 2:
                cleaned += b"0"
            try:
                emit(bytes.fromhex(cleaned.decode("ascii")), is_hex=True)
            except ValueError:
                continue
    return "".join(parts)


def _content_objects(objects: dict[int, _PdfObject]) -> list[bytes]:
    """Content-стримы страниц в порядке их упоминания в /Contents."""
    ordered: list[bytes] = []
    seen: set[int] = set()
    for obj in objects.values():
        if b"/Type" in obj.raw and b"/Page" in obj.raw and b"/Pages" not in obj.raw:
            contents = _CONTENTS_REF_RE.search(obj.raw)
            if not contents:
                continue
            refs = _REF_RE.findall(contents.group(1) or contents.group(2) or b"")
            if contents.group(2):
                refs = [contents.group(2)]
            for ref in refs:
                number = int(ref)
                target = objects.get(number)
                if target is not None and target.decoded and number not in seen:
                    seen.add(number)
                    ordered.append(target.decoded)
    if ordered:
        return ordered
    # Fallback: страницы не распознаны — берём все стримы с текстовыми операторами.
    return [
        obj.decoded
        for obj in objects.values()
        if obj.decoded and (b"Tj" in obj.decoded or b"TJ" in obj.decoded)
    ]


def _normalize_text(text: str) -> str:
    text = text.replace("\x00", "")
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in text.splitlines()]
    cleaned: list[str] = []
    for line in lines:
        if line:
            cleaned.append(line)
        elif cleaned and cleaned[-1] != "":
            cleaned.append("")
    return "\n".join(cleaned).strip()


def extract_pdf_text(data: bytes) -> dict[str, object]:
    """Достаёт текстовый слой PDF. Возвращает {text, pages, has_text_layer}."""
    if not data.startswith(b"%PDF-"):
        raise PDFTextError("Файл не является PDF")
    if len(data) > MAX_PDF_BYTES:
        raise PDFTextError("PDF больше 20 МБ")

    objects = _parse_objects(data)
    if not objects:
        raise PDFTextError("Не удалось разобрать структуру PDF")

    fonts = _font_maps(objects)
    pages = sum(
        1
        for obj in objects.values()
        if b"/Type" in obj.raw and b"/Page" in obj.raw and b"/Pages" not in obj.raw
    )

    chunks = [_extract_content_text(content, fonts) for content in _content_objects(objects)]
    text = _normalize_text("\n".join(chunks))[:MAX_TEXT_CHARS]

    meaningful = re.sub(r"\s", "", text)
    return {
        "text": text,
        "pages": pages or len(chunks),
        "has_text_layer": len(meaningful) >= 25,
    }
