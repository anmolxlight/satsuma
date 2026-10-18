"""What a file is and what it can become."""
import base64
import mimetypes
import os
import shutil
import subprocess
import tempfile
from functools import cache, lru_cache
from pathlib import Path

ALIAS = {"jpeg": "jpg", "jpe": "jpg", "tif": "tiff", "aif": "aiff", "aifc": "aiff", "heif": "heic", "htm": "html",
         "xhtml": "html", "markdown": "md", "oga": "ogg", "text": "txt", "tbz2": "bz2", "txz": "xz", "mpga": "mp3"}

# kind -> (input extensions, output formats in wheel order)
FAMILIES = {
    "image": ({"jpg", "png", "webp", "heic", "avif", "tiff", "bmp", "svg", "ico"},
              ["jpg", "png", "webp", "heic", "avif", "tiff", "gif", "pdf", "ico"]),
    "audio": ({"mp3", "m4a", "wav", "flac", "ogg", "opus", "aiff", "wma", "aac"},
              ["mp3", "m4a", "wav", "flac", "ogg", "opus", "aiff"]),
    # ponytail: gif lives here (animated); first-frame image outputs are added in options()
    "video": ({"mp4", "mov", "mkv", "webm", "gif", "avi", "wmv", "m4v"},
              ["mp4", "mov", "mkv", "webm", "gif", "mp3", "m4a"]),
    "pdf": ({"pdf"}, ["docx", "odt", "pptx", "xlsx", "jpg", "png", "txt", "md", "html", "epub"]),
    "doc": ({"docx", "doc", "odt", "rtf", "md", "txt", "html", "epub", "pages"},
            ["docx", "odt", "pdf", "md", "txt", "html", "epub", "rtf"]),
    "slides": ({"ppt", "pptx", "odp", "key"}, ["pdf", "pptx", "odp", "jpg", "png"]),
    "sheet": ({"xls", "xlsx", "ods", "csv", "tsv"}, ["xlsx", "ods", "csv", "tsv", "pdf", "html"]),
    "sub": ({"srt", "vtt", "ass"}, ["srt", "vtt", "txt"]),
    "archive": ({"zip", "tar", "tgz", "gz", "bz2", "xz", "7z", "rar"}, ["extract"]),
}
KIND_OF = {e: k for k, (ins, _) in FAMILIES.items() for e in ins}
GIF_FRAME_OUT = ["png", "jpg", "webp"]
LO_NATIVE_DOC = {"docx", "doc", "odt", "rtf", "html", "txt"}  # LibreOffice opens these directly
# Apple bundles: only the embedded preview is readable without Apple software
PREVIEW_ONLY = {"pages", "key"}

# mime types mimetypes.guess_extension gets wrong or doesn't know
MIME_EXT = {"image/heic": "heic", "image/heif": "heic", "image/avif": "avif", "audio/x-wav": "wav",
            "audio/x-m4a": "m4a", "video/x-matroska": "mkv", "application/x-rar": "rar",
            "application/vnd.rar": "rar", "application/x-7z-compressed": "7z", "application/gzip": "gz",
            "application/x-xz": "xz", "application/x-bzip2": "bz2", "text/x-ssa": "ass",
            "application/x-subrip": "srt", "text/vtt": "vtt", "text/markdown": "md", "image/x-icon": "ico",
            "image/vnd.microsoft.icon": "ico", "audio/x-aiff": "aiff", "audio/ogg": "ogg", "text/plain": "txt",
            "application/msword": "doc", "application/vnd.ms-excel": "xls", "application/vnd.ms-powerpoint": "ppt",
            "text/csv": "csv", "image/jpeg": "jpg", "audio/mpeg": "mp3", "video/quicktime": "mov"}


def norm(e):
    e = e.lower().lstrip(".")
    return ALIAS.get(e, e)


@lru_cache(maxsize=512)
def _sniff(path):
    """`file --mime-type` fallback for files with a missing or wrong extension."""
    if not shutil.which("file"):
        return ""
    try:
        mime = subprocess.run(["file", "--mime-type", "-b", path], capture_output=True, text=True,
                              timeout=5, check=False).stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        return ""
    e = MIME_EXT.get(mime) or (mimetypes.guess_extension(mime) or "")
    return norm(e)


def ext(path):
    """Normalized format of a file: by extension, else by content."""
    e = norm(Path(path).suffix)
    if e in KIND_OF or e == "pdf" or os.path.isdir(path):
        return e
    return _sniff(str(path)) or e


def kind(path):
    if os.path.isdir(path):
        return "folder"
    return KIND_OF.get(ext(path), "other")


