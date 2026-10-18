#!/usr/bin/python3
"""Runs real conversions in a temp dir. python3 test_tangerine.py"""
import os, subprocess, tempfile, sys
from pathlib import Path
sys.path.insert(0, os.path.dirname(__file__))
import tangerine as t

d = Path(tempfile.mkdtemp())
sh = lambda *c: subprocess.run(c, check=True, capture_output=True)
sh("convert", "-size", "64x48", "gradient:orange-black", str(d / "a.png"))
sh("ffmpeg", "-f", "lavfi", "-i", "sine=d=1", str(d / "s.wav"))
sh("ffmpeg", "-f", "lavfi", "-i", "testsrc=d=1:s=160x120", "-f", "lavfi", "-i", "sine=d=1", "-shortest", "-pix_fmt", "yuv420p", str(d / "v.mp4"))
(d / "n.md").write_text("# Hi\n\nhello **world**\n")
(d / "t.csv").write_text("a,b\n1,\"x,y\"\n")
(d / "c.srt").write_text("1\n00:00:01,000 --> 00:00:02,000\n<i>Hello</i>\n\n")
sh("pandoc", str(d / "n.md"), "-o", str(d / "n.html"))

cases = [("a.png", "jpg"), ("a.png", "webp"), ("a.png", "avif"), ("a.png", "pdf"), ("s.wav", "mp3"), ("s.wav", "m4a"),
         ("v.mp4", "gif"), ("v.mp4", "webm"), ("v.mp4", "mp3"), ("n.md", "docx"), ("n.md", "epub"),
         ("t.csv", "tsv"), ("c.srt", "vtt"), ("c.srt", "txt")]
for src, to in cases:
    out = t.convert(str(d / src), to)
    assert os.path.getsize(out) > 0, (src, to)
    print("ok", src, "->", Path(out).name)

pdf = str(d / "a.pdf")
assert len(os.listdir(t.convert(pdf, "png"))) == 1
assert "hello" in Path(t.convert(str(d / "n.docx"), "txt")).read_text()
assert (d / "t.tsv").read_bytes() == b"a\tb\r\n1\tx,y\r\n"
assert (d / "c.txt").read_text() == "Hello\n"
assert t.out_path(str(d / "a.png"), "jpg").endswith("a 2.jpg")  # no overwrite
z = t.zip_it(str(d / "a.png")); assert t.convert(z, "extract")
for name, fn in t.tools(str(d / "v.mp4")):
    if name not in ("zip", "tar.gz"):
        assert os.path.getsize(fn(str(d / "v.mp4"))) > 0, name
print("ALL OK", d)
