"""File tools (Ctrl wheel). Each tool takes a path (or a list for multi tools) plus prompt params."""
import itertools
import os
import re
import tarfile
import tempfile
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

from . import config
from .convert import Output, pdf_pages
from .formats import ext, kind, missing, needs
from .jobs import SatsumaError, check, duration, ff, has_stream, probe, run


@dataclass
class Field:
    key: str
    label: str
    default: object = ""  # str, or callable(path) -> str
    choices: tuple = ()
    secret: bool = False


@dataclass
class Tool:
    id: str
    label: str
    kinds: set
    fn: object
    fields: list = field(default_factory=list)
    multi: bool = False  # takes the whole selection at once
    needs: tuple = ()  # binaries the PDF variant needs (image/audio/video variants use hard deps)


def parse_time(s):
    """'90', '1:30', '0:01:30.5' -> seconds."""
    s = str(s).strip()
    if not s:
        raise SatsumaError("Enter a time like 1:30")
    try:
        secs = 0.0
        for part in s.split(":"):
            secs = secs * 60 + float(part)
        return secs
    except ValueError:
        raise SatsumaError(f"'{s}' isn't a time (try 1:30 or 90)") from None


def fmt_time(t):
    m, s = divmod(max(t, 0), 60)
    return f"{int(m)}:{s:05.2f}".rstrip("0").rstrip(".") if s % 1 else f"{int(m)}:{int(s):02d}"


def dims(src):
    if kind(src) == "image":
        w, h = run(["identify", "-format", "%w %h", src + "[0]"]).split()
    else:
        w, h = probe(src, "stream=width,height", "v:0").split(",")
    return int(w), int(h)


def same(src, tag):
    return Output(src, ext(src) if kind(src) != "image" or ext(src) != "svg" else "png", tag)


def keep_audio(src):
    return ["-c:a", "aac", "-b:a", "160k"] if has_stream(src, "a") else ["-an"]


def vencode(src):
    """Re-encode settings that keep the source container valid."""
    if ext(src) == "webm":
        return ["-c:v", "libvpx-vp9", "-b:v", "0", "-crf", "33", "-row-mt", "1", "-deadline", "good", "-cpu-used", "4",
                *(["-c:a", "libopus"] if has_stream(src, "a") else ["-an"])]
    if ext(src) == "gif":
        return []
    crf = config.CRF[config.get()["video_quality"]][0]
    return ["-c:v", "libx264", "-crf", str(crf), "-preset", "medium", "-pix_fmt", "yuv420p", *keep_audio(src)]


def vf(src, chain, tag, audio_args=()):
    with same(src, tag) as o:
        ff(src, o.tmp, "-vf", chain, *vencode(src), *audio_args)
    return o.path


# ---------------------------------------------------------------- tools
def compress(src):
    k = kind(src)
    with same(src, " compressed") as o:
        if k == "image":
            q = min(int(config.get()["image_quality"]), 75)
            run(["convert", src, "-auto-orient", "-strip", "-quality", str(q),
                 "-define", "png:compression-level=9", o.tmp])
        elif k == "video":
            crf = config.CRF[config.get()["video_quality"]][0] + 5
            args = vencode(src)
            if "-crf" in args:
                args[args.index("-crf") + 1] = str(crf)
            ff(src, o.tmp, *args)
        elif k == "audio":
            ff(src, o.tmp, "-vn", "-b:a", "96k")
        else:
            run(["gs", "-q", "-dNOPAUSE", "-dBATCH", "-dSAFER", "-sDEVICE=pdfwrite", "-dPDFSETTINGS=/ebook",
                 f"-sOutputFile={o.tmp}", src])
    return o.path


def resize(src, size="50%"):
    s = str(size).strip().rstrip("px")
    pct = s.endswith("%")
    try:
        n = float(s.rstrip("%"))
    except ValueError:
        raise SatsumaError("Enter a percentage like 50% or a max side like 1280") from None
    if n <= 0:
        raise SatsumaError("Size must be more than zero")
    if kind(src) == "image":
        with same(src, " resized") as o:
            run(["convert", src, "-auto-orient", "-resize", f"{n:g}%" if pct else f"{int(n)}x{int(n)}>", o.tmp])
        return o.path
    if pct:
        chain = f"scale=trunc(iw*{n / 100:g}/2)*2:-2"
    else:
        n = int(n)
        chain = f"scale='if(gt(iw,ih),min({n},iw),-2)':'if(gt(iw,ih),-2,min({n},ih))'"
    return vf(src, chain, " resized")


