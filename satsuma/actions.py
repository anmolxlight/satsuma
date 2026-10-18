"""File actions (Alt wheel). Work on files, folders and mixed selections."""
import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote

from .convert import free

TERMINALS = ("x-terminal-emulator", "gnome-terminal", "kgx", "ptyxis", "konsole", "xfce4-terminal",
             "tilix", "alacritty", "kitty", "wezterm", "foot", "xterm")


@dataclass
class Action:
    id: str
    label: str
    gui: bool = False  # needs the window (clipboard, folder chooser, preview)


def uri_list(paths):
    return "".join(f"file://{quote(os.path.abspath(p))}\r\n" for p in paths)


def gnome_copied_files(paths):
    """x-special/gnome-copied-files payload: what Nautilus/Nemo/Caja paste from."""
    return "copy\n" + "\n".join(f"file://{quote(os.path.abspath(p))}" for p in paths)


def move(paths, dest):
    out = []
    for p in paths:
        target = free(os.path.join(dest, os.path.basename(os.path.abspath(p))))
        shutil.move(p, target)
        out.append(target)
    return out


def show_in_folder(paths):
    """Open the file manager with the files selected; plain folder open as a fallback."""
    uris = [f"file://{quote(os.path.abspath(p))}" for p in paths]
    from gi.repository import Gio, GLib
    try:
        bus = Gio.bus_get_sync(Gio.BusType.SESSION)
        bus.call_sync("org.freedesktop.FileManager1", "/org/freedesktop/FileManager1",
                      "org.freedesktop.FileManager1", "ShowItems", GLib.Variant("(ass)", (uris, "")),
                      None, Gio.DBusCallFlags.NONE, 3000)
        return
    except GLib.Error:  # no FileManager1 service
        pass
    folder = paths[0] if os.path.isdir(paths[0]) and len(paths) == 1 else os.path.dirname(os.path.abspath(paths[0]))
    subprocess.Popen(["xdg-open", folder], start_new_session=True)


def terminal(paths):
    d = paths[0] if os.path.isdir(paths[0]) else os.path.dirname(os.path.abspath(paths[0]))
    for t in TERMINALS:
        if shutil.which(t):
            subprocess.Popen([t], cwd=d, start_new_session=True)
            return
    raise RuntimeError("No terminal app found")


def trash(paths):
    from gi.repository import Gio
    for p in paths:
        Gio.File.new_for_path(p).trash(None)


def sender():
    if shutil.which("localsend") or shutil.which("localsend_app"):
        return "localsend"
    if shutil.which("kdeconnect-cli"):
        return "kdeconnect"
    return None


def send(paths):
    s = sender()
    if s == "localsend":
        subprocess.Popen([shutil.which("localsend") or "localsend_app", *paths], start_new_session=True)
    elif s == "kdeconnect":
        dev = subprocess.run(["kdeconnect-cli", "-a", "--id-only"], capture_output=True, text=True,
                             check=False).stdout.split()
        if not dev:
            raise RuntimeError("No paired KDE Connect device is reachable")
        for p in paths:
            subprocess.run(["kdeconnect-cli", "-d", dev[0], "--share", p], check=True)


RUN = {"show": show_in_folder, "terminal": terminal, "trash": trash, "send": send}


def actions_for(paths):
    acts = [Action("copy", "Copy", True), Action("copy_path", "Copy path", True), Action("move", "Move to…", True),
            Action("show", "Show in folder"), Action("terminal", "Terminal"), Action("trash", "Trash"),
            Action("float", "Float", True)]
    if sender():
        acts.append(Action("send", "Send"))
    if not any(Path(p).is_file() for p in paths):
        acts = [a for a in acts if a.id != "float"]
    return acts
