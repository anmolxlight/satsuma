"""Conversion engine: one function per family. Output lands next to the source (or the
configured folder), never overwrites, and appears atomically (temp file + rename)."""
import bz2
import csv
import gzip
import lzma
import os
import re
import secrets
import shutil
import tarfile
import tempfile
import threading
import zipfile
from pathlib import Path

from . import config
from .formats import GIF_FRAME_OUT, LO_NATIVE_DOC, PREVIEW_ONLY, all_options, ext, install_hint, kind, missing, needs
from .jobs import SatsumaError, check, ff, has_stream, run

ARCHIVE_SUFFIXES = (".tar.gz", ".tar.bz2", ".tar.xz", ".tgz", ".tar", ".zip", ".7z", ".rar", ".gz", ".bz2", ".xz")


def free(want):
    """'a.jpg' -> 'a.jpg' if free, else 'a 2.jpg', 'a 3.jpg', ..."""
    p = Path(want)
    stem, suf = (p.name, "") if p.is_dir() or not p.suffix else (p.stem, p.suffix)
    if p.name.endswith(".tar.gz"):
        stem, suf = p.name[:-7], ".tar.gz"
    cand, n = p, 2
    while cand.exists() or cand.is_symlink():
        cand = p.with_name(f"{stem} {n}{suf}")
        n += 1
    return str(cand)


def out_dir(src):
    cfg = config.get()
    if cfg["output"] == "folder":
        d = os.path.expanduser(cfg["output_folder"])
        os.makedirs(d, exist_ok=True)
        return d
    return os.path.dirname(os.path.abspath(src))


def out_path(src, new_ext, tag=""):
    """Free output path for `src` with a new extension ("" = folder) and optional name tag."""
    stem = Path(src).stem if not os.path.isdir(src) else Path(src).name
    name = f"{stem}{tag}" + (f".{new_ext}" if new_ext else "")
    return free(os.path.join(out_dir(src), name))


class Output:
    """with Output(src, "jpg") as o: write o.tmp  ->  o.path is the final file (renamed on success only)."""

    def __init__(self, src, new_ext, tag="", name=None):
        self.want = os.path.join(out_dir(src), name) if name else out_path(src, new_ext, tag)
        self.is_dir = not new_ext

    def __enter__(self):
        d, n = os.path.split(self.want)
        self.tmp = os.path.join(d, f".satsuma-{secrets.token_hex(4)}-{n}")
        if self.is_dir:
            os.mkdir(self.tmp)
        return self

    def __exit__(self, et, ev, tb):
        ok = os.path.isdir(self.tmp) and os.listdir(self.tmp) if self.is_dir else \
            os.path.isfile(self.tmp) and os.path.getsize(self.tmp) > 0
        if et is None and ok:
            self.path = free(self.want)
            os.rename(self.tmp, self.path)
            return False
        shutil.rmtree(self.tmp, ignore_errors=True) if os.path.isdir(self.tmp) else \
            Path(self.tmp).unlink(missing_ok=True)
        if et is None:
            raise SatsumaError("The conversion finished but produced nothing")
        return False


def meta_flags(ffmpeg=True):
    if config.get()["keep_metadata"]:
        return []
    return ["-map_metadata", "-1"] if ffmpeg else ["-strip"]


# ---------------------------------------------------------------- images
def image(src, e, to):
    q = str(config.get()["image_quality"])
    first = e in ("gif", "tiff", "ico", "heic") and to not in ("pdf", "tiff", "gif")
    pre = ["-background", "none", "-density", "192"] if e == "svg" else []
    s = src + "[0]" if first else src
    with Output(src, to) as o:
        if to == "heic":
            with tempfile.TemporaryDirectory() as td:
                png = os.path.join(td, "i.png")
                run(["convert", *pre, s, "-auto-orient", png])
                run(["heif-enc", "-q", q, "-o", o.tmp, png])
        elif to == "ico":
            run(["convert", *pre, s, "-auto-orient", "-background", "none", "-resize", "256x256",
                 "-define", "icon:auto-resize=256,128,64,48,32,16", o.tmp])
        else:
            flat = ["-background", "white", "-alpha", "remove", "-alpha", "off"] if to == "jpg" else []
            run(["convert", *pre, s, "-auto-orient", *flat, *meta_flags(False), "-quality", q, o.tmp])
    return o.path