def _aspect(a):
    try:
        w, h = (float(x) for x in re.split(r"[:x/]", str(a).strip()))
        return w / h
    except (ValueError, ZeroDivisionError):
        raise SatsumaError("Enter an aspect ratio like 16:9") from None


def _fit(w, h, r):
    """Largest centered box of ratio r inside w x h (even sizes)."""
    cw, ch = (h * r, h) if w / h > r else (w, w / r)
    return int(cw) // 2 * 2, int(ch) // 2 * 2


def crop(src, aspect="1:1"):
    r, k = _aspect(aspect), kind(src)
    if k == "pdf":
        info = run(["pdfinfo", src])
        m = re.search(r"Page size:\s+([\d.]+) x ([\d.]+)", info)
        w, h = float(m.group(1)), float(m.group(2))
        cw, ch = (h * r, h) if w / h > r else (w, w / r)
        x0, y0 = (w - cw) / 2, (h - ch) / 2
        with same(src, " cropped") as o:
            run(["gs", "-q", "-dNOPAUSE", "-dBATCH", "-dSAFER", "-sDEVICE=pdfwrite", f"-sOutputFile={o.tmp}",
                 "-c", f"[/CropBox [{x0:.2f} {y0:.2f} {x0 + cw:.2f} {y0 + ch:.2f}] /PAGES pdfmark", "-f", src])
        return o.path
    w, h = dims(src)
    cw, ch = _fit(w, h, r)
    if k == "image":
        with same(src, " cropped") as o:
            run(["convert", src, "-auto-orient", "-gravity", "center", "-crop", f"{cw}x{ch}+0+0", "+repage", o.tmp])
        return o.path
    return vf(src, f"crop={cw}:{ch}", " cropped")


def trim(src, start="0:00", end=""):
    a, b = parse_time(start), parse_time(end) if str(end).strip() else duration(src)
    if b <= a:
        raise SatsumaError("End must be after start")
    with same(src, " trimmed") as o:
        if kind(src) == "video":
            ff(src, o.tmp, "-t", f"{b - a:.3f}", *vencode(src), pre=["-ss", f"{a:.3f}"], dur=b - a)
        else:
            ff(src, o.tmp, "-t", f"{b - a:.3f}", "-vn", pre=["-ss", f"{a:.3f}"], dur=b - a)
    return o.path


def split_pdf(src, every="1"):
    try:
        n = int(every)
    except ValueError:
        raise SatsumaError("Enter how many pages per file, like 1 or 5") from None
    with Output(src, "", " split") as o:
        run(["qpdf", src, f"--split-pages={max(n, 1)}", os.path.join(o.tmp, Path(src).stem + ".pdf")])
    return o.path


def split_av(src, parts="2"):
    """'3' -> three equal parts; '0:30, 1:15' -> cut at those timestamps."""
    total = duration(src)
    p = str(parts).strip()
    if re.fullmatch(r"\d+", p):
        n = int(p)
        if n < 2:
            raise SatsumaError("Split into at least 2 parts")
        cuts = [total * i / n for i in range(1, n)]
    else:
        cuts = sorted(parse_time(x) for x in p.split(",") if x.strip())
    edges = [0.0] + [c for c in cuts if 0 < c < total] + [total]
    e = ext(src)
    with Output(src, "", " parts") as o:
        for i, (a, b) in enumerate(itertools.pairwise(edges), 1):
            args = vencode(src) if kind(src) == "video" else ["-vn"]
            ff(src, os.path.join(o.tmp, f"{Path(src).stem} {i}.{e}"), "-t", f"{b - a:.3f}", *args,
               pre=["-ss", f"{a:.3f}"], dur=b - a)
    return o.path


