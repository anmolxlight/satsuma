#!/usr/bin/env python3
"""Real conversions in a temp dir. Plain asserts, no pytest:  python3 tests/test_satsuma.py"""
import gzip
import json
import os
import shutil
import socket
import struct
import subprocess
import sys
import tempfile
import time
import traceback
import zipfile
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TMP = Path(tempfile.mkdtemp(prefix="satsuma-test-"))
os.environ["XDG_CONFIG_HOME"] = str(TMP / "config")  # never touch the real config / log
os.environ["XDG_CACHE_HOME"] = str(TMP / "cache")
sys.path.insert(0, str(ROOT))

from satsuma import config, formats, jobs, tools  # noqa: E402
from satsuma.convert import convert, out_path  # noqa: E402

D = TMP / "files"
D.mkdir()
FAILED, SKIPPED, PASSED = [], [], []


def sh(*c, **kw):
    return subprocess.run([str(x) for x in c], check=True, capture_output=True, text=True, **kw).stdout


def case(name, needs=()):
    """Decorator: run now, record pass/fail/skip, keep going."""
    def wrap(fn):
        gone = [t for t in needs if not shutil.which(t)]
        if gone:
            SKIPPED.append(name)
            print(f"SKIP {name}: {', '.join(gone)} not installed")
            return fn
        try:
            fn()
            PASSED.append(name)
            print(f"ok   {name}")
        except Exception:
            FAILED.append(name)
            print(f"FAIL {name}\n{traceback.format_exc()}")
        return fn
    return wrap


def conv(src, to):
    return jobs.run_now(lambda p: convert(p, to), str(D / src))


def tool(tid, src, **params):
    srcs = [str(D / s) for s in src] if isinstance(src, list) else [str(D / src)]
    return tools.apply(tools.BY_ID[tid], srcs, params)[0]


MAGIC = {"jpg": b"\xff\xd8\xff", "png": b"\x89PNG", "gif": b"GIF8", "pdf": b"%PDF", "webp": b"RIFF",
         "zip": b"PK\x03\x04", "docx": b"PK\x03\x04", "xlsx": b"PK\x03\x04", "pptx": b"PK\x03\x04",
         "odt": b"PK\x03\x04", "ods": b"PK\x03\x04", "odp": b"PK\x03\x04", "epub": b"PK\x03\x04",
         "ico": b"\x00\x00\x01\x00", "tiff": b"II*\x00", "rtf": b"{\\rtf", "gz": b"\x1f\x8b", "flac": b"fLaC",
         "ogg": b"OggS", "opus": b"OggS", "wav": b"RIFF", "aiff": b"FORM", "mkv": b"\x1a\x45\xdf\xa3",
         "webm": b"\x1a\x45\xdf\xa3"}
FTYP = {"heic": b"heic", "avif": b"avif", "mp4": b"ftyp", "m4a": b"ftyp", "mov": b"ftyp"}


def valid(path, fmt=None):
    p = Path(path)
    assert p.exists() and p.stat().st_size > 0, f"{p} missing or empty"
    fmt = fmt or p.suffix.lstrip(".")
    head = p.read_bytes()[:64]
    if fmt in MAGIC:
        assert head.startswith(MAGIC[fmt]), f"{p.name}: bad magic {head[:8]!r}"
    if fmt in FTYP:
        assert FTYP[fmt] in head, f"{p.name}: no {FTYP[fmt]!r} in header"
    if fmt in ("jpg", "png", "webp", "gif", "tiff", "heic", "avif", "ico") and fmt not in ("heic", "avif"):
        sh("identify", path)
    return str(path)


def streams(path, kind):
    return sh("ffprobe", "-v", "error", "-select_streams", kind, "-show_entries", "stream=codec_type", "-of",
              "csv=p=0", path).split()


def dur(path):
    return float(sh("ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", path))


def pages(path):
    return int(sh("qpdf", "--show-npages", path))


