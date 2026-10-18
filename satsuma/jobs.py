"""Job runner: subprocesses with progress + cancel, a thread pool for batches."""
import logging
import os
import re
import signal
import subprocess
import tempfile
import threading
from concurrent.futures import ThreadPoolExecutor

from . import config

log = logging.getLogger("satsuma")
_local = threading.local()
_pool = ThreadPoolExecutor(max_workers=max(1, (os.cpu_count() or 2) // 2))


class SatsumaError(Exception):
    """A failure with a message fit for humans."""


class Cancelled(Exception):
    pass


FRIENDLY = [
    (r"does not contain any stream|matches no streams|Output file is empty", "This file has no audio track"),
    (r"moov atom not found|Invalid data found when processing input|could not find codec parameters",
     "This file looks damaged or isn't really a {ext} file"),
    (r"(?i)invalid password|password is incorrect|file is encrypted", "This PDF is password-protected (or the password is wrong)"),
    (r"No space left on device", "The disk is full"),
    (r"Permission denied|Read-only file system", "Satsuma can't write to this folder"),
    (r"no decode delegate|NoDecodeDelegate|improper image header", "This image format can't be read"),
    (r"(?i)syntax error|not a pdf|can't find startxref", "This PDF looks damaged"),
]


def setup_logging():
    if not log.handlers:
        h = logging.FileHandler(config.cache_dir() / "satsuma.log")
        h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        log.addHandler(h)
        log.setLevel(logging.INFO)


def friendly(stderr, cmd):
    src = next((c for c in reversed(cmd[:-1]) if os.path.exists(c)), "")
    e = os.path.splitext(src)[1].lstrip(".").upper() or "media"
    for pat, msg in FRIENDLY:
        if re.search(pat, stderr):
            return msg.format(ext=e)
    last = (stderr.strip().splitlines() or [""])[-1][:160]
    return f"{os.path.basename(cmd[0])} failed: {last}" if last else f"{os.path.basename(cmd[0])} failed"


def check():
    t = getattr(_local, "task", None)
    if t and t.job.cancelled.is_set():
        raise Cancelled()


def _kill(p):
    try:
        os.killpg(p.pid, signal.SIGKILL)  # whole group: soffice and ffmpeg helpers too
    except (ProcessLookupError, PermissionError):
        pass


def run(cmd, duration=None, timeout=None, cwd=None):
    """Run a tool; returns stdout. ffmpeg + duration -> live progress for the current task."""
    setup_logging()
    check()
    cmd = [str(c) for c in cmd]
    t = getattr(_local, "task", None)
    if duration and os.path.basename(cmd[0]) == "ffmpeg":
        cmd[1:1] = ["-progress", "pipe:1", "-nostats"]
    timed_out = []
    with tempfile.TemporaryFile() as err:
        p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=err, stdin=subprocess.DEVNULL, text=True,
                             cwd=cwd, start_new_session=True, errors="replace")
        if t:
            t.proc = p
            if t.job.cancelled.is_set():
                _kill(p)
        timer = None
        if timeout:
            timer = threading.Timer(timeout, lambda: (timed_out.append(1), _kill(p)))
            timer.start()
        out = []
        for line in p.stdout:
            if duration and line.startswith("out_time_us="):
                v = line.split("=", 1)[1].strip()
                if v.isdigit() and t:
                    t.progress = min(1.0, int(v) / 1e6 / duration)
            elif not duration:
                out.append(line)
        p.wait()
        if timer:
            timer.cancel()
        if t:
            t.proc = None
        if t and t.job.cancelled.is_set():
            raise Cancelled()
        if timed_out:
            log.error("timeout after %ss: %s", timeout, cmd)
            raise SatsumaError(f"{os.path.basename(cmd[0])} took too long and was stopped")
        if p.returncode:
            err.seek(0)
            stderr = err.read().decode(errors="replace")
            log.error("failed (%s): %s\n%s", p.returncode, " ".join(cmd), stderr)
            raise SatsumaError(friendly(stderr + "".join(out), cmd))
    return "".join(out)


def probe(path, entry="format=duration", stream=None):
    cmd = ["ffprobe", "-v", "error", "-show_entries", entry, "-of", "csv=p=0"]
    if stream:
        cmd += ["-select_streams", stream]
    try:
        return run(cmd + [path]).strip()
    except SatsumaError:
        return ""


def duration(path):
    try:
        return float(probe(path))
    except ValueError:
        return 0.0


def has_stream(path, s="a"):
    return bool(probe(path, "stream=index", s))


def ff(src, dst, *args, pre=(), dur=None):
    """ffmpeg src -> dst with progress against the source duration."""
    if dur is None:
        dur = duration(src)
    return run(["ffmpeg", "-y", "-nostdin", "-hide_banner", "-loglevel", "error", *pre, "-i", src, *args, dst],
               duration=dur or None)


class Task:
    def __init__(self, job, item):
        self.job, self.item, self.proc, self.progress, self.done = job, item, None, None, False


class Job:
    """One user action over one or many items. progress: 0..1, or None when indeterminate."""

    def __init__(self, fn, items, on_done=None):
        self.fn, self.cancelled, self.on_done = fn, threading.Event(), on_done
        self.tasks = [Task(self, i) for i in items]
        self.results = [None] * len(self.tasks)  # (item, output path or None, error message or None)
        self._lock = threading.Lock()
        self.finished = threading.Event()

    @property
    def progress(self):
        if len(self.tasks) == 1:
            t = self.tasks[0]
            return 1.0 if t.done else t.progress
        return sum(1.0 if t.done else (t.progress or 0) for t in self.tasks) / len(self.tasks)

    def cancel(self):
        self.cancelled.set()
        for t in self.tasks:
            if t.proc:
                _kill(t.proc)

    def _run(self, t):
        _local.task = t
        try:
            res = (t.item, self.fn(t.item), None)
        except Cancelled:
            res = (t.item, None, "Cancelled")
        except SatsumaError as e:
            res = (t.item, None, str(e))
        except Exception as e:  # unexpected: keep the app alive, keep the trace
            log.exception("job crashed on %s", t.item)
            res = (t.item, None, f"Something went wrong: {e}")
        finally:
            _local.task = None
        with self._lock:
            t.done = True
            self.results[self.tasks.index(t)] = res
            last = all(x.done for x in self.tasks)
        if last:
            self.finished.set()
            if self.on_done:
                self.on_done(self)


def submit(fn, items, on_done=None):
    job = Job(fn, items, on_done)
    for t in job.tasks:
        _pool.submit(job._run, t)
    return job


def run_now(fn, item):
    """Synchronous single-item run (CLI, tests). Raises SatsumaError on failure."""
    job = submit(fn, [item])
    job.finished.wait()
    _, out, err = job.results[0]
    if err:
        raise SatsumaError(err)
    return out
