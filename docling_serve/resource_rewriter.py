import logging
import mimetypes
import posixpath
import re
from pathlib import Path
from urllib.parse import unquote, unquote_plus

import requests

from docling_serve.settings import docling_serve_settings
from docling_serve.storage import get_scratch

_log = logging.getLogger(__name__)


class ResourceUploadError(RuntimeError):
    pass


class ResourceUploader:
    def __init__(self):
        self.upload_url = docling_serve_settings.resource_upload_url
        self.download_url_template = docling_serve_settings.resource_download_url_template
        self.file_field_name = docling_serve_settings.resource_upload_file_field_name
        self.timeout = docling_serve_settings.resource_upload_timeout_seconds
        self.extra_form_data = docling_serve_settings.resource_upload_form_data or {}
        self._cache: dict[str, str] = {}

    def enabled(self) -> bool:
        return (
            docling_serve_settings.resource_upload_enabled
            and bool(self.upload_url)
            and bool(self.download_url_template)
        )

    def _upload(self, file_path: Path) -> str:
        content_type, _ = mimetypes.guess_type(file_path.name)
        content_type = content_type or "application/octet-stream"
        with file_path.open("rb") as f:
            files = {self.file_field_name: (file_path.name, f, content_type)}
            resp = requests.post(
                self.upload_url,
                data=self.extra_form_data,
                files=files,
                timeout=self.timeout,
            )
        resp.raise_for_status()
        payload = resp.json()
        if not payload.get("success"):
            raise ResourceUploadError(f"upload failed: {payload}")
        data = payload.get("data") or []
        if not data:
            raise ResourceUploadError(f"missing file id: {payload}")
        file_id = data[0]
        return self.download_url_template.format(file_id=file_id)

    def _search_roots(self, base_dir: Path) -> list[Path]:
        roots = []
        for p in [base_dir, Path(docling_serve_settings.resource_local_base_dir or "."), get_scratch()]:
            try:
                rp = p.resolve()
            except Exception:
                rp = p
            if rp not in roots and rp.exists():
                roots.append(rp)
        return roots

    def _resolve_path(self, ref: str, base_dir: Path) -> Path | None:
        ref = (ref or "").strip().strip(chr(34) + chr(39))
        ref_name = Path(posixpath.basename(ref)).name
        ref_path = Path(ref)

        if ref_path.is_absolute() and ref_path.exists():
            return ref_path.resolve()

        roots = self._search_roots(base_dir)
        for root in roots:
            if not ref_path.is_absolute():
                candidate = (root / ref_path).resolve()
                if candidate.exists():
                    return candidate
            if ref_name:
                direct = (root / ref_name).resolve()
                if direct.exists():
                    return direct
                matches = list(root.glob(f"*_artifacts/{ref_name}"))
                if matches:
                    return matches[0].resolve()
                matches = list(root.rglob(ref_name))
                if matches:
                    return matches[0].resolve()
        return None

    def upload_once(self, ref: str, base_dir: Path) -> str:
        if ref in self._cache:
            return self._cache[ref]
        if ref.startswith("http://") or ref.startswith("https://"):
            return ref
        if ref.startswith("data:"):
            return ref
        path = self._resolve_path(ref, base_dir)
        if path is None:
            _log.warning("resource file not found, skip upload: %s (base_dir=%s)", ref, base_dir)
            return ref
        remote_url = self._upload(path)
        self._cache[ref] = remote_url
        return remote_url


MD_IMAGE_PATTERN = re.compile(r'!\[([^\]]*)\]\(([^)\s]+(?:\s+"[^"]*")?)\)')
HTML_IMAGE_PATTERN = re.compile(r"(<img[^>]*src=[\"'])([^\"']+)([\"'][^>]*>)", re.IGNORECASE)
BROKEN_MD_PREFIX_PATTERN = re.compile(r'\uFFFD?!\[', re.MULTILINE)


