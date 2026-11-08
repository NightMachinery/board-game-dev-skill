#!/usr/bin/env python3
"""Run heavy jobs under the project's RAM, slot and mode guard.

Every command that compiles, tests, builds, lints, installs, launches a
browser or runs codex goes through this script, usually via the Makefile:

  heavy.py run --kind KIND [--wait SECONDS] -- CMD...
  heavy.py status
  heavy.py stop-all [--grace SECONDS]
  heavy.py mode [continuous|nightshift|paused] [--window HH:MM-HH:MM]

Kinds: test, build, check, lint, browser, codex, install, fuzz, bench, light.
"light" is for cheap work: it needs no slot and every mode allows it.

A run passes three gates, checked in this order:

Mode gate
  The mode lives in RUN_DIR/mode.json. A missing file means "continuous".
  "paused" refuses every kind except light. "nightshift" refuses every kind
  except light outside its window (local time, default 00:00-10:00; a window
  such as 22:00-06:00 wraps past midnight). A refusal is immediate.

Pressure gate (heavy slots)
  Memory pressure sets the number of heavy slots: critical 0, warn 1,
  normal 2 (3 inside the nightshift window). macOS reads the sysctls
  kern.memorystatus_vm_pressure_level (1 normal, 2 warn, 4 critical),
  kern.memorystatus_level (percent free) and vm.swapusage. Linux reads
  /proc/meminfo and calls MemAvailable below 15% warn and below 5% critical.
  If pressure cannot be read it counts as warn.

Kind locks
  browser and codex also take their own machine-wide lock of capacity 1.
  A browser also needs free memory >= BGD_MIN_FREE_PCT_BROWSER percent
  (default 14) and free swap >= BGD_MIN_SWAP_FREE_MB_BROWSER MB
  (default 512). The swap floor applies only where swap has a fixed size
  (Linux): macOS adds swap files as it needs them, so its free swap is only
  the unused room in the files made so far and says nothing about how much
  memory is left. It is also skipped when no swap is allocated.

Jobs publish tickets in heavy/queue/ before attempting admission, ordered by
priority then creation time (FIFO among equals). Unavailable slots or locks
are checked every second for up to --wait seconds (default 1800, or
BGD_HEAVY_WAIT), then exit 75. Mode refusals remain immediate. A ticket
blocked only by its own browser floor or mode reserves nothing; one blocked
by a kind lock reserves only that lock, so unrelated work can pass it. A slot
waiter blocks later slot jobs even when multiple slots have just become free;
they wait until the earlier ticket has acquired its slot.

--priority high or HEAVY_PRIORITY=high moves ahead of normal tickets; only the
coordinator grants high priority. Nested runs never take tickets, including
when retrying a missing kind lock. status shows ordered tickets and flags legacy waiters without
tickets. Old/new pairs retain live locks across timezones, but two old copies
with different timezones can break each other's locks. Update old worktrees;
old admission/release can also disrupt FIFO order.
Memory samples are reused only within one admission poll. Process identities
use native birth seconds/microseconds on macOS and boot ID/start ticks on Linux,
independent of timezone and wall-clock changes, with no ps subprocess per poll.
Legacy records without this identity are retained while their PID is alive;
new lock records omit legacy local timestamps so old guards also retain them.

Each slot and kind lock is a directory under RUN_DIR/heavy/ made with mkdir,
holding owner.json: the guard's pid, the command's process group and their
immutable birth identities. A lock whose owner is gone, or whose strong
identity proves PID reuse, is stale and the next run clears it.

The command runs in its own session. SIGINT, SIGTERM and SIGHUP are forwarded
to its process group, locks are released when it ends, and this script exits
with the command's exit code. The child gets these defaults when unset or
empty: NODE_OPTIONS=--max-old-space-size=1536, GOMEMLIMIT=768MiB,
GOFLAGS=-p=2, GOMAXPROCS=4. A NODE_OPTIONS or GOFLAGS that is set but lacks a
heap or -p flag gets ours appended; a value that has one is kept. The child
also gets BGD_HEAVY_KIND=<kind>, BGD_HEAVY_HELD=1 when a slot is held,
and BGD_HEAVY_LOCKS=<held kind locks>.

Nested runs: when BGD_HEAVY_HELD=1 is already set, an outer heavy.py holds
a slot, so the inner run skips the mode gate and takes no slot (this keeps
"heavy.py run -- make verify" from deadlocking). It still takes a browser or
codex lock that no ancestor holds, and a new browser still passes its memory
and swap floors. fuzz and bench run under nice 10.

Every run appends {ts, kind, cmd, rc, secs, maxrss_kb} to
RUN_DIR/logs/heavy.jsonl. stop-all sends SIGTERM to the process groups this
script started (recorded in RUN_DIR/heavy/running/) and to guards still
waiting for a slot, then SIGKILL to groups that outlive --grace seconds.

RUN_DIR is BGD_RUN_DIR, or ~/.local/state/board-game-dev. With CI=true and no run
dir, the guard runs in continuous mode with the Linux readers and keeps its
state in RUNNER_TEMP (or the system temp dir). BGD_MAX_SLOTS caps the
slot count.

Detached runs (HEAVY_NOTIFY=<Paseo agent UUID> or --notify UUID; the value
"auto" reads PASEO_AGENT_ID): instead of blocking, run starts a copy of
itself in a new session with its output in RUN_DIR/logs/heavy-notify/, waits
until that copy has published its queue ticket (or, for light, started the
command), prints the ticket and the log path, and exits 0. The copy waits in
the queue as usual, runs the command, and then sends the agent one message
with `paseo send UUID TEXT --no-wait --json` (PASEO_BIN, default paseo, run
from RUN_DIR so a worktree removed meanwhile cannot break it): the
kind, the command, the outcome and exit code, the durations, the log path and
the last lines of the log. A failed send is retried 3 times with backoff and
then written to RUN_DIR/alerts/quota-<epoch>-heavy-notify-failed.md. While it
waits or runs, the copy sends keep-warm pings asking for a one-word reply,
every 25 minutes to a Codex agent and every 50 minutes to any other (the
provider comes from `paseo inspect UUID --json`), during the first 3.5 hours
only (HEAVY_WARM_CODEX, HEAVY_WARM_CLAUDE and HEAVY_WARM_MAX override the
seconds). A ping skips an agent whose Status is running, and the outcome waits
up to 5 minutes for it to go idle. A closed agent never reads its messages, so
pings skip it, and its outcome goes to its ParentAgentId instead (the agent that
launched it), prefixed with a line naming the closed agent; with no usable parent
the outcome is sent to the closed agent as before. A mode refusal is still reported at once without detaching. Nested
runs ignore HEAVY_NOTIFY and run inline, and the command never sees it. Under
make (MAKELEVEL set) HEAVY_NOTIFY is refused, because each step would detach
on its own; wrap the whole target instead:
HEAVY_NOTIFY=auto heavy.py run --kind light -- make verify-quick.

Exit codes: the command's own code; 75 when refused (EX_TEMPFAIL); 2 for
usage errors; 126 or 127 when the command cannot be started; 128+N when the
command (or this script, before the command started) died from signal N.
Pre-start cancellation exits without a final terminal diagnostic, so a blocked
stderr consumer cannot prevent cleanup or exit. Slot-cap and browser-floor
settings warn once at guard creation, before admission holds shared resources.
"""

from __future__ import annotations

from pathlib import Path

import argparse
import collections
import contextlib
import ctypes
import datetime as _dt
import fcntl
import json
import os
import random
import re
import resource
import select
import shlex
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from dataclasses import dataclass
from typing import Callable, Dict, Iterable, List, Mapping, Optional, Sequence, Set, Tuple

EX_TEMPFAIL = 75
EX_USAGE = 2

# Copy tools/project.json alongside this file. BGD_PROJECT_CONFIG can select
# another config; all processes sharing a browser must share the run directory.
CONFIG_PATH = Path(os.environ.get("BGD_PROJECT_CONFIG", Path(__file__).with_name("project.json")))
CONFIG = json.loads(CONFIG_PATH.read_text())
KINDS = tuple(CONFIG["kinds"])
KIND_LOCKS = tuple(CONFIG["kind_locks"])
NICE_KINDS = tuple(CONFIG["nice_kinds"])
if "light" not in KINDS or not set(KIND_LOCKS + NICE_KINDS) <= set(KINDS):
    raise ValueError("project.json: kinds must include light and all lock/nice kinds")
MODES = ("continuous", "nightshift", "paused")

DEFAULT_WINDOW = "00:00-10:00"
DEFAULT_WAIT = 1800.0
DEFAULT_GRACE = 10.0
DEFAULT_MIN_FREE_PCT_BROWSER = 14.0
DEFAULT_MIN_SWAP_FREE_MB_BROWSER = 512.0
DEFAULT_CHILD_ENV = (
    ("NODE_OPTIONS", "--max-old-space-size=1536"),
    ("GOMEMLIMIT", "768MiB"),
    ("GOFLAGS", "-p=2"),
    ("GOMAXPROCS", "4"),
)

LEVEL_NORMAL = 1
LEVEL_WARN = 2
LEVEL_CRITICAL = 4
LINUX_WARN_PCT = 15.0
LINUX_CRITICAL_PCT = 5.0

# A lock dir may exist without its owner file for this long (the owner is
# between mkdir and writing the file); after that it counts as stale.
FRESH_LOCK_GRACE = 30.0
BREAK_GRACE = 30.0
POLL_INTERVAL = 1.0
PROTOCOL_VERSION = 3
PRIORITIES = ("normal", "high")
OWNER_FILE = "owner.json"
SLOT_RE = re.compile(r"^slot-(\d+)$")
FORWARDED_SIGNALS = (signal.SIGINT, signal.SIGTERM, signal.SIGHUP)

# Detached runs that notify a Paseo agent (see the module docstring).
NOTIFY_ENV = ("HEAVY_NOTIFY", "BGD_HEAVY_NOTIFY_AGENT", "BGD_HEAVY_NOTIFY_FD",
              "BGD_HEAVY_NOTIFY_ACK_FD", "BGD_HEAVY_NOTIFY_LOG")
NOTIFY_OFF = ("", "0", "off", "no", "false")
AGENT_RE = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")
ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]")
HANDSHAKE_TIMEOUT = 60.0
ACK_TIMEOUT = 10.0
PASEO_TIMEOUT = 60.0
NOTIFY_BACKOFF = (10.0, 30.0, 90.0)
NOTIFY_TAIL_LINES = 12
NOTIFY_LINE_MAX = 200
# Keep-warm pings. Claude's prompt cache lasts about an hour and OpenAI keeps a
# GPT-6.1 prefix for 30 minutes after its last use. A ping rereads the context
# at the cached price, which pays for itself only early in a wait.
WARM_CLAUDE = 3000.0
WARM_CODEX = 1500.0
WARM_MAX = 12600.0
PING_POLL = 5.0
PING_RETRY = 300.0
# An agent mid-turn would have its current tool call cut off by a message, so
# a ping skips a busy agent and the outcome waits a while for it to go idle.
BUSY_POLL = 15.0
BUSY_MAX = 300.0