def make_rar(path, name, data):
    """Minimal RAR 4 'store' archive (rar itself is non-free, so craft the bytes)."""
    def block(htype, flags, body, add=b""):
        hdr = struct.pack("<BHH", htype, flags, 7 + len(body)) + body
        return struct.pack("<H", zlib.crc32(hdr) & 0xFFFF) + hdr + add
    n = name.encode()
    fbody = struct.pack("<IIBIIBBHI", len(data), len(data), 0, zlib.crc32(data), 0x58210000, 20, 0x30, len(n), 0x20) + n
    Path(path).write_bytes(b"Rar!\x1a\x07\x00" + block(0x73, 0, b"\0" * 6) + block(0x74, 0x8000, fbody, data)
                           + b"\xc4\x3d\x7b\x00\x40\x07\x00")


# ---------------------------------------------------------------- fixtures
t0 = time.time()
sh("convert", "-size", "64x48", "gradient:orange-black", D / "a.png")
sh("convert", "-size", "40x40", "xc:skyblue", D / "b.jpg")
(D / "s.svg").write_text('<svg xmlns="http://www.w3.org/2000/svg" width="32" height="32">'
                         '<circle cx="16" cy="16" r="14" fill="#FD5400"/></svg>')
sh("heif-enc", "-o", D / "h.heic", D / "a.png")
sh("ffmpeg", "-f", "lavfi", "-i", "sine=f=440:d=2", D / "s.wav")
sh("ffmpeg", "-f", "lavfi", "-i", "sine=f=330:d=1", D / "t.mp3")
sh("ffmpeg", "-f", "lavfi", "-i", "testsrc=d=3:s=160x120:r=25", "-f", "lavfi", "-i", "sine=d=3", "-shortest",
   "-pix_fmt", "yuv420p", "-c:v", "libx264", "-c:a", "aac", D / "v.mp4")
sh("ffmpeg", "-f", "lavfi", "-i", "testsrc2=d=2:s=320x240:r=25", "-f", "lavfi", "-i", "sine=d=2", "-shortest",
   "-pix_fmt", "yuv420p", D / "w.mp4")
sh("ffmpeg", "-f", "lavfi", "-i", "testsrc=d=2:s=160x120", "-pix_fmt", "yuv420p", D / "silent.mp4")
sh("ffmpeg", "-f", "lavfi", "-i", "testsrc=d=1:s=80x60:r=10", D / "anim.gif")
(D / "n.md").write_text("# Hello\n\nhello **world**, from Satsuma.\n\n- one\n- two\n")
sh("pandoc", D / "n.md", "-s", "-o", D / "n.docx")
sh("pandoc", D / "n.md", "-s", "-o", D / "n.html")
sh("pandoc", D / "n.md", "-s", "-o", D / "n.rtf")
sh("pandoc", D / "n.md", "-o", D / "p.pptx")
(D / "t.csv").write_text('a,b\n1,"x,y"\n2,z\n')
(D / "c.srt").write_text("1\n00:00:01,000 --> 00:00:02,000\n<i>Hello</i>\n\n2\n00:00:02,500 --> 00:00:03,000\nWorld\n\n")
sh("ffmpeg", "-i", D / "c.srt", D / "c.ass")
with zipfile.ZipFile(D / "z.zip", "w") as z:
    z.write(D / "n.md", "n.md")
sh("tar", "czf", D / "t.tar.gz", "-C", D, "n.md")
(D / "n.md.gz").write_bytes(gzip.compress((D / "n.md").read_bytes()))
make_rar(D / "r.rar", "hello.txt", b"hello from rar\n")
if shutil.which("7z"):
    sh("7z", "a", "-bd", D / "s.7z", D / "n.md")
lo_profile = f"-env:UserInstallation=file:///tmp/satsuma-lo-{os.getuid()}"
if shutil.which("soffice"):
    sh("soffice", lo_profile, "--headless", "--convert-to", "pdf", "--outdir", D, D / "n.docx")
    sh("soffice", lo_profile, "--headless", "--convert-to", "doc:MS Word 97", "--outdir", D, D / "n.docx")
    sh("soffice", lo_profile, "--headless", "--infilter=CSV:44,34,UTF8", "--convert-to", "xlsx", "--outdir", D,
       D / "t.csv")
sh("convert", D / "a.png", D / "b.jpg", D / "two.pdf")
print(f"fixtures ready in {time.time() - t0:.1f}s: {D}")