def needs(k, src, out):
    """Binaries required to turn a `src`-format file of kind `k` into `out`."""
    if k == "image":
        dec = (f"{src.upper()} decoder",) if src in ("avif", "heic") else ()
        enc = {"heic": ("heif-enc", "HEIC encoder"), "avif": ("AVIF encoder",)}.get(out, ())
        return ("convert", *dec, *enc)
    if k in ("audio", "video"):
        return ("convert",) if out in GIF_FRAME_OUT else ("ffmpeg",)
    if k == "sub":
        return () if out == "txt" else ("ffmpeg",)
    if k == "pdf":
        return {"jpg": ("pdftoppm",), "png": ("pdftoppm",), "txt": ("pdftotext",), "html": ("pdftohtml",),
                "md": ("pdftotext", "pandoc"), "epub": ("pdftotext", "pandoc"),
                "xlsx": ("pdftotext", "soffice")}.get(out, ("soffice",))
    if k == "doc":
        if src in PREVIEW_ONLY:
            return ()
        lo = out in ("pdf", "rtf") or src == "doc"
        pd = out not in ("pdf", "rtf") or src not in LO_NATIVE_DOC
        return ("soffice",) * lo + ("pandoc",) * pd
    if k == "slides":
        if src in PREVIEW_ONLY:
            return ("pdftoppm",) if out in ("jpg", "png") else ()
        return ("soffice", "pdftoppm") if out in ("jpg", "png") else ("soffice",)
    if k == "sheet":
        return () if {src, out} <= {"csv", "tsv"} else ("soffice",)
    if k == "archive":
        return ("unar",) if src in ("7z", "rar") else ()
    return ()


def all_options(path):
    """Every output format for this file, ignoring which tools are installed. Never the source format."""
    k, e = kind(path), ext(path)
    if k not in FAMILIES:
        return []
    outs = FAMILIES[k][1]
    if e == "gif":  # animated gif: no audio track to extract, but a first frame to grab
        outs = [o for o in outs if o not in ("mp3", "m4a")] + GIF_FRAME_OUT
    if e in PREVIEW_ONLY:  # Apple bundles: what the embedded preview PDF gives us
        outs = ["pdf", "jpg", "png"] if k == "slides" else ["pdf"]
    return [o for o in outs if o != e]


def missing(tools):
    return [t for t in tools if not (codec_works(t) if t in CODECS else shutil.which(t))]


# ImageMagick lists AVIF/HEIC as read+write whenever it links libheif, but the codecs are separate libheif
# plugins (aomenc, libde265, x265...). So probe for real: encode a pixel, decode these 1x1 samples.
CODECS = ("AVIF encoder", "AVIF decoder", "HEIC encoder", "HEIC decoder")
_PROBE = {
    "avif": "AAAAHGZ0eXBhdmlmAAAAAGF2aWZtaWYxbWlhZgAAAOptZXRhAAAAAAAAACFoZGxyAAAAAAAAAABwaWN0AAAAAAAAAAAAAAAAAAAA"
            "AA5waXRtAAAAAAABAAAAImlsb2MAAAAAREAAAQABAAAAAAEOAAEAAAAAAAAAHwAAACNpaW5mAAAAAAABAAAAFWluZmUCAAAAAAEA"
            "AGF2MDEAAAAAamlwcnAAAABLaXBjbwAAABNjb2xybmNseAABAA0ABoAAAAAMYXYxQ4FAbAAAAAAUaXNwZQAAAAAAAAABAAAAAQAA"
            "ABBwaXhpAAAAAAMMDAwAAAAXaXBtYQAAAAAAAAABAAEEAYIDBAAAACdtZGF0EgAKCFgABjQENBuEMhEYAA4444QAALASvbjm8/e/"
            "7A==",
    "heic": "AAAAGGZ0eXBoZWljAAAAAG1pZjFoZWljAAABfW1ldGEAAAAAAAAAIWhkbHIAAAAAAAAAAHBpY3QAAAAAAAAAAAAAAAAAAAAADnBp"
            "dG0AAAAAAAEAAAAiaWxvYwAAAABEQAABAAEAAAAAAZ0AAQAAAAAAAAAzAAAAI2lpbmYAAAAAAAEAAAAVaW5mZQIAAAAAAQAAaHZj"
            "MQAAAAD9aXBycAAAAN1pcGNvAAAAdmh2Y0MBA3AAAAAAAAAAAAAe8AD8/fj4AAAPAyAAAQAYQAEMAf//A3AAAAMAkAAAAwAAAwAe"
            "ugJAIQABACpCAQEDcAAAAwCQAAADAAADAB6gIIEFluqumubgIaDAgAAAAwCAAAADAIQiAAEABkQBwXPBiQAAABRpc3BlAAAAAAAA"
            "AEAAAABAAAAAKGNsYXAAAAABAAAAAQAAAAEAAAAB////wQAAAAL////BAAAAAgAAABNjb2xybmNseAABAA0ABoAAAAAQcGl4aQAA"
            "AAADCAgIAAAAGGlwbWEAAAAAAAAAAQABBYECgwQFAAAAO21kYXQAAAAvKAGvEyFkY0D1JyL2f2VCf/pNcn/IvZYWdyugwVvy+sD2"
            "ZJvA86qRnoCHaacwFXg=",
}