def rewrite_markdown(content: str, uploader: ResourceUploader, base_dir: Path) -> str:
    content = BROKEN_MD_PREFIX_PATTERN.sub('![', content)

    def repl(match):
        alt = match.group(1)
        ref = match.group(2).strip()
        if ref.startswith("<") and ref.endswith(">"):
            ref = ref[1:-1].strip()
        if " " in ref and not ref.startswith(("http://", "https://", "/")):
            ref = ref.split(" ", 1)[0].strip()
        remote = uploader.upload_once(ref, base_dir)
        return f"![{alt}]({remote})"

    return MD_IMAGE_PATTERN.sub(repl, content)


def rewrite_html(content: str, uploader: ResourceUploader, base_dir: Path) -> str:
    def repl(match):
        prefix = match.group(1)
        ref = match.group(2).strip()
        suffix = match.group(3)
        remote = uploader.upload_once(ref, base_dir)
        return f"{prefix}{remote}{suffix}"

    return HTML_IMAGE_PATTERN.sub(repl, content)


def rewrite_json_obj(obj, uploader: ResourceUploader, base_dir: Path):
    if isinstance(obj, dict):
        return {k: rewrite_json_obj(v, uploader, base_dir) for k, v in obj.items()}
    if isinstance(obj, list):
        return [rewrite_json_obj(v, uploader, base_dir) for v in obj]
    if isinstance(obj, str):
        if obj.startswith("data:") and docling_serve_settings.resource_strip_base64_data_urls:
            return ""
        lower = obj.lower()
        if lower.endswith((".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".svg")):
            try:
                return uploader.upload_once(obj, base_dir)
            except Exception:
                _log.exception("failed to upload json resource: %s", obj)
                return obj
        return obj
    return obj


def rewrite_export_document(document):
    uploader = ResourceUploader()
    if not uploader.enabled():
        return document
    root_dir = Path(docling_serve_settings.resource_local_base_dir or ".")
    real_output_dir = Path(document.output_dir) if getattr(document, "output_dir", None) else None
    raw_filename = getattr(document, "filename", "document")
    decoded_candidates = []
    for candidate in [raw_filename, unquote(raw_filename), unquote_plus(raw_filename)]:
        if candidate and candidate not in decoded_candidates:
            decoded_candidates.append(candidate)
    stems = []
    for candidate in decoded_candidates:
        stem = Path(candidate).stem
        if stem and stem not in stems:
            stems.append(stem)
    preferred_dirs = [
        real_output_dir / "artifacts" if real_output_dir else None,
        real_output_dir,
    ]
    for stem in stems:
        preferred_dirs.extend([
            root_dir / f"{stem}_artifacts",
            get_scratch() / f"{stem}_artifacts",
        ])
    preferred_dirs.extend([root_dir, get_scratch()])
    base_dir = next((p for p in preferred_dirs if p is not None and p.exists()), root_dir)
    _log.warning("DIAG rewriter filename=%s decoded=%s output_dir=%s base_dir=%s", raw_filename, decoded_candidates, getattr(document, "output_dir", None), base_dir)
    if getattr(document, "md_content", None):
        document.md_content = rewrite_markdown(document.md_content, uploader, base_dir)
    if getattr(document, "html_content", None):
        document.html_content = rewrite_html(document.html_content, uploader, base_dir)
    if getattr(document, "json_content", None) is not None:
        data = document.json_content.model_dump(mode="json")
        data = rewrite_json_obj(data, uploader, base_dir)
        document.json_content = type(document.json_content).model_validate(data)
    return document


def upload_file_and_collect(file_path: Path):
    uploader = ResourceUploader()
    local_path = file_path.resolve()
    result = {
        "filename": local_path.name,
        "local_path": str(local_path),
        "file_id": None,
        "download_url": None,
        "content_type": mimetypes.guess_type(local_path.name)[0] or "application/octet-stream",
        "size_bytes": local_path.stat().st_size if local_path.exists() else None,
    }
    if not local_path.exists():
        return result
    if not uploader.enabled():
        return result
    remote_url = uploader._upload(local_path)
    result["download_url"] = remote_url
    marker = '/downloadfile/'
    if marker in remote_url:
        result["file_id"] = remote_url.split(marker, 1)[1].split('?', 1)[0]
    return result