def merge(srcs):
    k, first = kind(srcs[0]), srcs[0]
    if k == "pdf":
        with Output(first, "pdf", " merged") as o:
            run(["qpdf", "--empty", "--pages", *srcs, "--", o.tmp])
        return o.path
    if k == "image":
        with Output(first, "pdf", " merged") as o:
            run(["convert", *srcs, "-auto-orient", o.tmp])
        return o.path
    n, total = len(srcs), sum(duration(s) for s in srcs)
    ins = [a for s in srcs for a in ("-i", s)]
    if k == "video":
        w, h = dims(first)
        audio = all(has_stream(s, "a") for s in srcs)
        parts = "".join(f"[{i}:v]scale={w}:{h}:force_original_aspect_ratio=decrease,pad={w}:{h}:(ow-iw)/2:(oh-ih)/2,"
                        f"setsar=1,fps=30,format=yuv420p[v{i}];" for i in range(n))
        if audio:
            parts += "".join(f"[{i}:a]aresample=48000[a{i}];" for i in range(n))
        streams = "".join(f"[v{i}]" + (f"[a{i}]" if audio else "") for i in range(n))
        graph = parts + f"{streams}concat=n={n}:v=1:a={int(audio)}[v]" + ("[a]" if audio else "")
        maps = ["-map", "[v]"] + (["-map", "[a]"] if audio else [])
        enc = vencode(first) if ext(first) != "gif" else []
        enc = [x for x in enc if x != "-an"]
    else:
        graph = "".join(f"[{i}:a]" for i in range(n)) + f"concat=n={n}:v=0:a=1[a]"
        maps, enc = ["-map", "[a]"], []
    with Output(first, ext(first), " merged") as o:
        run(["ffmpeg", "-y", "-nostdin", "-hide_banner", "-loglevel", "error", *ins, "-filter_complex", graph,
             *maps, *enc, o.tmp], duration=total or None)
    return o.path


def rotate(src, angle="90"):
    a = str(angle).rstrip("°")
    if a not in ("90", "180", "270"):
        raise SatsumaError("Rotate by 90, 180 or 270")
    k = kind(src)
    if k == "image":
        with same(src, " rotated") as o:
            run(["convert", src, "-auto-orient", "-rotate", a, o.tmp])
        return o.path
    if k == "pdf":
        with same(src, " rotated") as o:
            run(["qpdf", src, o.tmp, f"--rotate=+{a}"])
        return o.path
    return vf(src, {"90": "transpose=1", "180": "hflip,vflip", "270": "transpose=2"}[a], " rotated")


def flip(src, direction="horizontal"):
    h = str(direction).lower().startswith("h")
    if kind(src) == "image":
        with same(src, " flipped") as o:
            run(["convert", src, "-auto-orient", "-flop" if h else "-flip", o.tmp])
        return o.path
    return vf(src, "hflip" if h else "vflip", " flipped")


def grayscale(src):
    k = kind(src)
    with same(src, " gray") as o:
        if k == "image":
            run(["convert", src, "-auto-orient", "-colorspace", "Gray", o.tmp])
        elif k == "pdf":
            run(["gs", "-q", "-dNOPAUSE", "-dBATCH", "-dSAFER", "-sDEVICE=pdfwrite",
                 "-sColorConversionStrategy=Gray", "-dProcessColorModel=/DeviceGray", f"-sOutputFile={o.tmp}", src])
        else:
            ff(src, o.tmp, "-vf", "hue=s=0", *vencode(src))
    return o.path


def strip_metadata(src):
    with same(src, " clean") as o:
        if kind(src) == "image":
            run(["convert", src, "-strip", o.tmp])
        else:
            ff(src, o.tmp, "-map", "0", "-map_metadata", "-1", "-map_chapters", "-1", "-c", "copy")
    return o.path


def extract_audio(src):
    if not has_stream(src, "a"):
        raise SatsumaError("This video has no audio track")
    with Output(src, "m4a") as o:
        ff(src, o.tmp, "-vn", "-c:a", "aac", "-b:a", "192k")
    return o.path


def mute(src):
    with same(src, " muted") as o:
        ff(src, o.tmp, "-an", "-c:v", "copy")
    return o.path


def speed(src, factor="2x"):
    try:
        f = float(str(factor).rstrip("x×"))
    except ValueError:
        raise SatsumaError("Pick a speed like 0.5x or 2x") from None
    if not 0.5 <= f <= 2:
        raise SatsumaError("Speed must be between 0.5x and 2x")
    tag = f" {f:g}x"
    if kind(src) == "audio":
        with same(src, tag) as o:
            ff(src, o.tmp, "-vn", "-af", f"atempo={f:g}", dur=duration(src) / f)
        return o.path
    aud = ["-af", f"atempo={f:g}"] if has_stream(src, "a") else []
    with same(src, tag) as o:
        ff(src, o.tmp, "-vf", f"setpts=PTS/{f:g}", *aud, *vencode(src), dur=duration(src) / f)
    return o.path