@cache
def codec_works(name):
    """True if the "AVIF encoder" / "HEIC decoder" / ... really works. HEIC is written by heif-enc, the rest by convert."""
    fmt, role = name.lower().split()
    if missing(("convert", "heif-enc") if name == "HEIC encoder" else ("convert",)):
        return False
    with tempfile.TemporaryDirectory() as td:
        img, png = os.path.join(td, f"x.{fmt}"), os.path.join(td, "x.png")
        if role == "decoder":
            Path(img).write_bytes(base64.b64decode(_PROBE[fmt]))
            cmds, out = [["convert", img, png]], png
        else:
            cmds = [["convert", "-size", "8x8", "xc:orange", png],
                    ["heif-enc", "-o", img, png] if fmt == "heic" else ["convert", png, img]]
            out = img
        try:
            ok = all(subprocess.run(c, capture_output=True, timeout=20, check=False).returncode == 0 for c in cmds)
        except (OSError, subprocess.TimeoutExpired):
            return False
        head = Path(out).read_bytes()[:12] if ok and os.path.exists(out) else b""
    return head[4:] == b"ftyp" + fmt.encode() if role == "encoder" else head.startswith(b"\x89PNG")


def options(path):
    """Output formats offered for this file: installed tools only."""
    k, e = kind(path), ext(path)
    return [o for o in all_options(path) if not missing(needs(k, e, o))]


def common_options(paths):
    """Options shared by every file in a batch (same kind), in wheel order."""
    if not paths or len({kind(p) for p in paths}) != 1:
        return []
    sets = [set(options(p)) for p in paths]
    return [o for o in options(paths[0]) if all(o in s for s in sets)]


# A representative input per family, used to count what a missing tool would unlock
_SAMPLES = {"image": ["png", "svg"], "audio": ["wav"], "video": ["mp4", "gif"], "pdf": ["pdf"],
            "doc": ["docx", "md", "doc", "pages"], "slides": ["pptx", "key"], "sheet": ["xlsx", "csv"],
            "sub": ["srt", "ass"], "archive": ["zip", "7z", "rar"]}


def locked():
    """{missing binary: number of (input format, output) options it would unlock}."""
    out = {}
    for k, (ins, _) in FAMILIES.items():
        for src in ins:
            for o in all_options(f"x.{src}"):
                for t in missing(needs(k, src, o)):
                    out[t] = out.get(t, 0) + 1
    return out


# binary -> package name per distro
PACKAGES = {
    "ffmpeg": ("ffmpeg", "ffmpeg", "ffmpeg"),
    "convert": ("imagemagick", "ImageMagick", "imagemagick"),
    "heif-enc": ("libheif-examples", "libheif-tools", "libheif"),
    "AVIF encoder": ("libheif-plugin-aomenc", "libheif", "aom"),
    "AVIF decoder": ("libheif-plugin-dav1d", "libheif", "dav1d"),
    "HEIC encoder": ("libheif-plugin-x265", "libheif-freeworld", "x265"),
    "HEIC decoder": ("libheif-plugin-libde265", "libheif-freeworld", "libde265"),
    "pdftoppm": ("poppler-utils", "poppler-utils", "poppler"),
    "pdftotext": ("poppler-utils", "poppler-utils", "poppler"),
    "pdftohtml": ("poppler-utils", "poppler-utils", "poppler"),
    "pandoc": ("pandoc", "pandoc", "pandoc"),
    "soffice": ("libreoffice-nogui", "libreoffice-core libreoffice-writer libreoffice-calc libreoffice-impress",
                "libreoffice-fresh"),
    "unar": ("unar", "unar", "unarchiver"),
    "gs": ("ghostscript", "ghostscript", "ghostscript"),
    "qpdf": ("qpdf", "qpdf", "qpdf"),
}


def install_hint(binary):
    apt, dnf, pac = PACKAGES.get(binary, (binary,) * 3)
    return {"apt": f"sudo apt install {apt}", "dnf": f"sudo dnf install {dnf}", "pacman": f"sudo pacman -S {pac}"}