# ---------------------------------------------------------------- audio / video
ACODEC = {"mp3": ["-c:a", "libmp3lame", "-q:a", "2"], "m4a": ["-c:a", "aac", "-b:a", "192k"],
          "wav": ["-c:a", "pcm_s16le"], "flac": ["-c:a", "flac"], "ogg": ["-c:a", "libvorbis", "-q:a", "5"],
          "opus": ["-c:a", "libopus", "-b:a", "128k"], "aiff": ["-c:a", "pcm_s16be"]}
GIF_VF = "fps=12,scale='min(480,iw)':-2:flags=lanczos,split[a][b];[a]palettegen[p];[b][p]paletteuse"


def audio(src, e, to):
    with Output(src, to) as o:
        ff(src, o.tmp, "-vn", *meta_flags(), *ACODEC[to])
    return o.path


def vcodec(to):
    x264, vp9 = config.CRF[config.get()["video_quality"]]
    if to == "webm":
        return ["-c:v", "libvpx-vp9", "-b:v", "0", "-crf", str(vp9), "-row-mt", "1", "-deadline", "good",
                "-cpu-used", "4", "-c:a", "libopus", "-b:a", "128k"]
    fast = ["-movflags", "+faststart"] if to in ("mp4", "mov", "m4v") else []
    return ["-c:v", "libx264", "-preset", "medium", "-crf", str(x264), "-pix_fmt", "yuv420p",
            "-vf", "scale=trunc(iw/2)*2:trunc(ih/2)*2", "-c:a", "aac", "-b:a", "160k", *fast]


def video(src, e, to):
    if to in GIF_FRAME_OUT:  # first frame of an animated gif
        return image(src, e, to)
    if to in ("mp3", "m4a") and not has_stream(src, "a"):
        raise SatsumaError("This video has no audio track")
    with Output(src, to) as o:
        if to == "gif":
            ff(src, o.tmp, "-vf", GIF_VF, "-loop", "0")
        elif to in ("mp3", "m4a"):
            ff(src, o.tmp, "-vn", *meta_flags(), *ACODEC[to])
        else:
            ff(src, o.tmp, *meta_flags(), *vcodec(to))
    return o.path


# ---------------------------------------------------------------- office (LibreOffice)
_lo_lock = threading.Lock()  # ponytail: one soffice at a time per profile; per-job profiles if batches get slow
LO_FMT = {"docx": "docx:MS Word 2007 XML", "pptx": "pptx:Impress MS PowerPoint 2007 XML",
          "xlsx": "xlsx:Calc MS Excel 2007 XML", "csv": "csv:Text - txt - csv (StarCalc):44,34,76",
          "tsv": "csv:Text - txt - csv (StarCalc):9,34,76", "html": "html", "rtf": "rtf", "pdf": "pdf",
          "odt": "odt", "ods": "ods", "odp": "odp"}


def soffice(src, to, dst, infilter=None, timeout=180):
    """LibreOffice headless with a private profile (works while the user has LO open)."""
    with tempfile.TemporaryDirectory() as td:
        cmd = ["soffice", f"-env:UserInstallation=file:///tmp/satsuma-lo-{os.getuid()}", "--headless",
               "--norestore", "--nologo", "--nolockcheck", "--nodefault"]
        if infilter:
            cmd.append(f"--infilter={infilter}")
        fmt = LO_FMT.get(to, to)
        with _lo_lock:
            run(cmd + ["--convert-to", fmt, "--outdir", td, src], timeout=timeout)
        made = [f for f in os.listdir(td) if not f.startswith(".")]
        if not made:
            raise SatsumaError("LibreOffice couldn't convert this file")
        shutil.move(os.path.join(td, made[0]), dst)
    return dst


def pandoc(src, src_fmt, to, dst):
    reader = {"md": "markdown", "txt": "markdown", "html": "html"}.get(src_fmt, src_fmt)
    writer = {"txt": "plain", "md": "gfm"}.get(to, to)
    extra = ["-s", "--metadata", f"pagetitle={Path(src).stem}"] if to == "html" else ["-s"]
    run(["pandoc", "-f", reader, "-t", writer, *extra, src, "-o", dst])
    return dst