# ---------------------------------------------------------------- pure logic
@case("option tables never offer the source format")
def _():
    for k, (ins, _) in formats.FAMILIES.items():
        for e in ins:
            assert e not in formats.all_options(f"x.{e}"), (k, e)
    for alias, real in formats.ALIAS.items():
        assert real not in formats.all_options(f"x.{alias}"), alias


@case("kind by extension and by content (file --mime-type)", needs=("file",))
def _():
    assert formats.kind(str(D / "a.png")) == "image" and formats.kind(str(D / "v.mp4")) == "video"
    shutil.copy(D / "a.png", D / "noext")
    shutil.copy(D / "two.pdf", D / "mystery.bin")
    assert formats.kind(str(D / "noext")) == "image"
    assert formats.kind(str(D / "mystery.bin")) == "pdf"
    assert formats.kind(str(D)) == "folder"


@case("no-overwrite naming")
def _():
    assert out_path(str(D / "a.png"), "zzz") == str(D / "a.zzz")
    (D / "a.zzz").write_text("x")
    assert out_path(str(D / "a.png"), "zzz") == str(D / "a 2.zzz")
    (D / "a 2.zzz").write_text("x")
    assert out_path(str(D / "a.png"), "zzz") == str(D / "a 3.zzz")
    first = conv("a.png", "gif")
    second = conv("a.png", "gif")
    assert first.endswith("a.gif") and second.endswith("a 2.gif"), (first, second)


@case("config load/save roundtrip")
def _():
    cfg = config.load()
    assert cfg == config.DEFAULTS
    cfg.update(theme="dark", image_quality=70, keys={"convert": "alt", "tools": "ctrl", "actions": "shift"})
    config.save(cfg)
    assert json.loads(config.path().read_text())["theme"] == "dark"
    again = config.load()
    assert again == cfg, again
    config.path().write_text('{"theme": 5, "image_quality": "bad", "keys": {"tools": "hyper"}, "junk": 1}')
    assert config.load() == config.DEFAULTS  # bad values fall back to defaults
    config.save(json.loads(json.dumps(config.DEFAULTS)))


@case("batch options are the intersection")
def _():
    both = formats.common_options([str(D / "a.png"), str(D / "b.jpg")])
    assert "png" not in both and "jpg" not in both and "webp" in both
    assert formats.common_options([str(D / "a.png"), str(D / "s.wav")]) == []
    assert [t.id for t in tools.tools_for([str(D / "a.png"), str(D / "s.wav")])] == ["zip"]


# ---------------------------------------------------------------- conversions
@case("images", needs=("convert",))
def _():
    for to in ("jpg", "webp", "tiff", "gif", "pdf", "ico", "avif"):
        valid(conv("a.png", to), to)
    valid(conv("s.svg", "png"), "png")
    valid(conv("b.jpg", "png"), "png")
    valid(conv("anim.gif", "png"), "png")


@case("images: HEIC in and out", needs=("heif-enc",))
def _():
    valid(conv("a.png", "heic"), "heic")
    valid(conv("h.heic", "jpg"), "jpg")


@case("audio", needs=("ffmpeg",))
def _():
    for to in ("mp3", "m4a", "flac", "ogg", "opus", "aiff"):
        out = valid(conv("s.wav", to), to)
        assert streams(out, "a") == ["audio"], to
        assert abs(dur(out) - 2) < 0.2, (to, dur(out))
    valid(conv("t.mp3", "wav"), "wav")


@case("video", needs=("ffmpeg",))
def _():
    for to in ("webm", "mkv", "mov"):
        out = valid(conv("v.mp4", to), to)
        assert streams(out, "v") and streams(out, "a"), to
    valid(conv("v.mp4", "gif"), "gif")
    assert streams(valid(conv("v.mp4", "mp3")), "a")
    assert streams(valid(conv("v.mp4", "m4a"), "m4a"), "a")
    assert streams(valid(conv("anim.gif", "mp4"), "mp4"), "v")
    assert "mp3" not in formats.options(str(D / "anim.gif"))