def to_gif(src, start="0:00", end=""):
    a = parse_time(start)
    b = parse_time(end) if str(end).strip() else duration(src)
    if b <= a:
        raise SatsumaError("End must be after start")
    with Output(src, "gif") as o:
        ff(src, o.tmp, "-t", f"{b - a:.3f}", "-vf",
           "fps=12,scale='min(480,iw)':-2:flags=lanczos,split[a][b];[a]palettegen[p];[b][p]paletteuse",
           "-loop", "0", pre=["-ss", f"{a:.3f}"], dur=b - a)
    return o.path


def image_to_pdf(src):
    with Output(src, "pdf") as o:
        run(["convert", src, "-auto-orient", o.tmp])
    return o.path


def pdf_to_images(src):
    return pdf_pages(src, "png")


def reduce_fps(src, fps="24"):
    try:
        n = float(fps)
    except ValueError:
        raise SatsumaError("Enter frames per second, like 24") from None
    return vf(src, f"fps={n:g}", f" {n:g}fps")


def normalize(src):
    with same(src, " normalized") as o:
        if kind(src) == "video":
            if not has_stream(src, "a"):
                raise SatsumaError("This video has no audio track")
            ff(src, o.tmp, "-af", "loudnorm=I=-16:TP=-1.5:LRA=11", "-c:v", "copy",
               *(["-c:a", "libopus"] if ext(src) == "webm" else ["-c:a", "aac", "-b:a", "192k"]))
        else:
            ff(src, o.tmp, "-vn", "-af", "loudnorm=I=-16:TP=-1.5:LRA=11", "-ar", "48000")
    return o.path


def fade(src, seconds="1"):
    try:
        s = float(seconds)
    except ValueError:
        raise SatsumaError("Enter fade length in seconds, like 1") from None
    d = duration(src)
    s = min(s, d / 2)
    af = f"afade=t=in:d={s:g},afade=t=out:st={d - s:.3f}:d={s:g}"
    with same(src, " faded") as o:
        if kind(src) == "audio":
            ff(src, o.tmp, "-vn", "-af", af)
        else:
            aud = ["-af", af] if has_stream(src, "a") else []
            ff(src, o.tmp, "-vf", f"fade=t=in:d={s:g},fade=t=out:st={d - s:.3f}:d={s:g}", *aud, *vencode(src))
    return o.path


def extract_frames(src, per_second="1"):
    try:
        n = float(per_second)
    except ValueError:
        raise SatsumaError("Enter frames per second, like 1") from None
    with Output(src, "", " frames") as o:
        ff(src, os.path.join(o.tmp, "frame-%04d.png"), "-vf", f"fps={n:g}")
    return o.path


def _bundle_name(srcs):
    return srcs[0] if len(srcs) == 1 else os.path.join(os.path.dirname(srcs[0]), "Archive")


def zip_files(srcs):
    srcs = [srcs] if isinstance(srcs, str) else srcs
    with Output(_bundle_name(srcs), "zip") as o, zipfile.ZipFile(o.tmp, "w", zipfile.ZIP_DEFLATED) as z:
        for s in srcs:
            base = os.path.dirname(os.path.abspath(s))
            if os.path.isdir(s):
                for root, _, files in os.walk(s):
                    for f in files:
                        check()
                        p = os.path.join(root, f)
                        z.write(p, os.path.relpath(p, base))
            else:
                z.write(s, os.path.basename(s))
    return o.path


def tar_gz(srcs):
    srcs = [srcs] if isinstance(srcs, str) else srcs
    with Output(_bundle_name(srcs), "tar.gz") as o, tarfile.open(o.tmp, "w:gz") as t:
        for s in srcs:
            t.add(s, os.path.basename(os.path.abspath(s)))
    return o.path


def _qpdf_argfile(args):
    """Pass passwords to qpdf through a private @file, not argv (visible in ps)."""
    with tempfile.NamedTemporaryFile("w", delete=False, prefix="satsuma-") as f:  # mkstemp: mode 0600
        f.write("\n".join(args))
    return f.name


def encrypt_pdf(src, password=""):
    if not password:
        raise SatsumaError("Enter a password")
    with same(src, " encrypted") as o:
        af = _qpdf_argfile(["--encrypt", password, password, "256", "--"])
        try:
            run(["qpdf", f"@{af}", src, o.tmp])
        finally:
            os.unlink(af)
    return o.path


def decrypt_pdf(src, password=""):
    with same(src, " decrypted") as o:
        af = _qpdf_argfile([f"--password={password}", "--decrypt"])
        try:
            run(["qpdf", f"@{af}", src, o.tmp])
        finally:
            os.unlink(af)
    return o.path


def _end(src):
    return fmt_time(duration(src))