# ----------------------------------------------------------------------------
# Small helpers


def fmt_secs(secs: float) -> str:
    secs = int(round(max(secs, 0)))
    if secs < 60:
        return f"{secs}s"
    minutes, secs = divmod(secs, 60)
    if minutes < 60:
        return f"{minutes}m{secs:02d}s"
    hours, minutes = divmod(minutes, 60)
    return f"{hours}h{minutes:02d}m"


def iso(when: _dt.datetime) -> str:
    try:
        return when.astimezone().isoformat(timespec="seconds")
    except (ValueError, OSError):
        return when.isoformat(timespec="seconds")


def display_cmd(cmd: Sequence[str], limit: int = 0) -> str:
    text = shlex.join(list(cmd))
    if limit and len(text) > limit:
        return text[: limit - 3] + "..."
    return text


def normalize_maxrss(value: int, platform: str) -> int:
    """ru_maxrss is bytes on macOS and kilobytes on Linux; return kilobytes."""
    if platform == "darwin":
        return int(value) // 1024
    return int(value)


def read_json(path: str) -> Optional[dict]:
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def write_json_atomic(path: str, data: Mapping) -> None:
    directory = os.path.dirname(path)
    os.makedirs(directory, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".tmp-", dir=directory)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, sort_keys=True)
            fh.write("\n")
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def remove_file(path: Optional[str]) -> None:
    if not path:
        return
    try:
        os.unlink(path)
    except OSError:
        pass


def default_pid_alive(pid: object) -> bool:
    if not isinstance(pid, int) or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except (OSError, OverflowError):
        return False
    return True