@case("video without audio -> plain-language error", needs=("ffmpeg",))
def _():
    try:
        conv("silent.mp4", "mp3")
    except jobs.SatsumaError as e:
        assert "no audio track" in str(e), e
    else:
        raise AssertionError("expected an error")
    assert not list(D.glob("silent*.mp3")) and not list(D.glob(".satsuma-*"))


@case("pdf -> images, text, markdown, html, epub", needs=("pdftoppm", "pandoc"))
def _():
    d = conv("two.pdf", "png")
    assert sorted(os.listdir(d)) == ["two-1.png", "two-2.png"], os.listdir(d)
    valid(os.path.join(d, "two-1.png"), "png")
    assert len(os.listdir(conv("two.pdf", "jpg"))) == 2


@case("pdf -> docx/odt/pptx/xlsx/txt/md/html/epub (LibreOffice + poppler)", needs=("soffice", "pdftotext"))
def _():
    assert "hello" in Path(conv("n.pdf", "txt")).read_text().lower()
    assert "hello" in Path(conv("n.pdf", "md")).read_text().lower()
    assert "hello" in Path(conv("n.pdf", "html")).read_text().lower()
    for to in ("docx", "odt", "pptx", "xlsx", "epub"):
        valid(conv("n.pdf", to), to)
    with zipfile.ZipFile(conv("n.pdf", "docx")) as z:  # LibreOffice keeps PDF text in frames
        assert "hello" in z.read("word/document.xml").decode().lower()


@case("documents via pandoc", needs=("pandoc",))
def _():
    for to in ("docx", "odt", "html", "epub", "txt"):
        valid(conv("n.md", to), to)
    assert "hello" in Path(conv("n.docx", "md")).read_text().lower()
    assert "hello" in Path(conv("n.html", "txt")).read_text().lower()
    assert "hello" in Path(conv("n.rtf", "md")).read_text().lower()


@case("documents via LibreOffice: docx->pdf, md->pdf, doc->md, docx->rtf", needs=("soffice", "pandoc"))
def _():
    assert "hello" in sh("pdftotext", valid(conv("n.docx", "pdf")), "-").lower()
    valid(conv("n.md", "pdf"))
    valid(conv("n.docx", "rtf"), "rtf")
    assert "hello" in Path(conv("n.doc", "md")).read_text().lower()


@case("slides: pptx -> pdf / odp / png per slide", needs=("soffice", "pdftoppm"))
def _():
    valid(conv("p.pptx", "pdf"))
    valid(conv("p.pptx", "odp"), "odp")
    d = conv("p.pptx", "png")
    assert os.listdir(d) and all(f.endswith(".png") for f in os.listdir(d))


@case("sheets: xlsx->csv, csv<->tsv, csv->xlsx/ods, xlsx->pdf/html", needs=("soffice",))
def _():
    assert Path(conv("t.xlsx", "csv")).read_text().splitlines() == ["a,b", '1,"x,y"', "2,z"]
    tsv = conv("t.csv", "tsv")
    assert Path(tsv).read_bytes() == b"a\tb\r\n1\tx,y\r\n2\tz\r\n"
    valid(conv("t.csv", "xlsx"), "xlsx")
    valid(conv("t.tsv", "ods"), "ods")
    valid(conv("t.xlsx", "pdf"))
    assert "x,y" in Path(conv("t.xlsx", "html")).read_text()
    assert "x,y" in Path(conv("t.xlsx", "tsv")).read_text()


@case("subtitles", needs=("ffmpeg",))
def _():
    assert Path(conv("c.srt", "vtt")).read_text().startswith("WEBVTT")
    assert Path(conv("c.srt", "txt")).read_text() == "Hello\nWorld\n"
    assert "-->" in Path(conv("c.ass", "srt")).read_text()
    assert Path(conv("c.ass", "txt")).read_text() == "Hello\nWorld\n"


@case("archives: zip, tar.gz, gz")
def _():
    for src in ("z.zip", "t.tar.gz", "n.md.gz"):
        d = conv(src, "extract")
        files = list(Path(d).rglob("*.md"))
        assert files and "hello" in files[0].read_text().lower(), (src, os.listdir(d))
    assert conv("t.tar.gz", "extract").endswith("t 2")


@case("archives: rar", needs=("unar",))
def _():
    d = conv("r.rar", "extract")
    assert (Path(d) / "hello.txt").read_text() == "hello from rar\n", os.listdir(d)