CSV_IN = {"csv": "CSV:44,34,UTF8", "tsv": "CSV:9,34,UTF8"}


# ---------------------------------------------------------------- pdf
def pdf_pages(src, fmt, dpi=300, name=None, near=None):
    """Every page as an image, in a folder next to `near` (the user's file) or `src`."""
    with Output(near or src, "", " pages", name=name) as o:
        run(["pdftoppm", "-r", str(dpi), "-png" if fmt == "png" else "-jpeg", src, os.path.join(o.tmp, Path(src).stem)])
    return o.path


def pdf_table_csv(src, dst):
    """Text-layer table guess: one row per line, cells split on runs of 2+ spaces."""
    # ponytail: heuristic; real table detection (camelot-style) if people convert complex statements
    text = run(["pdftotext", "-layout", src, "-"])
    with open(dst, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        for line in text.splitlines():
            if line.strip():
                w.writerow(re.split(r"\s{2,}", line.strip()))


def pdf(src, e, to):
    if to in ("jpg", "png"):
        return pdf_pages(src, to)
    with Output(src, to) as o, tempfile.TemporaryDirectory() as td:
        if to == "txt":
            run(["pdftotext", "-layout", src, o.tmp])
        elif to == "html":
            run(["pdftohtml", "-s", "-i", "-noframes", "-q", src, os.path.join(td, "x.html")])
            shutil.move(os.path.join(td, "x.html"), o.tmp)
        elif to in ("md", "epub"):
            txt = os.path.join(td, Path(src).stem + ".txt")
            run(["pdftotext", src, txt])
            pandoc(txt, "txt", to, o.tmp)
        elif to in ("docx", "odt"):
            soffice(src, to, o.tmp, infilter="writer_pdf_import")
        elif to == "pptx":
            soffice(src, to, o.tmp, infilter="impress_pdf_import")
        elif to == "xlsx":
            c = os.path.join(td, Path(src).stem + ".csv")
            pdf_table_csv(src, c)
            soffice(c, to, o.tmp, infilter=CSV_IN["csv"])
    return o.path


# ---------------------------------------------------------------- documents, slides, sheets
def preview_pdf(src, dst):
    """Pages/Keynote bundles carry a preview PDF (older) or JPEG (newer); that's all we can read."""
    try:
        with zipfile.ZipFile(src) as z:
            names = {n.lower(): n for n in z.namelist()}
            for n in ("quicklook/preview.pdf", "preview.pdf"):
                if n in names:
                    with z.open(names[n]) as f, open(dst, "wb") as out:
                        shutil.copyfileobj(f, out)
                    return dst
            for n in ("preview.jpg", "quicklook/thumbnail.jpg"):
                if n in names:
                    with tempfile.TemporaryDirectory() as td:
                        jpg = z.extract(names[n], td)
                        run(["convert", jpg, dst])
                    return dst
    except zipfile.BadZipFile:
        pass
    raise SatsumaError("This file has no preview Satsuma can read (export it as PDF from the Mac app)")


def preview(src, e, to):
    if to == "pdf":
        with Output(src, "pdf") as o:
            preview_pdf(src, o.tmp)
        return o.path
    with tempfile.TemporaryDirectory() as td:
        p = preview_pdf(src, os.path.join(td, Path(src).stem + ".pdf"))
        return pdf_pages(p, to, 150, name=Path(src).stem + " slides", near=src)


def doc(src, e, to):
    with Output(src, to) as o, tempfile.TemporaryDirectory() as td:
        if to in ("pdf", "rtf"):
            if e not in LO_NATIVE_DOC:  # markdown, epub: pandoc first, then LibreOffice lays it out
                mid = pandoc(src, e, "docx", os.path.join(td, Path(src).stem + ".docx"))
                soffice(mid, to, o.tmp)
            else:
                soffice(src, to, o.tmp)
        else:
            if e == "doc":  # legacy Word: LibreOffice to docx, then pandoc
                src, e = soffice(src, "docx", os.path.join(td, Path(src).stem + ".docx")), "docx"
            pandoc(src, e, to, o.tmp)
    return o.path


def slides(src, e, to):
    if to in ("jpg", "png"):
        with tempfile.TemporaryDirectory() as td:
            p = soffice(src, "pdf", os.path.join(td, Path(src).stem + ".pdf"))
            return pdf_pages(p, to, 150, name=Path(src).stem + " slides", near=src)
    with Output(src, to) as o:
        soffice(src, to, o.tmp)
    return o.path


def sheet(src, e, to):
    with Output(src, to) as o:
        if {e, to} <= {"csv", "tsv"}:
            with open(src, newline="", encoding="utf-8-sig") as f, open(o.tmp, "w", newline="", encoding="utf-8") as out:
                csv.writer(out, delimiter="\t" if to == "tsv" else ",").writerows(
                    csv.reader(f, delimiter="\t" if e == "tsv" else ","))
        else:
            soffice(src, to, o.tmp, infilter=CSV_IN.get(e))
    return o.path


# ---------------------------------------------------------------- subtitles
def sub_text(src, e):
    raw = Path(src).read_text(encoding="utf-8-sig", errors="replace").splitlines()
    if e == "ass":
        lines = [ln.split(",", 9)[9] for ln in raw if ln.startswith("Dialogue:") and ln.count(",") >= 9]
        lines = [re.sub(r"\{[^}]*\}", "", ln).replace("\\N", "\n").replace("\\n", "\n") for ln in lines]
    else:
        lines = [ln for ln in raw if ln.strip() and "-->" not in ln and not ln.strip().isdigit()
                 and not ln.startswith(("WEBVTT", "NOTE", "STYLE", "Kind:", "Language:"))]
    return "\n".join(re.sub(r"<[^>]+>", "", ln) for ln in lines) + "\n"


def sub(src, e, to):
    with Output(src, to) as o:
        if to == "txt":
            Path(o.tmp).write_text(sub_text(src, e), encoding="utf-8")
        else:
            ff(src, o.tmp)
    return o.path


# ---------------------------------------------------------------- archives
def _safe_tar(tf, dst):
    if hasattr(tarfile, "data_filter"):
        tf.extractall(dst, filter="data")
        return
    for m in tf.getmembers():  # Python < 3.11.4: refuse what the data filter would
        p = Path(m.name)
        if p.is_absolute() or ".." in p.parts or m.issym() or m.islnk() or m.isdev():
            raise SatsumaError("This archive contains unsafe paths and was not extracted")
    tf.extractall(dst)


def archive(src, e, to):
    name = Path(src).name
    for suf in ARCHIVE_SUFFIXES:
        if name.lower().endswith(suf):
            name = name[:-len(suf)]
            break
    with Output(src, "", name=name or "archive") as o:
        if e in ("7z", "rar"):
            run(["unar", "-q", "-f", "-D", "-o", o.tmp, src])
        elif tarfile.is_tarfile(src):
            with tarfile.open(src) as tf:
                _safe_tar(tf, o.tmp)
        elif zipfile.is_zipfile(src):
            with zipfile.ZipFile(src) as z:
                z.extractall(o.tmp)  # zipfile strips absolute paths and '..'
        elif e in ("gz", "bz2", "xz"):
            opener = {"gz": gzip.open, "bz2": bz2.open, "xz": lzma.open}[e]
            with opener(src) as f, open(os.path.join(o.tmp, name), "wb") as out:
                shutil.copyfileobj(f, out)
        elif shutil.which("unar"):
            run(["unar", "-q", "-f", "-D", "-o", o.tmp, src])
        else:
            raise SatsumaError("This archive format needs unar (sudo apt install unar)")
        check()
    return o.path


FAMILY = {"image": image, "audio": audio, "video": video, "pdf": pdf, "doc": doc, "slides": slides,
          "sheet": sheet, "sub": sub, "archive": archive}


def convert(src, to):
    """Convert one file; returns the output path (file or folder)."""
    src = os.path.abspath(src)
    k, e = kind(src), ext(src)
    if to not in all_options(src):
        raise SatsumaError(f"Satsuma can't turn {e.upper() or 'this file'} into {to.upper()}")
    gone = missing(needs(k, e, to))
    if gone:
        raise SatsumaError(f"Converting to {to.upper()} needs {gone[0]}: {install_hint(gone[0])['apt']}")
    return (preview if e in PREVIEW_ONLY else FAMILY[k])(src, e, to)
