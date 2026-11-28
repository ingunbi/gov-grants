"""기업마당 공식 첨부에서 요약에 필요한 텍스트를 추출한다."""
from __future__ import annotations

import io
import re
import subprocess
import zipfile
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from defusedxml import ElementTree
from defusedxml.common import DefusedXmlException

MAX_BYTES = 12 * 1024 * 1024
MAX_XML_BYTES = 4 * 1024 * 1024
MAX_LENGTH = 8000
HOSTS = {"bizinfo.go.kr", "www.bizinfo.go.kr"}
SECTION = re.compile(r"Contents/section(\d+)\.xml")
PARAGRAPH = "{http://www.hancom.co.kr/hwpml/2011/paragraph}"


def official_url(url: str) -> bool:
    parsed = urlsplit(url)
    return (parsed.scheme == "https" and parsed.hostname in HOSTS
            and parsed.port in (None, 443) and parsed.username is None)


class OfficialRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not official_url(newurl):
            raise ValueError("공식 첨부 호스트 밖으로 이동")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def download(url: str) -> bytes:
    if not official_url(url):
        raise ValueError("공식 첨부 주소가 아님")
    request = Request(url, headers={"User-Agent": "gov-grants/1.0"})
    with build_opener(OfficialRedirect()).open(request, timeout=8) as response:
        data = response.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise ValueError("첨부 용량 초과")
    return data


def hwpx_text(data: bytes) -> str:
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        sections = [(int(match[1]), entry) for entry in archive.infolist()
                    if (match := SECTION.fullmatch(entry.filename))]
        if len(sections) > 32 or sum(entry.file_size for _, entry in sections) > MAX_XML_BYTES:
            raise ValueError("HWPX 본문 용량 초과")
        lines = []
        for _, entry in sorted(sections, key=lambda section: section[0]):
            root = ElementTree.fromstring(archive.read(entry), forbid_dtd=True)
            for paragraph in root.iter(PARAGRAPH + "p"):
                # 표 셀 안의 문단은 별도로 순회하므로 현재 문단의 run만 읽는다.
                line = "".join(node.text or "" for node in paragraph.findall(
                    PARAGRAPH + "run/" + PARAGRAPH + "t"))
                if line.strip():
                    lines.append(line)
    return "\n".join(lines)


def extract(data: bytes, kind: str) -> str:
    if kind == "pdf":
        if not data.startswith(b"%PDF-"):
            raise ValueError("PDF 형식이 아님")
        result = subprocess.run(
            ["pdftotext", "-enc", "UTF-8", "-l", "16", "-layout", "-", "-"],
            input=data, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            check=True, timeout=10,
        )
        raw = result.stdout.decode("utf-8", errors="replace")
    elif kind == "hwpx":
        raw = hwpx_text(data)
    else:
        raise ValueError("지원하지 않는 첨부 형식")
    return "\n".join(line for row in raw.splitlines()
                     if (line := " ".join(row.split())))[:MAX_LENGTH]


def attachment_text(notice: dict) -> str:
    files = [notice.get("print_file"), *notice.get("attachments", [])]
    sections = []
    seen = set()
    for file in files:
        if not file or file["url"] in seen:
            continue
        kind = file["name"].strip().lower().rsplit(".", 1)[-1]
        if kind not in {"pdf", "hwpx"}:
            continue
        seen.add(file["url"])
        try:
            body = extract(download(file["url"]), kind)
        except (OSError, ValueError, RuntimeError, subprocess.SubprocessError, zipfile.BadZipFile,
                ElementTree.ParseError, DefusedXmlException):
            body = ""
        if body:
            sections.append(f"{file['name']}\n{body}")
        if len(seen) >= 3 or sum(map(len, sections)) >= MAX_LENGTH:
            break
    return "\n\n".join(sections)[:MAX_LENGTH]