@case("archives: 7z", needs=("unar", "7z"))
def _():
    assert (Path(conv("s.7z", "extract")) / "n.md").exists()


# ---------------------------------------------------------------- tools
@case("every tool on a matching fixture", needs=("ffmpeg", "convert", "qpdf", "gs"))
def _():
    runs = [("compress", "a.png", {}), ("compress", "v.mp4", {}), ("compress", "s.wav", {}),
            ("compress", "n.pdf", {}), ("resize", "a.png", {"size": "50%"}), ("resize", "w.mp4", {"size": "160"}),
            ("crop", "a.png", {"aspect": "1:1"}), ("crop", "w.mp4", {"aspect": "16:9"}),
            ("crop", "n.pdf", {"aspect": "1:1"}), ("trim", "s.wav", {"start": "0:00.5", "end": "1.5"}),
            ("split_pdf", "two.pdf", {"every": "1"}), ("split_av", "v.mp4", {"parts": "3"}),
            ("split_av", "s.wav", {"parts": "0:00.5, 1"}), ("rotate", "a.png", {"angle": "90"}),
            ("rotate", "v.mp4", {"angle": "270"}), ("rotate", "two.pdf", {"angle": "180"}),
            ("flip", "a.png", {}), ("flip", "v.mp4", {"direction": "vertical"}), ("grayscale", "a.png", {}),
            ("grayscale", "v.mp4", {}), ("grayscale", "n.pdf", {}), ("strip", "b.jpg", {}), ("strip", "v.mp4", {}),
            ("extract_audio", "v.mp4", {}), ("mute", "v.mp4", {}), ("speed", "v.mp4", {"factor": "2x"}),
            ("speed", "s.wav", {"factor": "0.5x"}), ("gif", "v.mp4", {"start": "0:01", "end": "0:02"}),
            ("image_pdf", "a.png", {}), ("pdf_images", "two.pdf", {}), ("fps", "v.mp4", {"fps": "15"}),
            ("normalize", "s.wav", {}), ("normalize", "v.mp4", {}), ("fade", "s.wav", {"seconds": "0.5"}),
            ("fade", "v.mp4", {"seconds": "1"}), ("frames", "v.mp4", {"per_second": "1"}),
            ("zip", "a.png", {}), ("targz", "a.png", {}),
            ("merge", ["v.mp4", "w.mp4"], {}), ("merge", ["s.wav", "s.wav"], {}),
            ("merge", ["a.png", "b.jpg"], {})]
    for tid, src, params in runs:
        out = tool(tid, src, **params)
        assert os.path.exists(out) and (os.path.isdir(out) and os.listdir(out) or os.path.getsize(out)), (tid, src)
    assert dur(tool("speed", "v.mp4", factor="2x")) < 1.7
    assert len(os.listdir(tool("split_av", "v.mp4", parts="3"))) == 3
    assert len(os.listdir(tool("split_pdf", "two.pdf"))) == 2
    assert len(os.listdir(tool("frames", "v.mp4"))) >= 3
    assert sh("identify", "-format", "%w %h", tool("crop", "a.png", aspect="1:1")) == "48 48"
    assert sh("identify", "-format", "%w %h", tool("rotate", "a.png", angle="90")) == "48 64"
    assert streams(tool("mute", "v.mp4"), "a") == []
    assert abs(dur(tool("merge", ["v.mp4", "w.mp4"])) - 5) < 0.3
    assert pages(tool("merge", ["a.png", "b.jpg"])) == 2
    assert {t.id for t in tools.tools_for([str(D / "v.mp4")])} >= {"trim", "gif", "mute", "frames", "zip"}


@case("encrypt + decrypt pdf", needs=("qpdf",))
def _():
    enc = tool("encrypt", "two.pdf", password="s3cret pass")
    assert subprocess.run(["qpdf", "--requires-password", enc]).returncode == 0  # 0 = password required
    try:
        tools.apply(tools.BY_ID["decrypt"], [enc], {"password": "wrong"})
    except jobs.SatsumaError as e:
        assert "password" in str(e).lower(), e
    else:
        raise AssertionError("wrong password accepted")
    dec = tools.apply(tools.BY_ID["decrypt"], [enc], {"password": "s3cret pass"})[0]
    assert subprocess.run(["qpdf", "--requires-password", dec]).returncode == 2  # 2 = not encrypted
    assert pages(dec) == 2


