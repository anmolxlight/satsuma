"""Nautilus extension (python3-nautilus): right-click > Satsuma… opens the wheel for the selection."""
import subprocess
from urllib.parse import unquote, urlparse

import gi

try:
    gi.require_version("Nautilus", "4.0")
except ValueError:
    gi.require_version("Nautilus", "3.0")
from gi.repository import GObject, Nautilus  # noqa: E402


class SatsumaMenu(GObject.GObject, Nautilus.MenuProvider):
    def _open(self, _item, files):
        paths = [unquote(urlparse(f.get_uri()).path) for f in files if f.get_uri_scheme() == "file"]
        if paths:
            subprocess.Popen(["satsuma", "--popup", *paths], start_new_session=True)

    def get_file_items(self, *args):
        files = args[-1]  # Nautilus 4: (files); Nautilus 3: (window, files)
        if not files or any(f.get_uri_scheme() != "file" for f in files):
            return []
        item = Nautilus.MenuItem(name="Satsuma::Open", label="Satsuma…", tip="Convert, tools and actions")
        item.connect("activate", self._open, files)
        return [item]
