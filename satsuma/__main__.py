"""satsuma [FILE...] | --popup FILE... | --convert FILE FORMAT | --tool ID FILE... [key=value...] | --list FILE"""
import argparse
import os
import sys

from . import __version__


def cli(args):
    from . import formats, tools
    from .convert import convert
    from .jobs import SatsumaError, run_now
    try:
        if args.convert:
            src, to = args.convert
            print(run_now(lambda p: convert(p, formats.norm(to)), src))
        elif args.tool:
            tid, rest = args.tool[0], args.tool[1:]
            if tid not in tools.BY_ID:
                sys.exit(f"satsuma: unknown tool '{tid}'. Tools: {', '.join(tools.BY_ID)}")
            paths = [a for a in rest if "=" not in a or os.path.exists(a)]
            params = dict(a.split("=", 1) for a in rest if a not in paths)
            for out in tools.apply(tools.BY_ID[tid], paths, params):
                print(out)
        else:
            p = args.list
            print(f"kind: {formats.kind(p)}")
            print("convert:", " ".join(formats.options(p)) or "-")
            print("tools:", " ".join(t.id for t in tools.tools_for([p])))
    except (SatsumaError, OSError) as e:
        sys.exit(f"satsuma: {e}")


def main(argv=None):
    ap = argparse.ArgumentParser(prog="satsuma", description="Zero-click offline file converter.")
    ap.add_argument("--version", action="version", version=f"satsuma {__version__}")
    ap.add_argument("--convert", nargs=2, metavar=("FILE", "FORMAT"), help="convert a file and print the output path")
    ap.add_argument("--tool", nargs="+", metavar="ARG", help="run a file tool: --tool trim a.mp4 start=0:05 end=0:10")
    ap.add_argument("--list", metavar="FILE", help="show what Satsuma can do with a file")
    ap.add_argument("--popup", action="store_true", help="borderless wheel at the pointer (file manager integration)")
    ap.add_argument("--wheel", choices=("convert", "tools", "actions"), help="wheel to open first")
    ap.add_argument("files", nargs="*")
    args = ap.parse_args(argv)
    if args.convert or args.tool or args.list:
        return cli(args)
    if args.popup and not args.files:
        ap.error("--popup needs at least one file")
    from .ui.window import run_gui
    sys.exit(run_gui([os.path.abspath(f) for f in args.files], popup=args.popup, wheel=args.wheel))


if __name__ == "__main__":
    main()