def default_group_alive(pgid: object) -> bool:
    if not isinstance(pgid, int) or pgid <= 1:
        return False
    try:
        os.killpg(pgid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except (OSError, OverflowError):
        return False
    return True


PS = "/bin/ps" if os.path.exists("/bin/ps") else "ps"


def _ps_field(pid: int, field: str) -> Optional[str]:
    env = dict(os.environ, LC_ALL="C")
    try:
        res = subprocess.run([PS, "-o", f"{field}=", "-p", str(pid)], env=env,
                             capture_output=True, text=True, timeout=5, check=False)
    except (OSError, subprocess.SubprocessError):
        return None
    if res.returncode != 0:
        return None
    return " ".join(res.stdout.split()) or None


def default_proc_command(pid: int) -> Optional[str]:
    """The command line of a live process, or None."""
    return _ps_field(pid, "command")


def default_proc_start(pid: int) -> Optional[str]:
    """Legacy ps-compatible local time, kept only in running/ records.

    This display timestamp can change with TZ or Linux realtime adjustments;
    it is never used to break a lock. Unknown platforms use the ps fallback.
    """
    try:
        if sys.platform == "darwin":
            # proc_bsdinfo: 120 bytes precede the two uint64 birth fields.
            buf = ctypes.create_string_buffer(136)
            size = _LIBPROC.proc_pidinfo(pid, 3, 0, buf, len(buf))
            if size != len(buf):
                return None
            born = ctypes.c_uint64.from_buffer(buf, 120).value
        elif sys.platform.startswith("linux"):
            with open(f"/proc/{pid}/stat", encoding="utf-8") as fh:
                ticks = int(fh.read().rsplit(")", 1)[1].split()[19])
            with open("/proc/stat", encoding="utf-8") as fh:
                boot = next(int(line.split()[1]) for line in fh if line.startswith("btime "))
            born = boot + ticks / os.sysconf("SC_CLK_TCK")
        else:
            return _ps_field(pid, "lstart")
        return " ".join(time.strftime("%a %b %e %H:%M:%S %Y", time.localtime(born)).split())
    except (OSError, ValueError, IndexError, StopIteration, AttributeError):
        return None


def default_proc_identity(pid: int) -> Optional[str]:
    """Immutable birth identity; never use wall-clock boot time on Linux."""
    try:
        if sys.platform == "darwin":
            buf = ctypes.create_string_buffer(136)
            size = _LIBPROC.proc_pidinfo(pid, 3, 0, buf, len(buf))
            if size != len(buf):
                return None
            seconds = ctypes.c_uint64.from_buffer(buf, 120).value
            micros = ctypes.c_uint64.from_buffer(buf, 128).value
            return f"darwin:{seconds}:{micros}"
        if sys.platform.startswith("linux"):
            with open(f"/proc/{pid}/stat", encoding="utf-8") as fh:
                ticks = int(fh.read().rsplit(")", 1)[1].split()[19])
            with open("/proc/sys/kernel/random/boot_id", encoding="utf-8") as fh:
                boot_id = fh.read().strip()
            return f"linux:{boot_id}:{ticks}" if boot_id else None
    except (OSError, ValueError, IndexError, AttributeError):
        pass
    return None


_LIBPROC = ctypes.CDLL("/usr/lib/libproc.dylib") if sys.platform == "darwin" else None
if _LIBPROC is not None:
    _LIBPROC.proc_pidinfo.argtypes = (ctypes.c_int, ctypes.c_int, ctypes.c_uint64,
                                    ctypes.c_void_p, ctypes.c_int)
    _LIBPROC.proc_pidinfo.restype = ctypes.c_int


class Clock:
    """Wall clock, monotonic clock and sleep, injectable for tests."""

    def now(self) -> _dt.datetime:
        return _dt.datetime.now()

    def monotonic(self) -> float:
        return time.monotonic()

    def sleep(self, secs: float) -> None:
        time.sleep(secs)


# ----------------------------------------------------------------------------
# Window and mode

_WINDOW_RE = re.compile(r"^\s*(\d{1,2}):(\d{2})\s*-\s*(\d{1,2}):(\d{2})\s*$")


@dataclass(frozen=True)
class Window:
    """A daily local-time window [start, end) in minutes after midnight.

    When start > end the window wraps past midnight (22:00-06:00).
    The end may be 24:00, so 00:00-24:00 is the whole day.
    """

    start: int
    end: int

    @classmethod
    def parse(cls, text: str) -> "Window":
        match = _WINDOW_RE.match(text or "")
        if not match:
            raise ValueError(f"window must look like HH:MM-HH:MM, got {text!r}")
        sh, sm, eh, em = (int(g) for g in match.groups())
        if sh > 23 or sm > 59 or em > 59 or eh > 24 or (eh == 24 and em != 0):
            raise ValueError(f"window has an invalid time: {text!r}")
        start, end = sh * 60 + sm, eh * 60 + em
        if start == end:
            raise ValueError(f"window is empty: {text!r}")
        return cls(start, end)

    def contains(self, minute: int) -> bool:
        if self.start < self.end:
            return self.start <= minute < self.end
        return minute >= self.start or minute < self.end

    def contains_time(self, when: _dt.datetime) -> bool:
        return self.contains(when.hour * 60 + when.minute)

    def __str__(self) -> str:
        return (f"{self.start // 60:02d}:{self.start % 60:02d}-"
                f"{self.end // 60:02d}:{self.end % 60:02d}")


@dataclass
class ModeState:
    mode: str
    window: Window
    error: Optional[str] = None
    source: str = "file"  # "file", "default" (no file) or "ci"

    def in_window(self, now: _dt.datetime) -> bool:
        return self.mode == "nightshift" and self.error is None and self.window.contains_time(now)


def load_mode(path: str) -> ModeState:
    window = Window.parse(DEFAULT_WINDOW)
    try:
        with open(path, encoding="utf-8") as fh:
            text = fh.read()
    except FileNotFoundError:
        return ModeState("continuous", window, source="default")
    except OSError as exc:
        return ModeState("invalid", window, error=f"cannot read mode.json: {exc.strerror or exc}")
    try:
        data = json.loads(text)
    except ValueError as exc:
        return ModeState("invalid", window, error=f"mode.json is not JSON: {exc}")
    if not isinstance(data, dict) or data.get("mode") not in MODES:
        mode = data.get("mode") if isinstance(data, dict) else None
        return ModeState("invalid", window, error=f"mode.json has unknown mode {mode!r}")
    raw_window = data.get("window") or DEFAULT_WINDOW
    try:
        window = Window.parse(str(raw_window))
    except ValueError as exc:
        return ModeState("invalid", window, error=f"mode.json: {exc}")
    return ModeState(data["mode"], window)


def gate_mode(kind: str, state: ModeState, now: _dt.datetime) -> Optional[str]:
    """Why the mode forbids this kind right now, or None when it is allowed."""
    if kind == "light":
        return None
    if state.error:
        return f"{state.error}; fix it with: heavy.py mode continuous|nightshift|paused"
    if state.mode == "paused":
        return "mode is paused; only --kind light may run"
    if state.mode == "nightshift" and not state.in_window(now):
        return (f"mode is nightshift and {now:%H:%M} is outside the window {state.window}; "
                "only --kind light may run")
    return None


# ----------------------------------------------------------------------------
# Memory readers


@dataclass
class Memory:
    level: Optional[int] = None  # 1 normal, 2 warn, 4 critical, None unknown
    free_pct: Optional[float] = None
    swap_total_mb: Optional[float] = None
    swap_free_mb: Optional[float] = None
    # True where the OS grows swap on demand (macOS), so free swap is no limit.
    swap_dynamic: bool = False
    source: str = "unknown"


def level_name(level: Optional[int]) -> str:
    if level is None:
        return "unknown"
    return {LEVEL_NORMAL: "normal", LEVEL_WARN: "warn", LEVEL_CRITICAL: "critical"}.get(level, f"level {level}")


_SWAP_RE = re.compile(r"(total|used|free)\s*=\s*([\d.]+)\s*([KMGT]?)", re.IGNORECASE)
_UNIT_MB = {"": 1.0 / (1024 * 1024), "K": 1.0 / 1024, "M": 1.0, "G": 1024.0, "T": 1024.0 * 1024}


def parse_swapusage(text: str) -> Tuple[Optional[float], Optional[float]]:
    """Parse macOS `sysctl -n vm.swapusage` into (total MB, free MB)."""
    values: Dict[str, float] = {}
    for name, number, unit in _SWAP_RE.findall(text or ""):
        values[name.lower()] = float(number) * _UNIT_MB[unit.upper()]
    return values.get("total"), values.get("free")


def default_sysctl(key: str) -> Optional[str]:
    exe = "/usr/sbin/sysctl" if os.path.exists("/usr/sbin/sysctl") else "sysctl"
    try:
        res = subprocess.run([exe, "-n", key], capture_output=True, text=True, timeout=5, check=False)
    except (OSError, subprocess.SubprocessError):
        return None
    if res.returncode != 0:
        return None
    return res.stdout.strip()


def _to_int(text: Optional[str]) -> Optional[int]:
    try:
        return int(str(text).strip())
    except (TypeError, ValueError):
        return None


def read_darwin(sysctl: Callable[[str], Optional[str]] = default_sysctl) -> Memory:
    level = _to_int(sysctl("kern.memorystatus_vm_pressure_level"))
    free = _to_int(sysctl("kern.memorystatus_level"))
    swap_total, swap_free = parse_swapusage(sysctl("vm.swapusage") or "")
    return Memory(level=level, free_pct=None if free is None else float(free),
                  swap_total_mb=swap_total, swap_free_mb=swap_free, swap_dynamic=True,
                  source="darwin sysctl")


def level_from_free_pct(free_pct: Optional[float]) -> Optional[int]:
    if free_pct is None:
        return None
    if free_pct < LINUX_CRITICAL_PCT:
        return LEVEL_CRITICAL
    if free_pct < LINUX_WARN_PCT:
        return LEVEL_WARN
    return LEVEL_NORMAL


def parse_meminfo(text: str) -> Memory:
    kb: Dict[str, int] = {}
    for line in (text or "").splitlines():
        name, _, rest = line.partition(":")
        parts = rest.split()
        if parts and parts[0].isdigit():
            kb[name.strip()] = int(parts[0])
    total = kb.get("MemTotal")
    avail = kb.get("MemAvailable")
    free_pct = (avail * 100.0 / total) if total and avail is not None else None
    swap_total = kb["SwapTotal"] / 1024.0 if "SwapTotal" in kb else None
    swap_free = kb["SwapFree"] / 1024.0 if "SwapFree" in kb else None
    return Memory(level=level_from_free_pct(free_pct), free_pct=free_pct,
                  swap_total_mb=swap_total, swap_free_mb=swap_free, source="linux /proc/meminfo")


def read_linux(path: str = "/proc/meminfo") -> Memory:
    try:
        with open(path, encoding="utf-8") as fh:
            return parse_meminfo(fh.read())
    except OSError:
        return Memory(source=f"unreadable {path}")


def default_reader(platform: str) -> Callable[[], Memory]:
    if platform == "darwin":
        return read_darwin
    if platform.startswith("linux"):
        return read_linux
    return lambda: Memory(source=f"no reader for {platform}")


def slot_capacity(level: Optional[int], nightshift_window: bool, max_slots: Optional[int] = None) -> int:
    """Heavy slots for a pressure level: critical 0, warn 1, normal 2 (3 in the nightshift window)."""
    if level is None:
        cap = 1
    elif level >= LEVEL_CRITICAL:
        cap = 0
    elif level >= LEVEL_WARN:
        cap = 1
    else:
        cap = 3 if nightshift_window else 2
    if max_slots is not None:
        cap = min(cap, max_slots)
    return max(cap, 0)


def browser_block_reason(mem: Memory, min_free_pct: float, min_swap_mb: float) -> Optional[str]:
    """Why a browser may not launch now, or None. Unknown readings do not block."""
    if mem.free_pct is not None and mem.free_pct < min_free_pct:
        return f"free memory {mem.free_pct:.0f}% is below the browser floor of {min_free_pct:g}%"
    if (not mem.swap_dynamic and mem.swap_total_mb and mem.swap_free_mb is not None
            and mem.swap_free_mb < min_swap_mb):
        return f"free swap {mem.swap_free_mb:.0f} MB is below the browser floor of {min_swap_mb:g} MB"
    return None


# ----------------------------------------------------------------------------
# Lock dirs


class Locks:
    """Machine-wide locks: one directory each, created atomically with mkdir.

    The directory holds owner.json with the guard's pid and, once the command
    has started, its process group, each with an immutable native birth
    identity when readable. A lock is stale when neither identity is alive.
    Unknown identities and legacy local timestamps are conservative: retain
    a live PID because timezone or realtime changes cannot prove reuse.
    """

    def __init__(self, root: str, pid_alive: Callable[[object], bool],
                 group_alive: Callable[[object], bool],
                 proc_start: Optional[Callable[[int], Optional[str]]] = None,
                 proc_identity: Optional[Callable[[int], Optional[str]]] = None):
        self.root = root
        self.pid_alive = pid_alive
        self.group_alive = group_alive
        self.proc_start = proc_start
        self.proc_identity = proc_identity

    def path(self, name: str) -> str:
        return os.path.join(self.root, name)

    def owner(self, name: str) -> Optional[dict]:
        return read_json(os.path.join(self.path(name), OWNER_FILE))

    def _not_reused(self, pid: int, recorded: object) -> bool:
        if not recorded or self.proc_start is None:
            return True
        current = self.proc_start(pid)
        return current is None or current == recorded

    def identity_matches(self, pid: int, recorded: object) -> Optional[bool]:
        """None means identity is unavailable, never evidence of PID reuse."""
        if not recorded or self.proc_identity is None:
            return None
        current = self.proc_identity(pid)
        return None if current is None else current == recorded

    def process_alive(self, pid: object, identity: object = None, group: bool = False) -> bool:
        alive = self.group_alive(pid) if group else self.pid_alive(pid)
        # Legacy lstart is caller-local and Linux btime may change. It cannot
        # safely prove reuse, so retain legacy holders until their PID is gone.
        return alive and self.identity_matches(pid, identity) is not False

    def info_alive(self, info: Mapping) -> bool:
        if self.process_alive(info.get("pid"), info.get("identity")):
            return True
        pgid = info.get("pgid")
        return isinstance(pgid, int) and self.process_alive(pgid, info.get("pgid_identity"), group=True)

    def state(self, name: str) -> str:
        """"free", "live" or "stale"."""
        path = self.path(name)
        if not os.path.isdir(path):
            return "free"
        info = self.owner(name)
        if info is None:
            try:
                age = time.time() - os.stat(path).st_mtime
            except OSError:
                return "free"
            return "live" if age < FRESH_LOCK_GRACE else "stale"
        return "live" if self.info_alive(info) else "stale"

    def slot_names(self) -> List[str]:
        try:
            names = [n for n in os.listdir(self.root) if SLOT_RE.match(n)]
        except OSError:
            return []
        return sorted(names, key=lambda n: int(SLOT_RE.match(n).group(1)))

    def try_acquire(self, name: str, info: Mapping) -> bool:
        os.makedirs(self.root, exist_ok=True)
        path = self.path(name)
        for attempt in (0, 1):
            try:
                os.mkdir(path)
            except FileExistsError:
                if attempt == 0 and self.state(name) == "stale" and self.break_stale(name):
                    continue
                return False
            try:
                write_json_atomic(os.path.join(path, OWNER_FILE), info)
            except BaseException:
                shutil.rmtree(path, ignore_errors=True)
                raise
            return True
        return False

    def update(self, name: str, token: str, **fields: object) -> None:
        info = self.owner(name)
        if not info or info.get("token") != token:
            return
        info.update(fields)
        write_json_atomic(os.path.join(self.path(name), OWNER_FILE), info)

    def release(self, name: str, token: str) -> None:
        info = self.owner(name)
        if info is not None and info.get("token") != token:
            return  # not ours any more; never remove another holder's lock
        shutil.rmtree(self.path(name), ignore_errors=True)

    def break_stale(self, name: str) -> bool:
        """Remove a stale lock. A sibling NAME.break dir serializes breakers."""
        path = self.path(name)
        breaker = path + ".break"
        try:
            os.mkdir(breaker)
        except FileExistsError:
            try:
                if time.time() - os.stat(breaker).st_mtime > BREAK_GRACE:
                    os.rmdir(breaker)
            except OSError:
                pass
            return False
        except OSError:
            return False
        try:
            if self.state(name) != "stale":
                return False
            shutil.rmtree(path, ignore_errors=True)
            return not os.path.exists(path)
        finally:
            try:
                os.rmdir(breaker)
            except OSError:
                pass

    def sweep(self) -> None:
        for name in self.slot_names() + list(KIND_LOCKS):
            if self.state(name) == "stale":
                self.break_stale(name)


# ----------------------------------------------------------------------------
# The guard


class Refused(Exception):
    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


class _Interrupted(BaseException):
    """Raised by the signal handler. A BaseException, like KeyboardInterrupt,
    so that `except Exception` (around the memory reader) cannot swallow it."""

    def __init__(self, signum: int):
        super().__init__(signum)
        self.signum = signum


class Guard:
    def __init__(self, env: Optional[Mapping[str, str]] = None, platform: Optional[str] = None,
                 reader: Optional[Callable[[], Memory]] = None, clock: Optional[Clock] = None,
                 pid_alive: Optional[Callable[[object], bool]] = None,
                 group_alive: Optional[Callable[[object], bool]] = None,
                 proc_command: Optional[Callable[[int], Optional[str]]] = None,
                 proc_start: Optional[Callable[[int], Optional[str]]] = None,
                 proc_identity: Optional[Callable[[int], Optional[str]]] = None,
                 rng: Optional[random.Random] = None, stdout=None, stderr=None):
        self.env: Dict[str, str] = dict(os.environ if env is None else env)
        self.platform = platform or sys.platform
        self.clock = clock or Clock()
        self.pid_alive = pid_alive or default_pid_alive
        self.group_alive = group_alive or default_group_alive
        self.proc_command = proc_command or default_proc_command
        self.proc_start = proc_start or default_proc_start
        self.proc_identity = proc_identity or default_proc_identity
        self.rng = rng or random.Random()
        self.out = stdout or sys.stdout
        self.err = stderr or sys.stderr

        self.home = self.env.get("HOME") or os.path.expanduser("~")
        self.configured_run_dir = self.env.get(CONFIG["run_dir_env"]) or os.path.expandvars(
            str(CONFIG["run_dir"]).replace("~", self.home, 1))
        ci = self.env.get("CI", "").lower() in ("true", "1")
        self.ci_mode = ci and not os.path.isdir(self.configured_run_dir)
        if self.ci_mode:
            base = self.env.get("RUNNER_TEMP") or tempfile.gettempdir()
            self.run_dir = os.path.join(base, CONFIG["name"] + "-heavy-ci")
            self.reader_platform = "linux"
        else:
            self.run_dir = self.configured_run_dir
            self.reader_platform = self.platform
        self.reader = reader or default_reader(self.reader_platform)
        self.heavy_dir = os.path.join(self.run_dir, "heavy")
        self.log_path = os.path.join(self.run_dir, "logs", "heavy.jsonl")
        self.mode_path = os.path.join(self.configured_run_dir, "mode.json")
        self.locks = Locks(self.heavy_dir, self.pid_alive, self.group_alive, self.proc_start, self.proc_identity)

        self._admission_depth = 0
        self._acquiring = False
        self._memory_sample: Optional[Tuple[float, Memory]] = None
        self._child: Optional[subprocess.Popen] = None
        self._spawning = False
        self._pending: Optional[int] = None
        self._done = False
        self._old_handlers: Dict[int, object] = {}
        # Hooks and facts for a detached run's notifier.
        self.on_queued: Optional[Callable[[str, int, int], None]] = None
        self.last_refusal: Optional[str] = None
        self.started_at: Optional[float] = None
        self.token: Optional[str] = None
        self.detached: Optional[subprocess.Popen] = None
        # Resolve settings and warn once before any admission critical section.
        # The getters used by eligibility/status must never write to a pipe.
        self._max_slots = self._read_max_slots()
        self._browser_floors = (
            self._env_float("BGD_MIN_FREE_PCT_BROWSER", DEFAULT_MIN_FREE_PCT_BROWSER),
            self._env_float("BGD_MIN_SWAP_FREE_MB_BROWSER", DEFAULT_MIN_SWAP_FREE_MB_BROWSER))

    # -- configuration -------------------------------------------------------

    def _say(self, msg: str) -> None:
        print(msg, file=self.out)

    def _warn(self, msg: str) -> None:
        try:
            fd = self.err.fileno()
        except (AttributeError, OSError, ValueError):
            print(msg, file=self.err)
            try:
                self.err.flush()
            except (OSError, ValueError):
                pass
            return
        # A signal can interrupt a full pipe. TextIO buffering would retain
        # the interrupted bytes and retry them at interpreter shutdown, after
        # our handlers have been restored. Write directly so nothing is queued.
        data = (msg + "\n").encode(getattr(self.err, "encoding", None) or "utf-8",
                                    getattr(self.err, "errors", None) or "backslashreplace")
        # A lost diagnostic (closed pipe, full disk, non-blocking full pipe)
        # must never stop a run; _Interrupted is a BaseException and still
        # propagates.
        try:
            while data:
                data = data[os.write(fd, data):]
        except OSError:
            pass

    def _env_float(self, name: str, default: float) -> float:
        raw = self.env.get(name)
        if raw is None or raw == "":
            return default
        try:
            return float(raw)
        except ValueError:
            self._warn(f"heavy: ignoring {name}={raw!r}: not a number")
            return default

    def _read_max_slots(self) -> Optional[int]:
        raw = self.env.get("BGD_MAX_SLOTS")
        if raw is None or raw == "":
            return None
        try:
            return max(int(raw), 0)
        except ValueError:
            self._warn(f"heavy: ignoring BGD_MAX_SLOTS={raw!r}: not an integer")
            return None

    def max_slots(self) -> Optional[int]:
        return self._max_slots

    def browser_floors(self) -> Tuple[float, float]:
        return self._browser_floors

    def mode_state(self) -> ModeState:
        if self.ci_mode:
            return ModeState("continuous", Window.parse(DEFAULT_WINDOW), source="ci")
        return load_mode(self.mode_path)

    def read_memory(self) -> Memory:
        try:
            mem = self.reader()
        except Exception as exc:  # a broken reader must not break every job
            return Memory(source=f"reader failed: {exc}")
        return mem if isinstance(mem, Memory) else Memory(source="reader returned nothing")

    def capacity(self, mem: Memory, state: Optional[ModeState] = None,
                 now: Optional[_dt.datetime] = None) -> int:
        state = state or self.mode_state()
        now = now or self.clock.now()
        return slot_capacity(mem.level, state.in_window(now), self.max_slots())

    def tilde(self, path: str) -> str:
        home = self.home.rstrip("/")
        if home and (path == home or path.startswith(home + "/")):
            return "~" + path[len(home):]
        return path

    # -- describing holders ----------------------------------------------------

    def _describe(self, info: Optional[Mapping]) -> str:
        if not info:
            return "a starting job"
        age = time.time() - float(info.get("t0") or time.time())
        return f"pid {info.get('pid')} {info.get('kind')} {fmt_secs(age)}: {info.get('cmd', '')}"

    def _live_slots(self) -> List[str]:
        return [n for n in self.locks.slot_names() if self.locks.state(n) == "live"]

    # -- acquiring ---------------------------------------------------------------

    def _try_slot(self, cap: int, mem: Memory, info: Mapping) -> Tuple[Optional[str], Optional[str]]:
        if cap <= 0:
            return None, f"memory pressure is {level_name(mem.level)}, which allows no heavy slots"
        live = self._live_slots()
        busy = (f"all {cap} heavy slot(s) are busy at {level_name(mem.level)} pressure"
                f" ({'; '.join(self._describe(self.locks.owner(n)) for n in live)})")
        if len(live) >= cap:
            return None, busy
        for index in range(1, cap + 1):
            name = f"slot-{index}"
            if self.locks.try_acquire(name, info):
                try:
                    if len(self._live_slots()) > cap:  # lost a race while capacity shrank
                        self.locks.release(name, info["token"])
                        return None, busy
                    return name, None
                except BaseException:
                    self.locks.release(name, info["token"])
                    raise
        return None, busy

    @contextlib.contextmanager
    def _admission(self, deadline: Optional[float] = None):
        """Serialize publication, eligibility, acquisition, release and status.

        Keep this file permanently: unlinking a flock file lets two processes
        lock different inodes. Legacy guards still share the mkdir locks.
        """
        if self._admission_depth:
            yield
            return
        os.makedirs(self.heavy_dir, exist_ok=True)
        with open(os.path.join(self.heavy_dir, "admission.lock"), "a") as fh:
            while True:
                if self._acquiring and not self._done:
                    self._raise_pending()
                try:
                    fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    remaining = None if deadline is None else deadline - self.clock.monotonic()
                    if remaining is not None and remaining <= 0:
                        raise Refused("admission lock is busy; wait deadline reached")
                    self.clock.sleep(0.05 if remaining is None else min(0.05, remaining))
            try:
                self._admission_depth += 1
                yield
            finally:
                self._admission_depth -= 1
                fcntl.flock(fh, fcntl.LOCK_UN)

    def _poll_memory(self) -> Memory:
        now = self.clock.monotonic()
        if self._memory_sample is None or now - self._memory_sample[0] >= POLL_INTERVAL:
            self._memory_sample = (now, self.read_memory())
        return self._memory_sample[1]

    @staticmethod
    def _ticket_order(info: Mapping) -> tuple:
        return (0 if info.get("priority") == "high" else 1,
                info.get("created_ns", 0), info.get("token", ""))

    def _tickets(self) -> List[Tuple[str, dict]]:
        """Caller holds admission lock. Reuse lock liveness rules, including PID reuse."""
        tickets = []
        for path, rec in self._records("queue"):
            if self.locks.info_alive(rec):
                tickets.append((path, rec))
            else:
                remove_file(path)
        return sorted(tickets, key=lambda item: self._ticket_order(item[1]))

    def _resource(self, kind: str, nested: bool, inherited: Set[str],
                  mem: Memory, state: ModeState, floors: Optional[Sequence[float]] = None) -> str:
        """Resource a pending job reserves, or gate if it cannot use resources.

        Recompute rather than trusting another waiter's last blocked_on value:
        its memory floor, mode or kind lock may have changed since that poll.
        """
        if not nested and gate_mode(kind, state, self.clock.now()):
            return "gate"
        needs_kind = kind in KIND_LOCKS and kind not in inherited
        if needs_kind:
            if kind == "browser" and browser_block_reason(mem, *(floors or self.browser_floors())):
                return "gate"
            if self.locks.state(kind) == "live":
                return kind
        return "slots" if not nested else kind if needs_kind else "none"

    def _attempt(self, kind: str, nested: bool, inherited: Set[str],
                 info: Mapping, tickets: Sequence[Tuple[str, dict]] = ()) -> Tuple[List[str], Optional[str], bool]:
        """Try every gate once while holding admission lock."""
        state = self.mode_state()
        if not nested:
            reason = gate_mode(kind, state, self.clock.now())
            if reason:
                return [], reason, True
        if kind == "light":
            return [], None, False
        needs_kind_lock = kind in KIND_LOCKS and kind not in inherited
        if nested and not needs_kind_lock:
            return [], None, False
        self.locks.sweep()
        mem = self._poll_memory()
        if needs_kind_lock and kind == "browser":
            reason = browser_block_reason(mem, *self.browser_floors())
            if reason:
                self._blocked = "gate: " + reason
                return [], reason, False
        # A ticket blocked by its kind lock reserves that lock only. Otherwise
        # it reserves a slot, even if one has just freed and it has not polled.
        # Propagate kind reservations so a later browser cannot reserve slots
        # while it is itself queued behind an earlier browser.
        reserved: Set[str] = set()
        for _, earlier in tickets:
            if earlier.get("token") == info["token"]:
                break
            other_kind = earlier["kind"]
            resource = self._resource(other_kind, bool(earlier.get("nested")),
                                      set(earlier.get("inherited", [])), mem, state, earlier.get("browser_floors"))
            if other_kind in reserved and resource == "slots":
                resource = other_kind
            if resource not in ("gate", "none"):
                reserved.add(resource)
                if resource == "slots" and other_kind in KIND_LOCKS:
                    reserved.add(other_kind)
        conflict = None
        if needs_kind_lock and kind in reserved:
            conflict = kind
        elif not nested and "slots" in reserved:
            conflict = "slots"
        if conflict:
            self._blocked = conflict
            return [], f"earlier queued job is waiting for {conflict}", False
        held: List[str] = []
        try:
            # Observe the kind lock first, but do not take it until a slot is
            # available. A waiting job must not pulse a lock an ancestor needs.
            if needs_kind_lock and self.locks.state(kind) == "live":
                self._blocked = kind
                holder = self._describe(self.locks.owner(kind))
                return [], f"the {kind} lock is held by {holder}", False
            if not nested:
                slot, reason = self._try_slot(self.capacity(mem, state), mem, info)
                if slot is None:
                    self._blocked = "slots"
                    return [], reason, False
                held.append(slot)
            if needs_kind_lock:
                if not self.locks.try_acquire(kind, info):
                    self._blocked = kind
                    holder = self._describe(self.locks.owner(kind))
                    self._release(held, info["token"])
                    return [], f"the {kind} lock is held by {holder}", False
                held.append(kind)
            return held, None, False
        except BaseException:
            self._release_owned(info["token"])
            raise

    def _acquire(self, kind: str, wait: float, nested: bool, inherited: Set[str],
                 info: Mapping) -> List[str]:
        deadline = self.clock.monotonic() + max(wait, 0.0)
        last_reason = None
        if not nested:
            reason = gate_mode(kind, self.mode_state(), self.clock.now())
            if reason:
                raise Refused(reason)
        # Nested runs never publish tickets or join the queue, including when
        # they need a missing kind lock. Waiting behind a top-level ticket
        # could deadlock it on our ancestor's held slot.
        if nested and (kind not in KIND_LOCKS or kind in inherited):
            return []
        path = None if nested else os.path.join(self.heavy_dir, "queue", f"{info['token']}.json")
        ticket = dict(info, nested=nested, inherited=sorted(inherited), blocked_on="checking",
                      browser_floors=list(self.browser_floors()) if kind == "browser" else [])
        published = False
        try:
            while True:
                self._raise_pending()
                with self._admission(deadline):
                    # Reuse memory only within this admission poll. A final
                    # fractional wait must sample again before refusing.
                    self._memory_sample = None
                    tickets = self._tickets()
                    if path is not None and not published:
                        ticket["created_ns"] = max(time.time_ns(), max(
                            (rec.get("created_ns", 0) + 1 for _, rec in tickets), default=0))
                        write_json_atomic(path, ticket)
                        published = True
                        tickets = sorted(tickets + [(path, ticket)], key=lambda item: self._ticket_order(item[1]))
                        if self.on_queued is not None:
                            position = [p for p, _ in tickets].index(path) + 1
                            self.on_queued(info["token"], position, len(tickets))
                    self._blocked = "gate"
                    held, reason, final = self._attempt(kind, nested, inherited, info, tickets if not nested else ())
                    if reason is None:
                        remove_file(path)
                        return held
                    if path is not None:
                        if final:
                            remove_file(path)
                        else:
                            ticket["blocked_on"] = self._blocked
                            write_json_atomic(path, ticket)
                self._raise_pending()
                if final:
                    raise Refused(reason)
                remaining = deadline - self.clock.monotonic()
                if remaining <= 0:
                    if wait > 0:
                        reason = f"{reason}; gave up after waiting {fmt_secs(wait)}"
                    raise Refused(reason)
                # A failed poll holds no resources. Let signals interrupt a
                # blocked diagnostic pipe or sleep instead of deferring them.
                deferred = self._acquiring
                self._acquiring = False
                try:
                    # A signal deferred since the check above must not wait
                    # behind the diagnostic and the poll sleep.
                    self._raise_pending()
                    # Holder ages change every poll; report resource changes.
                    if self._blocked != last_reason:
                        self._warn(f"heavy: {kind} is waiting: {reason} (up to {fmt_secs(remaining)} more)")
                        last_reason = self._blocked
                    self.clock.sleep(min(remaining, POLL_INTERVAL))
                finally:
                    self._acquiring = deferred
        except BaseException:
            self._release_owned(info["token"])
            raise
        finally:
            remove_file(path)

    def _release(self, held: Iterable[str], token: str) -> None:
        # Serialize the full handover with eligibility checks, including a
        # waiter that has already classified the exiting holder's kind lock.
        names = list(held)
        if not names:
            return
        with self._admission():
            for name in [n for n in names if n in KIND_LOCKS] + [n for n in names if n not in KIND_LOCKS]:
                self.locks.release(name, token)

    def _release_owned(self, token: str) -> None:
        # Disk ownership survives asynchronous exceptions between a callee's
        # return and assignment to the caller's local held list.
        names = self.locks.slot_names() + list(KIND_LOCKS)
        owned = [name for name in names if (self.locks.owner(name) or {}).get("token") == token]
        if owned:
            with self._admission():
                self._release(owned, token)

    def _raise_pending(self) -> None:
        if self._pending is not None:
            self._done = True
            raise _Interrupted(self._pending)

    # -- signals -----------------------------------------------------------------

    def _on_signal(self, signum, frame) -> None:
        if self._done:
            return
        if self._child is not None:
            self._forward(signum)
            return
        if self._spawning or self._acquiring:
            if self._pending is None:
                self._pending = signum
            return
        self._done = True
        raise _Interrupted(self._pending if self._pending is not None else signum)

    def _forward(self, signum: int) -> None:
        child = self._child
        if child is None or child.pid <= 1:
            return
        try:
            os.killpg(child.pid, signum)
        except (ProcessLookupError, PermissionError):
            pass

    def _install_signals(self) -> None:
        self._old_handlers = {}
        for sig in FORWARDED_SIGNALS:
            try:
                self._old_handlers[sig] = signal.signal(sig, self._on_signal)
            except (ValueError, OSError):  # not the main thread
                pass

    def _restore_signals(self) -> None:
        for sig, handler in self._old_handlers.items():
            try:
                signal.signal(sig, handler)
            except (ValueError, OSError, TypeError):
                pass
        self._old_handlers = {}

    # -- records and log -----------------------------------------------------------

    def _record(self, sub: str, pid: int, data: Mapping) -> Optional[str]:
        path = os.path.join(self.heavy_dir, sub, f"{pid}.json")
        try:
            write_json_atomic(path, data)
        except OSError as exc:
            # Inside acquisition, signals are deferred; let one interrupt a
            # blocked diagnostic write rather than wait behind it.
            deferred = self._acquiring
            self._acquiring = False
            try:
                if deferred:
                    self._raise_pending()
                self._warn(f"heavy: cannot write {sub} record: {exc}")
            finally:
                self._acquiring = deferred
            return None
        return path

    def _records(self, sub: str) -> List[Tuple[str, dict]]:
        directory = os.path.join(self.heavy_dir, sub)
        try:
            names = sorted(n for n in os.listdir(directory) if n.endswith(".json"))
        except OSError:
            return []
        out = []
        for name in names:
            path = os.path.join(directory, name)
            data = read_json(path)
            if data is not None:
                out.append((path, data))
        return out

    def _log(self, kind: str, cmd: Sequence[str], rc: int, secs: float, maxrss_kb: int,
             when: Optional[_dt.datetime] = None, **extra: object) -> None:
        entry = {"ts": iso(when or self.clock.now()), "kind": kind, "cmd": display_cmd(cmd),
                 "rc": rc, "secs": round(secs, 2), "maxrss_kb": int(maxrss_kb)}
        entry.update({k: v for k, v in extra.items() if v not in (None, False, "")})
        line = (json.dumps(entry) + "\n").encode("utf-8")
        try:
            os.makedirs(os.path.dirname(self.log_path), exist_ok=True)
            fd = os.open(self.log_path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o644)
            try:
                os.write(fd, line)
            finally:
                os.close(fd)
        except OSError as exc:
            self._warn(f"heavy: cannot append to heavy.jsonl: {exc}")

    # -- run -------------------------------------------------------------------------

    def child_env(self, kind: str, slot_held: bool, locks: Set[str]) -> Dict[str, str]:
        env = dict(self.env)
        for key, value in DEFAULT_CHILD_ENV:
            if not env.get(key):
                env[key] = value
        # NODE_OPTIONS and GOFLAGS hold several flags. A value that is set but
        # has no heap or parallelism flag gets ours appended; one that already
        # has such a flag is kept as it is.
        node = env["NODE_OPTIONS"]
        if "--max-old-space-size" not in node and "--max_old_space_size" not in node:
            env["NODE_OPTIONS"] = f"{node} --max-old-space-size=1536"
        goflags = env["GOFLAGS"].split()
        if not any(flag in ("-p", "--p") or flag.startswith(("-p=", "--p=")) for flag in goflags):
            env["GOFLAGS"] = f"{env['GOFLAGS']} -p=2"
        env["BGD_HEAVY_KIND"] = kind
        if slot_held:
            env["BGD_HEAVY_HELD"] = "1"
        else:
            env.pop("BGD_HEAVY_HELD", None)
        if locks:
            env["BGD_HEAVY_LOCKS"] = ",".join(sorted(locks))
        else:
            env.pop("BGD_HEAVY_LOCKS", None)
        for key in NOTIFY_ENV:  # inner runs must block, not detach again
            env.pop(key, None)
        return env

    def run(self, kind: str, cmd: Sequence[str], wait: Optional[float] = None,
            priority: Optional[str] = None, notify: Optional[str] = None) -> int:
        if kind not in KINDS:
            self._warn(f"heavy: unknown kind {kind!r}; use one of {', '.join(KINDS)}")
            return EX_USAGE
        cmd = list(cmd)
        if not cmd:
            self._warn("heavy: run needs a command after --")
            return EX_USAGE
        if wait is None:
            wait = self._env_float("BGD_HEAVY_WAIT", DEFAULT_WAIT)
        priority = priority or self.env.get("HEAVY_PRIORITY") or "normal"
        if priority not in PRIORITIES:
            self._warn(f"heavy: invalid priority {priority!r}; use normal or high")
            return EX_USAGE
        self._memory_sample = None
        nested = self.env.get("BGD_HEAVY_HELD") == "1"
        inherited = {x for x in self.env.get("BGD_HEAVY_LOCKS", "").split(",") if x}
        self.last_refusal, self.started_at = None, None
        if not nested:
            try:
                target = self.notify_target(notify)
            except ValueError as exc:
                self._warn(f"heavy: {exc}")
                return EX_USAGE
            if target:
                if notify is None and self.env.get("MAKELEVEL"):
                    self._warn("heavy: HEAVY_NOTIFY under make would detach every step on its own; "
                               "wrap the whole target instead: HEAVY_NOTIFY=auto python3 tools/heavy.py "
                               "run --kind light -- make <target>")
                    return EX_USAGE
                reason = gate_mode(kind, self.mode_state(), self.clock.now())
                if reason:
                    self._warn(f"heavy: refused --kind {kind}: {reason}")
                    self._log(kind, cmd, EX_TEMPFAIL, 0.0, 0, refused=reason)
                    return EX_TEMPFAIL
                return self._detach(kind, cmd, wait, priority, target)
        info = {"pid": os.getpid(), "kind": kind, "cmd": display_cmd(cmd, 160),
                "since": iso(self.clock.now()), "t0": time.time(), "token": uuid.uuid4().hex,
                "cwd": os.getcwd(), "priority": priority, "protocol": PROTOCOL_VERSION}
        identity = self.proc_identity(os.getpid())
        if identity:
            info["identity"] = identity
        self.token = info["token"]
        # Do not publish lstart in locks/tickets/waiting: old copies compare
        # that caller-local timestamp and may break our live lock across TZ.
        held: List[str] = []
        self._child, self._spawning, self._pending, self._done = None, False, None, False
        # Signals defer until ownership has reached run(), including mkdir,
        # owner publication and every return/assignment boundary in admission.
        self._acquiring = True
        self._install_signals()
        try:
            if kind != "light":
                waiting = self._record("waiting", os.getpid(), {
                    "guard": os.getpid(), "kind": kind, "cmd": info["cmd"],
                    "since": info["since"], "t0": info["t0"], "protocol": PROTOCOL_VERSION,
                    "identity": info.get("identity"), "nested": nested})
                try:
                    try:
                        held = self._acquire(kind, wait, nested, inherited, info)
                    finally:
                        remove_file(waiting)
                except Refused as refusal:
                    # Acquisition and waiting-record cleanup are complete.
                    # Terminal output may block, so cancellation must now raise.
                    self.last_refusal = refusal.reason
                    self._acquiring = False
                    self._raise_pending()
                    self._warn(f"heavy: refused --kind {kind}: {refusal.reason}")
                    self._log(kind, cmd, EX_TEMPFAIL, 0.0, 0, refused=refusal.reason, nested=nested)
                    return EX_TEMPFAIL
            # End deferral before the final check: a signal arriving after
            # this check must raise immediately rather than become stranded.
            self._acquiring = False
            self._raise_pending()
            slot_held = nested or any(SLOT_RE.match(h) for h in held)
            locks = inherited | {h for h in held if h in KIND_LOCKS}
            env = self.child_env(kind, slot_held, locks)
            return self._spawn(kind, cmd, env, held, info, nested)
        except _Interrupted as exc:
            # The interrupted operation may be writing to a full stderr pipe.
            # Do not start another blocking terminal write during shutdown.
            return 128 + exc.signum
        finally:
            self._done = True
            try:
                self._release_owned(info["token"])
            finally:
                self._acquiring = False
                self._restore_signals()

    def _spawn(self, kind: str, cmd: List[str], env: Dict[str, str], held: List[str],
               info: Mapping, nested: bool) -> int:
        started = self.clock.now()
        t0 = self.clock.monotonic()
        preexec = _nice10 if kind in NICE_KINDS else None
        self._spawning = True
        try:
            child = subprocess.Popen(cmd, env=env, start_new_session=True, preexec_fn=preexec)
        except OSError as exc:
            self._spawning = False
            self._raise_pending()  # a signal deferred during Popen still cancels
            rc = 127 if isinstance(exc, FileNotFoundError) else 126
            self._warn(f"heavy: cannot start {cmd[0]!r}: {exc.strerror or exc}")
            self._log(kind, cmd, rc, 0.0, 0, when=started, nested=nested)
            return rc
        self._child = child
        self._spawning = False
        self.started_at = t0
        record_data = {
            "pid": child.pid, "pgid": child.pid, "guard": os.getpid(), "kind": kind,
            "cmd": info["cmd"], "argv0": cmd[0], "since": iso(started), "t0": time.time(),
            "guard_identity": info.get("identity"), "nested": nested}
        record = self._record("running", child.pid, record_data)
        identity = self.proc_identity(child.pid)
        lstart = self.proc_start(child.pid)  # legacy stop-all keeps its strict fallback
        record_data["identity"] = identity
        if lstart:
            record_data["lstart"] = lstart
        if record:
            record = self._record("running", child.pid, record_data)
        try:
            for name in held:
                self.locks.update(name, info["token"], pgid=child.pid, pgid_identity=identity)
            if self._pending is not None:
                self._forward(self._pending)
                self._pending = None
            rc = child.wait()
        finally:
            self._done = True
            remove_file(record)
        secs = self.clock.monotonic() - t0
        if rc < 0:
            rc = 128 - rc
        # sys.platform, not self.platform: ru_maxrss's unit is fixed by the real
        # kernel this process runs under. self.platform is injectable (tests pin
        # it to pick a fake memory reader) and must not leak into this conversion.
        maxrss = normalize_maxrss(resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss, sys.platform)
        self._log(kind, cmd, rc, secs, maxrss, when=started, nested=nested)
        return rc

    # -- detached runs that notify an agent ------------------------------------------

    def notify_target(self, flag: Optional[str]) -> Optional[str]:
        """The Paseo agent to notify, None for a blocking run; ValueError if unusable."""
        raw = flag if flag is not None else self.env.get("HEAVY_NOTIFY", "")
        source = "--notify" if flag is not None else "HEAVY_NOTIFY"
        if raw.strip().lower() in NOTIFY_OFF:
            return None
        value = self.env.get("PASEO_AGENT_ID", "") if raw == "auto" else raw
        if raw == "auto" and not value:
            raise ValueError(f"{source}=auto needs PASEO_AGENT_ID, which is not set")
        if not AGENT_RE.match(value):
            raise ValueError(f"{source} needs a Paseo agent UUID or auto, not {value!r}")
        return value.lower()

    def _detach(self, kind: str, cmd: List[str], wait: float, priority: str, agent: str) -> int:
        log_dir = os.path.join(self.run_dir, "logs", "heavy-notify")
        stamp = self.clock.now().strftime("%Y%m%d-%H%M%S")
        log_path = os.path.join(log_dir, f"{stamp}-{kind}-{uuid.uuid4().hex[:8]}.log")
        # Two pipes: the copy reports how it started; when that report is a
        # refusal or an early end, the caller acknowledges it on the second
        # pipe, and an unacknowledged report is messaged to the agent instead.
        read_fd, write_fd = os.pipe()
        ack_read, ack_write = os.pipe()
        env = {k: v for k, v in self.env.items() if k not in NOTIFY_ENV}
        env.update(BGD_HEAVY_NOTIFY_AGENT=agent, BGD_HEAVY_NOTIFY_FD=str(write_fd),
                   BGD_HEAVY_NOTIFY_ACK_FD=str(ack_read), BGD_HEAVY_NOTIFY_LOG=log_path)
        argv = [sys.executable, os.path.abspath(__file__), "run", "--kind", kind,
                "--wait", repr(float(wait)), "--priority", priority, "--"] + cmd
        try:
            try:
                try:
                    os.makedirs(log_dir, exist_ok=True)
                    with open(log_path, "ab") as log:
                        self.detached = subprocess.Popen(
                            argv, env=env, stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                            start_new_session=True, pass_fds=(write_fd, ack_read))
                finally:
                    os.close(write_fd)
                    os.close(ack_read)
                try:
                    line = _read_line(read_fd, HANDSHAKE_TIMEOUT)
                except OSError as exc:  # the copy is alive and will message the agent
                    self._warn(f"heavy: cannot read the detached guard's report: {exc}")
                    line = None
            except OSError as exc:
                self._warn(f"heavy: cannot detach: {exc}")
                return 126
            finally:
                os.close(read_fd)
            pid = self.detached.pid
            where = f"heavy: log {self.tilde(log_path)}"
            word, _, rest = (line or "").partition(" ")
            if word in ("refused", "ended"):
                if word == "refused":
                    self._warn(f"heavy: refused --kind {kind}: {rest}")
                    rc = EX_TEMPFAIL
                else:
                    self._warn(f"heavy: the detached {kind} job ended before it queued, exit {rest}; {where}")
                    rc = int(rest) if rest.isdigit() else 1
                with contextlib.suppress(OSError):
                    os.write(ack_write, b"k")
                return rc
        finally:
            os.close(ack_write)
        if line is not None and word not in ("queued", "started"):
            self._warn(f"heavy: the detached guard (pid {pid}) stopped before it queued; {where}")
            return 1
        if word == "queued":
            token, position, total = (rest.split() + ["?", "?", "?"])[:3]
            self._say(f"heavy: detached {kind} job as pid {pid}, ticket {token}, "
                      f"number {position} of {total} in the queue")
        elif word == "started":
            self._say(f"heavy: detached {kind} job as pid {pid}; it is running")
        else:
            self._say(f"heavy: detached {kind} job as pid {pid}; no ticket after "
                      f"{fmt_secs(HANDSHAKE_TIMEOUT)} (read the log)")
        self._say(where)
        self._say(f"heavy: end your turn; you will be messaged (agent {agent}) when the job ends")
        return 0

    def run_notified(self, kind: str, cmd: Sequence[str], wait: Optional[float],
                     priority: Optional[str]) -> int:
        """The detached copy: run the job, then message the agent once."""
        agent = self.env["BGD_HEAVY_NOTIFY_AGENT"]
        log_path = self.env.get("BGD_HEAVY_NOTIFY_LOG", "")
        fds: Dict[str, Optional[int]] = {}
        for name in ("FD", "ACK_FD"):
            try:
                fds[name] = int(self.env.get(f"BGD_HEAVY_NOTIFY_{name}", ""))
            except ValueError:
                fds[name] = None

        def tell(line: str, ack: bool = False) -> bool:
            """Report to the caller once. With ack, True only if it acknowledged."""
            fd, fds["FD"] = fds["FD"], None
            if fd is None:
                return False
            try:
                os.write(fd, (line.replace("\n", " ") + "\n").encode("utf-8"))
            except OSError:
                return False
            finally:
                with contextlib.suppress(OSError):
                    os.close(fd)
            ack_fd, fds["ACK_FD"] = fds["ACK_FD"], None
            if not ack:
                if ack_fd is not None:
                    with contextlib.suppress(OSError):
                        os.close(ack_fd)
                return True
            return ack_fd is not None and _read_byte(ack_fd, ACK_TIMEOUT) == b"k"

        notifier = Notifier(self, agent, kind, list(cmd), log_path)
        self.on_queued = lambda token, position, total: tell(f"queued {token} {position} {total}")
        if kind == "light":
            tell("started")
        stop = threading.Event()
        pinger = threading.Thread(target=notifier.ping_loop, args=(stop,), daemon=True)
        pinger.start()
        old = {}
        try:
            try:
                rc = self.run(kind, cmd, wait, priority)
            except Exception as exc:  # the outcome must still reach the agent
                self._warn(f"heavy-notify: guard error: {exc!r}")
                rc = 1
            finally:
                # run() has restored the default handlers. From here on a stray
                # SIGINT, SIGTERM or SIGHUP must not lose the outcome (stop-all
                # no longer lists us).
                for sig in FORWARDED_SIGNALS:
                    with contextlib.suppress(ValueError, OSError):
                        old[sig] = signal.signal(sig, _ignore_signal)
                stop.set()
                pinger.join(PASEO_TIMEOUT + 5)
            if rc == EX_TEMPFAIL and self.last_refusal and fds["FD"] is not None:
                if tell(f"refused {self.last_refusal}", ack=True):
                    return rc  # refused before queuing: the caller printed it
            elif tell(f"ended {rc}", ack=True):
                return rc  # ended before queuing: the caller printed it
            notifier.finish(rc, self.last_refusal)
        finally:
            for sig, handler in old.items():
                with contextlib.suppress(ValueError, OSError, TypeError):
                    signal.signal(sig, handler)
        return rc

    # -- stop-all ----------------------------------------------------------------------

    def _is_heavy_guard(self, pid: object) -> bool:
        if not isinstance(pid, int) or pid <= 1 or not self.pid_alive(pid):
            return False
        return "heavy.py" in (self.proc_command(pid) or "")

    def _record_identity_trusted(self, pid: int, rec: Mapping) -> bool:
        if rec.get("identity"):
            return self.locks.identity_matches(pid, rec["identity"]) is True
        if rec.get("lstart"):
            return self.proc_start(pid) == rec["lstart"]
        return True  # legacy records without identity still require a guard command

    def _running_identity_trusted(self, rec: Mapping) -> bool:
        pgid = rec.get("pgid")
        if rec.get("identity"):
            # Strong child identity never falls back to guard or argv0.
            return self.locks.identity_matches(pgid, rec["identity"]) is True
        guard = rec.get("guard")
        trusted = self._is_heavy_guard(guard)
        if rec.get("guard_identity"):
            trusted = trusted and self.locks.identity_matches(guard, rec["guard_identity"]) is True
        if trusted:
            return True
        if rec.get("lstart"):
            return self.proc_start(pgid) == rec["lstart"]
        if rec.get("guard_identity"):
            return False  # a reused/unreadable guard identity needs child proof
        leader = self.proc_command(pgid) or ""
        argv0 = os.path.basename(str(rec.get("argv0") or ""))
        return bool(argv0) and argv0 in leader

    def stop_all(self, grace: float = DEFAULT_GRACE) -> int:
        my_pgid = os.getpgrp()
        guards: List[Tuple[int, str]] = []
        groups: List[Tuple[int, str, dict]] = []
        # Waiting guards first, so they cannot grab a slot that is about to free up.
        for path, rec in self._records("waiting"):
            pid = rec.get("guard")
            if pid == os.getpid():
                continue
            if (not self._is_heavy_guard(pid)
                    or not self._record_identity_trusted(pid, rec)):
                remove_file(path)
                continue
            try:
                os.kill(pid, signal.SIGTERM)
            except OSError:
                remove_file(path)
                continue
            self._say(f"stop-all: SIGTERM waiting guard pid {pid} ({rec.get('kind')}: {rec.get('cmd')})")
            guards.append((pid, path))
        for path, rec in self._records("running"):
            pgid = rec.get("pgid")
            if not isinstance(pgid, int) or pgid <= 1:
                remove_file(path)
                continue
            if pgid == my_pgid:
                self._say(f"stop-all: skipping pgid {pgid}: it is this process's own group")
                continue
            if not self.group_alive(pgid):
                remove_file(path)
                continue
            trusted = self._running_identity_trusted(rec)
            if not trusted:
                self._say(f"stop-all: skipping pgid {pgid}: its guard is gone and its leader "
                          "is not the process we started; check it by hand")
                remove_file(path)
                continue
            try:
                os.killpg(pgid, signal.SIGTERM)
            except OSError:
                remove_file(path)
                continue
            self._say(f"stop-all: SIGTERM process group {pgid} ({rec.get('kind')}: {rec.get('cmd')})")
            groups.append((pgid, path, rec))
        if not guards and not groups:
            self._say("stop-all: nothing to stop")
            return 0
        deadline = self.clock.monotonic() + max(grace, 0.0)
        while self.clock.monotonic() < deadline:
            if not any(self.pid_alive(p) for p, _ in guards) and \
                    not any(self.group_alive(g) for g, _, _ in groups):
                break
            self.clock.sleep(0.2)
        for pgid, path, rec in groups:
            if self.group_alive(pgid) and self._running_identity_trusted(rec):
                try:
                    os.killpg(pgid, signal.SIGKILL)
                    self._say(f"stop-all: SIGKILL process group {pgid}: still alive after {fmt_secs(grace)}")
                except OSError:
                    pass
            remove_file(path)
        for pid, path in guards:
            if self.pid_alive(pid):
                self._say(f"stop-all: waiting guard pid {pid} is still alive after {fmt_secs(grace)}")
            else:
                remove_file(path)
        return 0

    # -- mode ----------------------------------------------------------------------------

    def set_mode(self, mode: Optional[str], window_text: Optional[str]) -> int:
        now = self.clock.now()
        if mode is None:
            if window_text:
                self._warn("heavy: --window needs a mode, e.g. heavy.py mode nightshift --window 22:00-06:00")
                return EX_USAGE
            self._say(self._mode_line(self.mode_state(), now))
            return 0
        if mode not in MODES:
            self._warn(f"heavy: unknown mode {mode!r}; use one of {', '.join(MODES)}")
            return EX_USAGE
        if window_text and mode != "nightshift":
            self._warn("heavy: --window only applies to nightshift")
            return EX_USAGE
        try:
            window = Window.parse(window_text or DEFAULT_WINDOW)
        except ValueError as exc:
            self._warn(f"heavy: {exc}")
            return EX_USAGE
        data: Dict[str, object] = {"mode": mode, "since": iso(now)}
        if mode == "nightshift":
            data["window"] = str(window)
        try:
            write_json_atomic(self.mode_path, data)
        except OSError as exc:
            self._warn(f"heavy: cannot write {self.tilde(self.mode_path)}: {exc}")
            return 1
        self._say(self._mode_line(ModeState(mode, window), now))
        return 0

    def _mode_line(self, state: ModeState, now: _dt.datetime) -> str:
        if state.error:
            return f"mode: invalid ({state.error})"
        if state.mode == "nightshift":
            inside = "yes" if state.in_window(now) else "no"
            return f"mode: nightshift, window {state.window}, inside the window now ({now:%H:%M}): {inside}"
        return f"mode: {state.mode}"

    # -- status --------------------------------------------------------------------------

    def status(self) -> int:
        now = self.clock.now()
        state = self.mode_state()
        mem = self.read_memory()
        say = self._say

        say(f"run dir:   {self.tilde(self.run_dir)}"
            + (" (CI mode: no run dir, continuous, Linux readers)" if self.ci_mode else ""))
        if state.error:
            say(f"mode:      invalid: {state.error} (non-light kinds are refused)")
        else:
            say(f"mode:      {state.mode}" + (" (no mode.json)" if state.source == "default" else ""))
        if state.mode == "nightshift" and not state.error:
            say(f"window:    {state.window}")
            say(f"in window: {'yes' if state.in_window(now) else 'no'} (local time {now:%H:%M})")
        else:
            say("window:    none (only nightshift has one)")
            say("in window: n/a")

        say(f"pressure:  {level_name(mem.level)}"
            + (f" (level {mem.level})" if mem.level is not None else " (treated as warn)")
            + f" [{mem.source}]")
        say("free mem:  " + ("unknown" if mem.free_pct is None else f"{mem.free_pct:.0f}%"))
        if mem.swap_total_mb is None:
            say("swap:      unknown")
        else:
            say(f"swap:      {mem.swap_free_mb or 0:.0f} MB free of {mem.swap_total_mb:.0f} MB"
                + (" (grows on demand)" if mem.swap_dynamic else ""))

        cap = self.capacity(mem, state, now)
        why = f"{level_name(mem.level)} pressure"
        if state.in_window(now):
            why += ", nightshift window"
        if self.max_slots() is not None:
            why += f", BGD_MAX_SLOTS={self.max_slots()}"
        resource_lines = []
        with self._admission():
            slots = self.locks.slot_names()
            live = [n for n in slots if self.locks.state(n) == "live"]
            resource_lines.append(f"slots:     capacity {cap} ({why}), {len(live)} held")
            for name in slots:
                lock_state = self.locks.state(name)
                mark = "" if lock_state == "live" else " (stale, cleared on the next run)"
                resource_lines.append(f"  {name:<8} {self._describe(self.locks.owner(name))}{mark}")

            min_free, min_swap = self.browser_floors()
            for kind in KIND_LOCKS:
                lock_state = self.locks.state(kind)
                if lock_state == "free":
                    line = "free"
                else:
                    line = self._describe(self.locks.owner(kind))
                    if lock_state == "stale":
                        line += " (stale, cleared on the next run)"
                if kind == "browser":
                    block = browser_block_reason(mem, min_free, min_swap)
                    swap_need = "" if mem.swap_dynamic else f" and free swap >= {min_swap:g} MB"
                    line += (f"; launch needs free mem >= {min_free:g}%{swap_need}: "
                             + ("ok" if block is None else f"blocked, {block}"))
                resource_lines.append(f"{kind + ':':<10} {line}")

            tickets = self._tickets()
            waiting = []
            for path, rec in self._records("waiting"):
                if self.locks.process_alive(rec.get("guard"), rec.get("identity")):
                    waiting.append(rec)
                else:
                    remove_file(path)
        for line in resource_lines:
            say(line)
        say(f"queue:     {len(tickets)} (protocol {PROTOCOL_VERSION})")
        ticket_pids = {rec.get("pid") for _, rec in tickets}
        for position, (_, rec) in enumerate(tickets, 1):
            age = time.time() - float(rec.get("t0") or time.time())
            say(f"  {position}. {rec.get('priority', 'normal')} {rec.get('kind')} "
                f"{fmt_secs(age)} pid {rec.get('pid')} blocked on {rec.get('blocked_on')}: {rec.get('cmd')}")
        say(f"waiting:   {len(waiting)}")
        for rec in waiting:
            age = time.time() - float(rec.get("t0") or time.time())
            note = ""
            if rec.get("guard") not in ticket_pids:
                note = (" (NO TICKET: legacy guard, may overtake queue)" if not rec.get("protocol")
                        else " (no ticket: starting or inherited resources)")
            say(f"  pid {rec.get('guard')} {rec.get('kind')} {fmt_secs(age)}: {rec.get('cmd')}{note}")
        running = self._records("running")
        say(f"running:   {len(running)}")
        for _, rec in running:
            age = time.time() - float(rec.get("t0") or time.time())
            gone = "" if self.group_alive(rec.get("pgid")) else " (gone)"
            nested = " nested" if rec.get("nested") else ""
            say(f"  pgid {rec.get('pgid')} {rec.get('kind')}{nested} {fmt_secs(age)}: {rec.get('cmd')}{gone}")

        recent = self._recent(5)
        say(f"recent:    {'none' if not recent else f'last {len(recent)} of heavy.jsonl'}")
        for entry in recent:
            rss = entry.get("maxrss_kb") or 0
            extra = f" refused: {entry['refused']}" if entry.get("refused") else ""
            say(f"  {entry.get('ts')} {entry.get('kind')} rc={entry.get('rc')} "
                f"{entry.get('secs')}s {rss / 1024:.0f} MB: {entry.get('cmd')}{extra}")
        return 0

    def _recent(self, n: int) -> List[dict]:
        try:
            with open(self.log_path, encoding="utf-8") as fh:
                lines = collections.deque(fh, maxlen=n)
        except OSError:
            return []
        out = []
        for line in lines:
            try:
                entry = json.loads(line)
            except ValueError:
                continue
            if isinstance(entry, dict):
                out.append(entry)
        return out


def _read_line(fd: int, timeout: float) -> Optional[str]:
    """One line from fd: None on timeout, "" when the writer closed without one."""
    data = b""
    deadline = time.monotonic() + timeout
    while b"\n" not in data:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return None
        try:
            ready, _, _ = select.select([fd], [], [], remaining)
        except InterruptedError:
            continue
        if not ready:
            return None
        chunk = os.read(fd, 4096)
        if not chunk:
            break
        data += chunk
    return data.decode("utf-8", "replace").split("\n", 1)[0]


def _read_byte(fd: int, timeout: float) -> bytes:
    try:
        ready, _, _ = select.select([fd], [], [], timeout)
        return os.read(fd, 1) if ready else b""
    except OSError:
        return b""
    finally:
        with contextlib.suppress(OSError):
            os.close(fd)


def _ignore_signal(signum, frame) -> None:
    pass


class Notifier:
    """Messages one Paseo agent about one detached job: keep-warm pings, then the outcome."""

    def __init__(self, guard: Guard, agent: str, kind: str, cmd: List[str], log_path: str):
        self.guard = guard
        self.agent = agent
        self.kind = kind
        self.cmd = cmd
        self.short = display_cmd(cmd, 120)
        self.log_path = log_path
        self.t0 = guard.clock.monotonic()
        self.last_contact = self.t0
        self.next_try = self.t0
        self.provider = ""
        self.inspected_at: Optional[float] = None
        # Held across each send, so no ping can follow or overlap the outcome.
        self.lock = threading.Lock()
        self.finished = False
        self.warm_claude = guard._env_float("HEAVY_WARM_CLAUDE", WARM_CLAUDE)
        self.warm_codex = guard._env_float("HEAVY_WARM_CODEX", WARM_CODEX)
        self.warm_max = guard._env_float("HEAVY_WARM_MAX", WARM_MAX)

    def note(self, msg: str) -> None:
        self.guard._warn(f"heavy-notify: {msg}")

    def paseo(self, *args: str) -> Tuple[bool, str, str]:
        argv = [self.guard.env.get("PASEO_BIN") or "paseo", *args]
        # Not the job's directory: the outcome may wait for a busy agent,
        # which meanwhile can merge and remove that worktree, and the paseo
        # CLI (Node) dies at startup when its working directory is gone.
        cwd = next((d for d in (self.guard.run_dir, self.guard.home) if os.path.isdir(d)), "/")
        try:
            res = subprocess.run(argv, env=self.guard.env, stdin=subprocess.DEVNULL, cwd=cwd,
                                 capture_output=True, text=True, timeout=PASEO_TIMEOUT)
        except (OSError, subprocess.SubprocessError) as exc:
            return False, "", str(exc)
        detail = (res.stderr or res.stdout or "").strip()[-500:]
        return res.returncode == 0, res.stdout or "", detail or f"exit {res.returncode}"

    def inspect(self) -> dict:
        """The agent's paseo inspect record ({} if unreadable); remembers its provider."""
        self.inspected_at = self.guard.clock.monotonic()
        ok, out, _ = self.paseo("inspect", self.agent, "--json")
        try:
            data = json.loads(out) if ok else {}
        except ValueError:
            data = {}
        data = data if isinstance(data, dict) else {}
        if not self.provider:
            self.provider = str(data.get("Provider") or "")
        return data

    def interval(self) -> float:
        return self.warm_codex if "codex" in self.provider.lower() else self.warm_claude

    def busy(self, data: Mapping) -> bool:
        return str(data.get("Status") or "").lower() == "running"

    def closed(self, data: Mapping) -> bool:
        return str(data.get("Status") or "").lower() == "closed" or data.get("Archived") is True

    def recipient(self, data: Mapping) -> Optional[str]:
        """The closed agent's parent, when the outcome should go there instead."""
        parent = str(data.get("ParentAgentId") or "")
        if self.closed(data) and AGENT_RE.match(parent) and parent.lower() != self.agent:
            return parent.lower()
        return None

    def where(self) -> str:
        if self.guard.started_at is not None:
            return f"is still running ({fmt_secs(self.guard.clock.monotonic() - self.guard.started_at)} so far)"
        tickets = sorted((rec for _, rec in self.guard._records("queue")), key=Guard._ticket_order)
        tokens = [rec.get("token") for rec in tickets]
        if self.guard.token in tokens:
            return (f"is still waiting in the queue (number {tokens.index(self.guard.token) + 1}"
                    f" of {len(tokens)})")
        return "is still waiting in the queue"

    def maybe_ping(self) -> bool:
        now = self.guard.clock.monotonic()
        if now - self.t0 >= self.warm_max or now < self.next_try:
            return False
        since = now - self.last_contact
        if since < min(self.warm_codex, self.warm_claude):
            return False
        if self.provider and since < self.interval():
            return False
        if not self.provider and self.inspected_at is not None and now - self.inspected_at < PING_RETRY:
            return False
        data = self.inspect()
        if since < self.interval():
            return False
        if self.closed(data):  # it will never read a ping
            self.last_contact = now
            self.note("agent is closed; keep-warm ping skipped")
            return False
        if self.busy(data):  # its cache is warm, and a message would cut its turn
            self.last_contact = now
            self.note("agent is busy; keep-warm ping skipped")
            return False
        text = (f"heavy.py keep-warm ping: your {self.kind} job ({self.short}) {self.where()}. "
                "Reply with one word and end your turn. Check nothing; a message will wake you "
                "when the job ends.")
        with self.lock:
            if self.finished:
                return False
            ok, _, detail = self.paseo("send", self.agent, text, "--no-wait", "--json")
        if ok:
            self.last_contact = now
            self.note(f"keep-warm ping sent after {fmt_secs(since)}")
            return True
        self.next_try = now + PING_RETRY
        self.note(f"keep-warm ping failed: {detail}")
        return False

    def ping_loop(self, stop: threading.Event) -> None:
        while not stop.wait(PING_POLL):
            try:
                self.maybe_ping()
            except Exception as exc:  # pings are best effort; the outcome is not
                self.note(f"keep-warm ping error: {exc!r}")

    def outcome(self, rc: int, refusal: Optional[str]) -> str:
        if rc == 0:
            return "ok (exit 0)"
        if rc == EX_TEMPFAIL and refusal:
            if "gave up after waiting" in refusal:
                return f"timed out in the queue (exit {rc}): {refusal}"
            return f"refused (exit {rc}): {refusal}"
        if 128 < rc < 160:
            return f"stopped by signal {rc - 128} (exit {rc})"
        return f"failed (exit {rc})"

    def tail(self) -> str:
        try:
            with open(self.log_path, "rb") as fh:
                fh.seek(0, os.SEEK_END)
                fh.seek(max(fh.tell() - 65536, 0))
                data = fh.read()
        except OSError:
            return ""
        lines = []
        for raw in data.decode("utf-8", "replace").split("\n"):
            line = ANSI_RE.sub("", raw.rsplit("\r", 1)[-1]).rstrip()
            if not line.strip() or line.startswith("heavy-notify:"):
                continue
            if len(line) > NOTIFY_LINE_MAX:
                line = line[:NOTIFY_LINE_MAX - 3] + "..."
            lines.append(line)
        return "\n".join(lines[-NOTIFY_TAIL_LINES:])

    def message(self, rc: int, refusal: Optional[str]) -> str:
        end = self.guard.clock.monotonic()
        timing = f"after {fmt_secs(end - self.t0)}"
        started = self.guard.started_at
        if started is not None:
            timing += f" (queued {fmt_secs(started - self.t0)}, ran {fmt_secs(end - started)})"
        lines = [f"heavy.py: your detached {self.kind} job ended: {self.outcome(rc, refusal)}, {timing}.",
                 f"Command: {self.short}",
                 f"Log: {self.guard.tilde(self.log_path)}"]
        tail = self.tail()
        if tail:
            lines += ["Last lines:", tail]
        return "\n".join(lines)

    def finish(self, rc: int, refusal: Optional[str]) -> bool:
        with self.lock:
            self.finished = True
        text = self.message(rc, refusal)
        waited = 0.0
        data = self.inspect()
        while waited < BUSY_MAX and self.busy(data):
            self.guard.clock.sleep(BUSY_POLL)
            waited += BUSY_POLL
            data = self.inspect()
        if waited:
            self.note(f"waited {fmt_secs(waited)} for the agent to go idle")
        target = self.agent
        parent = self.recipient(data)
        if parent:
            target = parent
            text = (f"heavy.py: agent {self.agent} is closed, so the outcome of the job it "
                    f"started comes to you, its parent.\n{text}")
            self.note(f"agent is closed; sending the outcome to its parent {parent}")
        detail = ""
        for attempt in range(len(NOTIFY_BACKOFF) + 1):
            if attempt:
                self.guard.clock.sleep(NOTIFY_BACKOFF[attempt - 1])
            ok, _, detail = self.paseo("send", target, text, "--no-wait", "--json")
            if ok:
                self.note(f"sent the outcome to {target}")
                return True
            self.note(f"send {attempt + 1} failed: {detail}")
        self.alert(rc, refusal, text, detail)
        return False

    def alert(self, rc: int, refusal: Optional[str], text: str, detail: str) -> None:
        # The coordinator's waiter watches alerts/quota-*.md.
        directory = os.path.join(self.guard.configured_run_dir, "alerts")
        body = (f"# heavy.py could not notify its agent\n\n"
                f"- Agent: {self.agent}\n- Kind: {self.kind}\n- Command: {self.short}\n"
                f"- Outcome: {self.outcome(rc, refusal)}\n- Log: {self.guard.tilde(self.log_path)}\n"
                f"- Last send error: {detail}\n\nThe message it tried to send:\n\n{text}\n")
        try:
            os.makedirs(directory, exist_ok=True)
            stamp = int(time.time())
            for n in range(100):
                suffix = f"-{n}" if n else ""
                path = os.path.join(directory, f"quota-{stamp}-heavy-notify-failed{suffix}.md")
                try:
                    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
                except FileExistsError:
                    continue
                with os.fdopen(fd, "w", encoding="utf-8") as fh:
                    fh.write(body)
                self.note(f"wrote {self.guard.tilde(path)}")
                return
        except OSError as exc:
            self.note(f"cannot write the alert: {exc}")


def _nice10() -> None:
    try:
        os.nice(10)
    except OSError:
        pass


# ----------------------------------------------------------------------------
# CLI


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="heavy.py", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", metavar="COMMAND")
    sub.required = True

    run = sub.add_parser("run", help="run CMD under the guard: heavy.py run --kind KIND -- CMD...",
                         description="Run CMD under the guard. Put -- before the command.")
    run.add_argument("--kind", required=True, choices=KINDS)
    run.add_argument("--wait", type=float, default=None, metavar="SECONDS",
                     help="how long to wait for a slot or lock (default 1800 or $BGD_HEAVY_WAIT)")

    run.add_argument("--priority", choices=PRIORITIES, default=None,
                     help="queue priority (default normal or $HEAVY_PRIORITY); only the coordinator grants high")
    run.add_argument("--notify", default=None, metavar="UUID|auto",
                     help="detach and message this Paseo agent when the job ends (default $HEAVY_NOTIFY; "
                          "auto reads $PASEO_AGENT_ID)")

    sub.add_parser("status", help="show mode, pressure, slots, locks, ordered queue and recent runs")

    stop = sub.add_parser("stop-all", help="stop every job this script started")
    stop.add_argument("--grace", type=float, default=DEFAULT_GRACE, metavar="SECONDS",
                      help="seconds between SIGTERM and SIGKILL (default 10)")

    mode = sub.add_parser("mode", help="show or set the mode")
    mode.add_argument("mode", nargs="?", choices=MODES)
    mode.add_argument("--window", metavar="HH:MM-HH:MM",
                      help=f"nightshift window, local time (default {DEFAULT_WINDOW})")
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args_in = list(sys.argv[1:] if argv is None else argv)
    cmd: Optional[List[str]] = None
    if "--" in args_in:
        cut = args_in.index("--")
        args_in, cmd = args_in[:cut], args_in[cut + 1:]
    parser = build_parser()
    args = parser.parse_args(args_in)
    if args.command != "run" and cmd is not None:
        parser.error("only the run command takes -- CMD")
    guard = Guard()
    if args.command == "run":
        if cmd is None:
            parser.error("run needs -- before the command, e.g. heavy.py run --kind test -- go test ./...")
        if guard.env.get("BGD_HEAVY_NOTIFY_AGENT"):
            return guard.run_notified(args.kind, cmd, args.wait, args.priority)
        return guard.run(args.kind, cmd, args.wait, args.priority, args.notify)
    if args.command == "status":
        return guard.status()
    if args.command == "stop-all":
        return guard.stop_all(args.grace)
    if args.command == "mode":
        return guard.set_mode(args.mode, args.window)
    parser.error(f"unknown command {args.command!r}")
    return EX_USAGE


if __name__ == "__main__":
    sys.exit(main())