IMG, VID, AUD, PDF = "image", "video", "audio", "pdf"
TIME_FIELDS = [Field("start", "Start", "0:00"), Field("end", "End", _end)]
TOOLS = [
    Tool("compress", "Compress", {IMG, VID, AUD, PDF}, compress, needs=("gs",)),
    Tool("resize", "Resize", {IMG, VID}, resize, [Field("size", "Size (50% or max side px)", "50%")]),
    Tool("crop", "Crop", {IMG, VID, PDF}, crop,
         [Field("aspect", "Aspect ratio", "1:1", ("1:1", "4:3", "3:2", "16:9", "9:16", "4:5"))], needs=("gs",)),
    Tool("trim", "Trim", {AUD, VID}, trim, TIME_FIELDS),
    Tool("split_pdf", "Split", {PDF}, split_pdf, [Field("every", "Pages per file", "1")], needs=("qpdf",)),
    Tool("split_av", "Split", {AUD, VID}, split_av, [Field("parts", "Parts (3) or cut at (0:30, 1:15)", "2")]),
    Tool("merge", "Merge", {PDF, IMG, VID, AUD}, merge, multi=True, needs=("qpdf",)),
    Tool("rotate", "Rotate", {IMG, VID, PDF}, rotate, [Field("angle", "Rotate by", "90", ("90", "180", "270"))],
         needs=("qpdf",)),
    Tool("flip", "Flip", {IMG, VID}, flip, [Field("direction", "Flip", "horizontal", ("horizontal", "vertical"))]),
    Tool("grayscale", "Grayscale", {IMG, VID, PDF}, grayscale, needs=("gs",)),
    Tool("strip", "Strip metadata", {IMG, VID, AUD}, strip_metadata),
    Tool("extract_audio", "Extract audio", {VID}, extract_audio),
    Tool("mute", "Mute", {VID}, mute),
    Tool("speed", "Speed", {VID, AUD}, speed, [Field("factor", "Speed", "2x", ("0.5x", "1.5x", "2x"))]),
    Tool("gif", "To GIF", {VID}, to_gif, TIME_FIELDS),
    Tool("image_pdf", "To PDF", {IMG}, image_to_pdf),
    Tool("pdf_images", "To images", {PDF}, pdf_to_images, needs=("pdftoppm",)),
    Tool("fps", "Frame rate", {VID}, reduce_fps, [Field("fps", "Frames per second", "24", ("30", "24", "15"))]),
    Tool("normalize", "Normalize", {AUD, VID}, normalize),
    Tool("fade", "Fade in/out", {AUD, VID}, fade, [Field("seconds", "Fade length (s)", "1")]),
    Tool("frames", "Frames", {VID}, extract_frames, [Field("per_second", "Frames per second", "1")]),
    Tool("encrypt", "Encrypt", {PDF}, encrypt_pdf, [Field("password", "Password", "", secret=True)], needs=("qpdf",)),
    Tool("decrypt", "Decrypt", {PDF}, decrypt_pdf, [Field("password", "Password", "", secret=True)], needs=("qpdf",)),
    Tool("zip", "Zip", {"*"}, zip_files, multi=True),
    Tool("targz", "Tar.gz", {"*"}, tar_gz, multi=True),
]
BY_ID = {t.id: t for t in TOOLS}


def tools_for(paths):
    """Tools offered for a selection: same kind -> that kind's tools; mixed -> Zip only."""
    kinds = {kind(p) for p in paths}
    if len(kinds) != 1:
        return [BY_ID["zip"]]
    k, out = kinds.pop(), []
    undecodable = k == IMG and any(missing(needs(k, ext(p), "png")) for p in paths)  # e.g. HEIC w/o libde265
    for t in TOOLS:
        if not (k in t.kinds or "*" in t.kinds) or (undecodable and "*" not in t.kinds):
            continue
        if t.id == "merge" and len(paths) < 2:
            continue
        if t.id == "mute" and ext(paths[0]) == "gif":
            continue
        if k == PDF and missing(t.needs):
            continue
        out.append(t)
    return out


def apply(tool, paths, params=None):
    """Run a tool synchronously over a selection; returns list of outputs (CLI + tests)."""
    from .jobs import run_now
    params = params or {}
    if tool.multi:
        return [run_now(lambda ps: tool.fn(ps, **params), list(paths))]
    return [run_now(lambda p: tool.fn(p, **params), p) for p in paths]


def defaults(tool, path):
    return {f.key: f.default(path) if callable(f.default) else f.default for f in tool.fields}