@case("merge 2 pdfs: page count == sum", needs=("qpdf",))
def _():
    srcs = ["two.pdf", "n.pdf"] if (D / "n.pdf").exists() else ["two.pdf", "two.pdf"]
    out = tool("merge", srcs)
    assert pages(out) == sum(pages(D / s) for s in srcs), pages(out)


@case("trim duration within 0.2s", needs=("ffmpeg",))
def _():
    assert abs(dur(tool("trim", "v.mp4", start="0:00.5", end="0:02.5")) - 2.0) < 0.2
    assert abs(dur(tool("trim", "s.wav", start="0.25", end="1.25")) - 1.0) < 0.2


@case("cancel mid-job kills ffmpeg and leaves no output (atomic write)", needs=("ffmpeg",))
def _():
    sh("ffmpeg", "-f", "lavfi", "-i", "testsrc2=d=30:s=640x480:r=30", "-pix_fmt", "yuv420p", "-c:v", "libx264",
       "-preset", "ultrafast", D / "long.mp4")
    before = set(os.listdir(D))
    job = jobs.submit(lambda p: convert(p, "webm"), [str(D / "long.mp4")])
    deadline = time.time() + 10
    while not job.progress and time.time() < deadline:
        time.sleep(0.05)
    assert job.progress and 0 < job.progress < 1, job.progress  # progress parsed from ffmpeg
    job.cancel()
    assert job.finished.wait(5), "cancel did not stop the job"
    assert job.results[0][2] == "Cancelled", job.results
    assert set(os.listdir(D)) == before, set(os.listdir(D)) ^ before


@case("batch: one job, combined progress, all outputs", needs=("ffmpeg",))
def _():
    job = jobs.submit(lambda p: convert(p, "flac"), [str(D / "s.wav"), str(D / "t.mp3")])
    assert job.finished.wait(30)
    assert job.progress == 1.0 and all(r[1] and not r[2] for r in job.results), job.results


# ---------------------------------------------------------------- GUI
def gi_python():
    for py in (sys.executable, "/usr/bin/python3"):
        if subprocess.run([py, "-c", "import gi; gi.require_version('Gtk', '4.0'); from gi.repository import Gtk"],
                          capture_output=True).returncode == 0:
            return py
    return None


def free_display():
    for n in range(20, 60):
        with socket.socket() as s:
            if s.connect_ex(("127.0.0.1", 8080 + n)):
                return n
    raise RuntimeError("no free broadway port")


@case("GUI smoke test under broadway", needs=("gtk4-broadwayd",))
def _():
    py = gi_python()
    if not py:
        print("SKIP GUI smoke test: no Python with GTK 4 bindings (python3-gi)")
        return
    n = free_display()
    bd = subprocess.Popen(["gtk4-broadwayd", f":{n}"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        time.sleep(0.5)
        env = dict(os.environ, GDK_BACKEND="broadway", BROADWAY_DISPLAY=f":{n}", SATSUMA_DEMO='{"quit_after": 1}',
                   PYTHONPATH=str(ROOT))
        for args in ([], [str(D / "a.png")], ["--popup", str(D / "v.mp4"), str(D / "w.mp4")]):
            t = time.time()
            r = subprocess.run([py, "-m", "satsuma", *args], env=env, capture_output=True, text=True, timeout=5)
            assert r.returncode == 0, (args, r.stderr[-2000:])
            assert "Traceback" not in r.stderr and "CRITICAL" not in r.stderr, r.stderr[-2000:]
            assert time.time() - t < 5
    finally:
        bd.kill()


print(f"\n{len(PASSED)} passed, {len(FAILED)} failed, {len(SKIPPED)} skipped in {time.time() - t0:.1f}s")
if FAILED:
    print("FAILED:", *FAILED, sep="\n  ")
    sys.exit(1)
shutil.rmtree(TMP, ignore_errors=True)
print("ALL OK")
