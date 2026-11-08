"""Tests for tools/heavy.py, the RAM, slot and mode guard.

Most tests drive an in-process Guard with an injected memory reader, clock and
liveness checks, and a run dir in a temporary directory. A few start real
child processes (tiny Python one-liners) to check signals and stop-all.

Run: python3 -m unittest discover -s tests -v
"""

from __future__ import annotations

import contextlib
import datetime as dt
import importlib.util
import io
import json
import os
import select
import signal
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HEAVY_PATH = os.path.join(ROOT, "tools", "heavy.py")


def _load_heavy():
    spec = importlib.util.spec_from_file_location("board-game-dev_heavy", HEAVY_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # dataclasses look the module up here
    spec.loader.exec_module(module)
    return module


heavy = _load_heavy()

# Far above any real pid limit (macOS 99999, Linux at most 4194304), so a real
# liveness check would say "dead"; tests mark them alive or dead explicitly.
FAKE_LIVE = 10_000_001
FAKE_LIVE_2 = 10_000_002
FAKE_DEAD = 10_000_003

PY = sys.executable


DEFAULTED = tuple(key for key, _ in heavy.DEFAULT_CHILD_ENV)


def clean_environ():
    """os.environ without the guard's own variables, CI markers or the defaulted ones."""
    return {k: v for k, v in os.environ.items()
            if not k.startswith(heavy.ENV_PREFIX) and k not in (
                "CI", "RUNNER_TEMP", "HEAVY_PRIORITY", "HEAVY_NOTIFY", "PASEO_AGENT_ID", "PASEO_BIN",
                "MAKELEVEL", "MAKEFLAGS", "MFLAGS") + DEFAULTED}


class FakeClock:
    def __init__(self, now: dt.datetime):
        self.start = now
        self.mono = 0.0
        self.sleeps = []
        self.on_sleep = None

    def now(self):
        return self.start + dt.timedelta(seconds=self.mono)

    def monotonic(self):
        return self.mono

    def sleep(self, secs):
        self.sleeps.append(secs)
        self.mono += secs
        if self.on_sleep:
            self.on_sleep(len(self.sleeps))


def at(hour, minute=0):
    return dt.datetime(2026, 10, 1, hour, minute, 0)


class GuardCase(unittest.TestCase):
    """Base class: a temp run dir and a Guard factory with injected readers."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = self._tmp.name
        self.run_dir = os.path.join(self.tmp, "run")
        os.makedirs(self.run_dir)
        self.clock = FakeClock(at(12))
        self.fake_live = {FAKE_LIVE, FAKE_LIVE_2}
        self.out = io.StringIO()
        self.err = io.StringIO()

    def tearDown(self):
        self._tmp.cleanup()

    def pid_alive(self, pid):
        if pid in self.fake_live:
            return True
        if pid == FAKE_DEAD:
            return False
        return heavy.default_pid_alive(pid)

    def group_alive(self, pgid):
        if pgid in self.fake_live:
            return True
        if pgid == FAKE_DEAD:
            return False
        return heavy.default_group_alive(pgid)

    def guard(self, level=1, free=50.0, swap_total=8192.0, swap_free=4096.0, env=None,
              platform="darwin", reader=None, **kw):
        base = clean_environ()
        base[heavy.env_name('RUN_DIR')] = self.run_dir
        base["HOME"] = self.tmp
        base.update(env or {})
        mem = heavy.Memory(level=level, free_pct=free, swap_total_mb=swap_total,
                           swap_free_mb=swap_free, source="test")
        self.out = io.StringIO()
        self.err = io.StringIO()
        return heavy.Guard(env=base, platform=platform, reader=reader or (lambda: mem),
                           clock=self.clock, pid_alive=self.pid_alive, group_alive=self.group_alive,
                           stdout=self.out, stderr=self.err, **kw)

    def heavy_dir(self, *parts):
        return os.path.join(self.run_dir, "heavy", *parts)

    def hold(self, name, pid=FAKE_LIVE, kind="test", cmd="sleep forever"):
        """Create a lock dir owned by pid, as another guard would."""
        path = self.heavy_dir(name)
        os.makedirs(path)
        with open(os.path.join(path, heavy.OWNER_FILE), "w") as fh:
            json.dump({"pid": pid, "kind": kind, "cmd": cmd, "token": "other", "t0": time.time()}, fh)
        return path

    def set_owner(self, path, **fields):
        """Merge fields into a held lock's owner.json."""
        owner = os.path.join(path, heavy.OWNER_FILE)
        with open(owner) as fh:
            info = json.load(fh)
        info.update(fields)
        with open(owner, "w") as fh:
            json.dump(info, fh)

    def sentinel_cmd(self, name="ran"):
        path = os.path.join(self.tmp, name)
        return path, [PY, "-c", f"open({path!r}, 'w').write('x')"]

    def log_entries(self):
        path = os.path.join(self.run_dir, "logs", "heavy.jsonl")
        if not os.path.exists(path):
            return []
        with open(path) as fh:
            return [json.loads(line) for line in fh]

    def write_mode(self, data):
        with open(os.path.join(self.run_dir, "mode.json"), "w") as fh:
            fh.write(data if isinstance(data, str) else json.dumps(data))


class WindowTests(unittest.TestCase):
    def test_simple_window(self):
        w = heavy.Window.parse("00:00-10:00")
        self.assertEqual((w.start, w.end), (0, 600))
        self.assertTrue(w.contains_time(at(0, 0)))
        self.assertTrue(w.contains_time(at(9, 59)))
        self.assertFalse(w.contains_time(at(10, 0)))
        self.assertFalse(w.contains_time(at(23, 59)))

    def test_window_wrapping_midnight(self):
        w = heavy.Window.parse("22:00-06:00")
        for inside in (at(22, 0), at(23, 59), at(0, 0), at(3, 30), at(5, 59)):
            self.assertTrue(w.contains_time(inside), inside)
        for outside in (at(6, 0), at(12, 0), at(21, 59)):
            self.assertFalse(w.contains_time(outside), outside)

    def test_whole_day_and_end_of_day(self):
        self.assertTrue(heavy.Window.parse("00:00-24:00").contains_time(at(23, 59)))
        late = heavy.Window.parse("23:00-24:00")
        self.assertTrue(late.contains_time(at(23, 30)))
        self.assertFalse(late.contains_time(at(0, 0)))

    def test_single_digit_hours_and_round_trip(self):
        w = heavy.Window.parse("7:05-9:30")
        self.assertEqual(str(w), "07:05-09:30")
        self.assertEqual(heavy.Window.parse(str(w)), w)

    def test_invalid_windows(self):
        for text in ("", "10:00", "1000-1200", "25:00-01:00", "10:60-11:00", "24:00-01:00",
                     "10:00-24:30", "10:00-10:00", "aa:bb-cc:dd"):
            with self.assertRaises(ValueError, msg=text):
                heavy.Window.parse(text)


class ModeGateTests(GuardCase):
    def state(self, mode, window="00:00-10:00"):
        return heavy.ModeState(mode, heavy.Window.parse(window))

    def test_missing_mode_file_means_continuous(self):
        st = heavy.load_mode(os.path.join(self.run_dir, "mode.json"))
        self.assertEqual((st.mode, st.error, st.source), ("continuous", None, "default"))
        self.assertIsNone(heavy.gate_mode("test", st, at(12)))

    def test_paused_refuses_everything_but_light(self):
        st = self.state("paused")
        for kind in heavy.KINDS:
            reason = heavy.gate_mode(kind, st, at(3))
            if kind == "light":
                self.assertIsNone(reason)
            else:
                self.assertIn("paused", reason)

    def test_nightshift_window_gate(self):
        st = self.state("nightshift", "22:00-06:00")
        self.assertIsNone(heavy.gate_mode("build", st, at(23, 30)))
        self.assertIsNone(heavy.gate_mode("build", st, at(2, 0)))
        self.assertIn("outside the window 22:00-06:00", heavy.gate_mode("build", st, at(12)))
        self.assertIsNone(heavy.gate_mode("light", st, at(12)))

    def test_mode_file_with_window(self):
        self.write_mode({"mode": "nightshift", "window": "22:00-06:00"})
        st = heavy.load_mode(os.path.join(self.run_dir, "mode.json"))
        self.assertEqual((st.mode, str(st.window)), ("nightshift", "22:00-06:00"))
        self.write_mode({"mode": "nightshift"})
        st = heavy.load_mode(os.path.join(self.run_dir, "mode.json"))
        self.assertEqual(str(st.window), heavy.DEFAULT_WINDOW)

    def test_invalid_mode_file_refuses_heavy_but_not_light(self):
        for bad in ("{not json", json.dumps({"mode": "turbo"}),
                    json.dumps({"mode": "nightshift", "window": "late"}), "[]"):
            self.write_mode(bad)
            st = heavy.load_mode(os.path.join(self.run_dir, "mode.json"))
            self.assertIsNotNone(st.error, bad)
            self.assertIsNotNone(heavy.gate_mode("test", st, at(3)), bad)
            self.assertIsNone(heavy.gate_mode("light", st, at(3)), bad)

    def test_mode_command_writes_and_validates(self):
        g = self.guard()
        self.assertEqual(g.set_mode("nightshift", "22:00-06:00"), 0)
        with open(os.path.join(self.run_dir, "mode.json")) as fh:
            data = json.load(fh)
        self.assertEqual((data["mode"], data["window"]), ("nightshift", "22:00-06:00"))
        self.assertIn("window 22:00-06:00", self.out.getvalue())

        g = self.guard()
        self.assertEqual(g.set_mode("nightshift", None), 0)
        self.assertEqual(g.mode_state().window, heavy.Window.parse(heavy.DEFAULT_WINDOW))

        g = self.guard()
        self.assertEqual(g.set_mode("continuous", "01:00-02:00"), heavy.EX_USAGE)
        self.assertEqual(g.set_mode("nightshift", "01:00"), heavy.EX_USAGE)
        self.assertEqual(g.set_mode("paused", None), 0)
        self.assertEqual(g.mode_state().mode, "paused")
        self.assertEqual(g.set_mode(None, None), 0)
        self.assertIn("mode: paused", self.out.getvalue())


class CapacityTests(GuardCase):
    def test_capacity_by_pressure(self):
        self.assertEqual(heavy.slot_capacity(1, False), 2)
        self.assertEqual(heavy.slot_capacity(1, True), 3)
        self.assertEqual(heavy.slot_capacity(2, False), 1)
        self.assertEqual(heavy.slot_capacity(2, True), 1)
        self.assertEqual(heavy.slot_capacity(4, False), 0)
        self.assertEqual(heavy.slot_capacity(4, True), 0)
        self.assertEqual(heavy.slot_capacity(None, False), 1)  # unknown counts as warn

    def test_max_slots_caps_but_never_raises(self):
        self.assertEqual(heavy.slot_capacity(1, True, max_slots=1), 1)
        self.assertEqual(heavy.slot_capacity(2, False, max_slots=5), 1)
        g = self.guard(level=1, env={heavy.env_name('MAX_SLOTS'): "1"})
        self.assertEqual(g.capacity(g.read_memory()), 1)

    def test_nightshift_window_adds_a_slot(self):
        self.write_mode({"mode": "nightshift", "window": "22:00-06:00"})
        self.clock = FakeClock(at(23))
        g = self.guard(level=1)
        self.assertEqual(g.capacity(g.read_memory()), 3)
        self.write_mode({"mode": "continuous"})
        self.assertEqual(g.capacity(g.read_memory()), 2)


class BrowserThresholdTests(GuardCase):
    def mem(self, free=50.0, swap_total=8192.0, swap_free=4096.0):
        return heavy.Memory(level=1, free_pct=free, swap_total_mb=swap_total, swap_free_mb=swap_free)

    def test_free_memory_floor(self):
        self.assertIn("free memory 13%", heavy.browser_block_reason(self.mem(free=13), 14, 512))
        self.assertIsNone(heavy.browser_block_reason(self.mem(free=14), 14, 512))

    def test_swap_floor(self):
        self.assertIn("free swap 500 MB", heavy.browser_block_reason(self.mem(swap_free=500), 14, 512))
        self.assertIsNone(heavy.browser_block_reason(self.mem(swap_free=512), 14, 512))
        # No swap allocated yet (macOS grows swap on demand): nothing to protect.
        self.assertIsNone(heavy.browser_block_reason(self.mem(swap_total=0, swap_free=0), 14, 512))
        # Unknown readings do not block.
        self.assertIsNone(heavy.browser_block_reason(heavy.Memory(), 14, 512))

    def test_swap_floor_skipped_where_swap_grows(self):
        # macOS adds swap files on demand: low free swap is no reason to wait.
        mem = heavy.Memory(level=1, free_pct=50.0, swap_total_mb=8192.0, swap_free_mb=100.0,
                           swap_dynamic=True)
        self.assertIsNone(heavy.browser_block_reason(mem, 14, 512))
        # The free memory floor still applies.
        mem.free_pct = 10.0
        self.assertIn("free memory 10%", heavy.browser_block_reason(mem, 14, 512))

    def test_floors_are_env_tunable(self):
        g = self.guard(env={heavy.env_name('MIN_FREE_PCT_BROWSER'): "30", heavy.env_name('MIN_SWAP_FREE_MB_BROWSER'): "100"})
        self.assertEqual(g.browser_floors(), (30.0, 100.0))
        g = self.guard(env={heavy.env_name('MIN_FREE_PCT_BROWSER'): "lots"})
        self.assertEqual(g.browser_floors(), (14.0, 512.0))
        self.assertIn("ignoring", self.err.getvalue())

    def test_browser_refused_below_floor(self):
        g = self.guard(free=10)
        rc = g.run("browser", [PY, "-c", "pass"], wait=0)
        self.assertEqual(rc, heavy.EX_TEMPFAIL)
        self.assertIn("browser floor", self.err.getvalue())
        self.assertFalse(os.path.exists(self.heavy_dir("browser")))

    def test_browser_lock_has_capacity_one(self):
        self.hold("browser", kind="browser")
        g = self.guard(level=1)
        self.assertEqual(g.run("browser", [PY, "-c", "pass"], wait=0), heavy.EX_TEMPFAIL)
        self.assertIn("browser lock is held", self.err.getvalue())
        # A codex job is not blocked by the browser lock.
        self.assertEqual(self.guard(level=1).run("codex", [PY, "-c", "pass"], wait=0), 0)


class QueueTests(GuardCase):
    def ticket(self, token, kind="test", priority="normal", pid=FAKE_LIVE,
               created=1, **extra):
        rec = dict(pid=pid, token=token, kind=kind, priority=priority,
                   cmd="sentinel", cwd=self.tmp, t0=time.time(), created_ns=created,
                   blocked_on="slots", nested=False, inherited=[])
        rec.update(extra)
        heavy.write_json_atomic(self.heavy_dir("queue", token + ".json"), rec)
        return rec

    def attempt(self, g, rec):
        with g._admission():
            return g._attempt(rec["kind"], rec["nested"], set(rec["inherited"]), rec, g._tickets())

    def assert_empty_queue(self):
        directory = self.heavy_dir("queue")
        self.assertFalse(os.listdir(directory) if os.path.isdir(directory) else [])

    def test_strict_fifo_even_if_later_ticket_polls_first(self):
        g = self.guard(level=2)
        records = [self.ticket(str(i), created=i) for i in range(1, 4)]
        for index, rec in enumerate(records):
            for later in records[index + 1:]:
                self.assertIn("earlier queued", self.attempt(g, later)[1])
            held, reason, _ = self.attempt(g, rec)
            self.assertIsNone(reason)
            self.assertEqual(held, ["slot-1"])
            g._release(held, rec["token"])
            heavy.remove_file(self.heavy_dir("queue", rec["token"] + ".json"))

    def test_high_priority_ahead_of_normal_fifo_within_high(self):
        g = self.guard(level=2)
        normal = self.ticket("normal", created=1)
        first = self.ticket("first", priority="high", created=2)
        last = self.ticket("last", priority="high", created=3)
        self.assertIn("earlier queued", self.attempt(g, normal)[1])
        self.assertIn("earlier queued", self.attempt(g, last)[1])
        held, reason, _ = self.attempt(g, first)
        self.assertIsNone(reason)
        g._release(held, first["token"])
        with g._admission():
            self.assertEqual([r["token"] for _, r in g._tickets()], ["first", "last", "normal"])

    def test_new_fast_path_respects_existing_ticket(self):
        self.ticket("older")
        g = self.guard(level=2)
        self.assertEqual(g.run("test", [PY, "-c", "pass"], wait=0), heavy.EX_TEMPFAIL)
        self.assertEqual(len(os.listdir(self.heavy_dir("queue"))), 1)
        self.assertIn("earlier queued", self.err.getvalue())

    def test_browser_floor_reserves_nothing_even_with_stale_slot_reason(self):
        self.ticket("browser", kind="browser", blocked_on="slots")
        self.assertEqual(self.guard(level=2, free=10).run("lint", [PY, "-c", "pass"], wait=0), 0)
        self.write_mode({"mode": "paused"})
        g = self.guard(free=50)
        with g._admission():
            self.assertEqual(g._resource("browser", False, set(), g.read_memory(), g.mode_state()), "gate")

    def test_earlier_browser_uses_its_own_floor_settings(self):
        self.ticket("custom-floor", kind="browser", browser_floors=[30, 512])
        self.assertEqual(self.guard(level=2, free=20).run("lint", [PY, "-c", "pass"], wait=0), 0)
        heavy.remove_file(self.heavy_dir("queue", "custom-floor.json"))
        self.ticket("default-floor", kind="browser", browser_floors=[14, 512])
        g = self.guard(level=2, free=20, env={heavy.env_name('MIN_FREE_PCT_BROWSER'): "30"})
        self.assertEqual(g.run("lint", [PY, "-c", "pass"], wait=0), heavy.EX_TEMPFAIL)

    def test_browser_lock_reserves_only_browser_including_queued_followers(self):
        self.hold("browser", kind="browser")
        self.ticket("first", kind="browser", created=1)
        second = self.ticket("second", kind="browser", created=2)
        g = self.guard(level=2)
        self.assertIn("earlier queued", self.attempt(g, second)[1])
        self.assertEqual(g.run("test", [PY, "-c", "pass"], wait=0), 0)
        # After the physical lock frees the earlier browser reserves a slot;
        # the next browser must not overtake while its predecessor is asleep.
        g.locks.release("browser", "other")
        self.assertIn("earlier queued", self.attempt(g, second)[1])

    def test_stale_dead_reused_and_unknown_identity_tickets(self):
        self.ticket("dead", pid=FAKE_DEAD)
        self.ticket("reused", pid=FAKE_LIVE, identity="old")
        self.ticket("unknown", pid=FAKE_LIVE_2, identity="old")
        g = self.guard(proc_identity=lambda pid: "new" if pid == FAKE_LIVE else None)
        with g._admission():
            self.assertEqual([r["token"] for _, r in g._tickets()], ["unknown"])
        self.assertEqual(os.listdir(self.heavy_dir("queue")), ["unknown.json"])

    def test_cleanup_on_timeout_mode_refusal_and_signal(self):
        self.hold("slot-1")
        g = self.guard(level=2)
        self.assertEqual(g.run("test", [PY, "-c", "pass"], wait=2.5), heavy.EX_TEMPFAIL)
        self.assertEqual(sum(self.clock.sleeps), 2.5)
        self.assert_empty_queue()
        self.write_mode({"mode": "paused"})
        self.assertEqual(g.run("test", [PY, "-c", "pass"], wait=10), heavy.EX_TEMPFAIL)
        self.assert_empty_queue()
        self.write_mode({"mode": "continuous"})
        for sig in heavy.FORWARDED_SIGNALS:
            self.clock.on_sleep = lambda _, sig=sig: os.kill(os.getpid(), sig)
            self.assertEqual(g.run("test", [PY, "-c", "pass"], wait=10), 128 + sig)
            self.assert_empty_queue()

    def test_ticket_records_current_block_metadata(self):
        self.hold("slot-1")
        seen = []
        def observe(_):
            rec = self.guard()._records("queue")[0][1]
            seen.append(rec)
        self.clock.on_sleep = observe
        g = self.guard(level=2)
        self.assertEqual(g.run("test", [PY, "-c", "pass"], wait=1), heavy.EX_TEMPFAIL)
        self.assertEqual(seen[0]["blocked_on"], "slots")
        for key in ("pid", "identity", "kind", "cmd", "cwd", "created_ns", "priority"):
            self.assertIn(key, seen[0])
        self.assert_empty_queue()

    def test_inherited_runs_take_no_ticket_and_missing_kind_ignores_outer_slot_queue(self):
        self.hold("slot-1", pid=os.getpid())
        self.ticket("waiting-for-outer-slot", kind="browser")
        g = self.guard(level=2, env={heavy.env_name('HEAVY_HELD'): "1"})
        self.assertEqual(g.run("test", [PY, "-c", "pass"], wait=0), 0)
        self.assertEqual(g.run("browser", [PY, "-c", "pass"], wait=0), 0)
        self.assertEqual(os.listdir(self.heavy_dir("queue")), ["waiting-for-outer-slot.json"])

    def test_nested_missing_kind_waits_without_ever_taking_ticket(self):
        self.hold("browser", kind="browser")
        g = self.guard(env={heavy.env_name('HEAVY_HELD'): "1"})
        seen = []
        self.clock.on_sleep = lambda _: seen.append(g._records("queue"))
        self.assertEqual(g.run("browser", [PY, "-c", "pass"], wait=2), heavy.EX_TEMPFAIL)
        self.assertEqual(seen, [[], []])
        self.assert_empty_queue()

    def test_capacity_warn_normal_warn_counts_higher_numbered_slots(self):
        first = self.hold("slot-1")
        level = [2]
        g = self.guard(reader=lambda: heavy.Memory(level=level[0], free_pct=50))
        rec = self.ticket("queued")
        self.assertIsNotNone(self.attempt(g, rec)[1])
        level[0] = 1
        self.clock.sleep(1)
        held, reason, _ = self.attempt(g, rec)
        self.assertIsNone(reason)
        self.assertEqual(held, ["slot-2"])
        level[0] = 2
        self.clock.sleep(1)
        # Capacity shrinks below existing holders. Neither the low slot freeing
        # nor a later ticket allows a third job while slot-2 remains held.
        g.locks.release("slot-1", "other")
        later = self.ticket("later", created=2)
        self.assertIsNotNone(self.attempt(g, later)[1])
        heavy.remove_file(self.heavy_dir("queue", "queued.json"))
        self.assertIsNotNone(self.attempt(g, later)[1])
        g._release(held, rec["token"])
        self.assertIsNone(self.attempt(g, later)[1])

    def test_polling_does_not_log_each_change_in_holder_age(self):
        from unittest.mock import patch
        self.hold("slot-1")
        base = time.time()
        g = self.guard(level=2)
        with patch.object(heavy.time, "time", side_effect=lambda: base + self.clock.mono):
            self.assertEqual(g.run("test", [PY, "-c", "pass"], wait=4), heavy.EX_TEMPFAIL)
        self.assertEqual(len(self.err.getvalue().strip().splitlines()), 2)

    def test_memory_poll_cache_is_bounded_one_second(self):
        calls = []
        g = self.guard(reader=lambda: calls.append(1) or heavy.Memory(level=2))
        for _ in range(10):
            g._poll_memory()
        self.assertEqual(len(calls), 1)
        self.clock.sleep(heavy.POLL_INTERVAL)
        g._poll_memory()
        self.assertEqual(len(calls), 2)

    def test_admission_mutex_respects_wait_deadline(self):
        other = self.guard()
        g = self.guard()
        with other._admission():
            self.assertEqual(g.run("test", [PY, "-c", "pass"], wait=0.12), heavy.EX_TEMPFAIL)
        self.assertAlmostEqual(sum(self.clock.sleeps), 0.12)
        self.assertIn("admission lock is busy", self.err.getvalue())
        self.assert_empty_queue()

    def test_single_digit_birth_date_matches_legacy_ps_format(self):
        from unittest.mock import patch
        born = time.mktime((2026, 10, 1, 5, 0, 0, 0, 0, -1))
        real_localtime = time.localtime
        with patch.object(heavy.time, "localtime", return_value=real_localtime(born)):
            current = heavy.default_proc_start(os.getpid())
        self.assertEqual(current, "Thu Oct 1 05:00:00 2026")
        # Old default_proc_start normalizes ps's two spaces before day 1.
        path = self.hold("slot-1")
        self.set_owner(path, lstart="Thu Oct 1 05:00:00 2026")
        g = self.guard(proc_start=lambda _: current)
        self.assertEqual(g.locks.state("slot-1"), "live")

    def test_native_start_identity_matches_ps_without_subprocess_per_poll(self):
        if not (sys.platform == "darwin" or sys.platform.startswith("linux")):
            self.skipTest("native process identity is macOS/Linux only")
        from unittest.mock import patch
        expected = heavy._ps_field(os.getpid(), "lstart")
        with patch.object(heavy.subprocess, "run", side_effect=AssertionError("spawned ps")):
            for _ in range(4):
                self.assertEqual(heavy.default_proc_start(os.getpid()), expected)

    def test_priority_environment_cli_override_and_invalid_value(self):
        normal = self.ticket("normal")
        g = self.guard(level=2, env={"HEAVY_PRIORITY": "high"})
        self.assertEqual(g.run("test", [PY, "-c", "pass"], wait=0), 0)
        self.assertEqual(g.run("test", [PY, "-c", "pass"], wait=0, priority="normal"), heavy.EX_TEMPFAIL)
        self.assertEqual(g.run("test", [PY, "-c", "pass"], priority="typo"), heavy.EX_USAGE)

    def test_legacy_guards_can_overtake_but_still_share_safe_slot_locks(self):
        self.ticket("older")
        g = self.guard(level=2)
        overtakes = 0
        for i in range(3):
            # Old _attempt has no queue snapshot or admission mutex. Its mkdir
            # slot protocol is unchanged, so bypassing the queue cannot double
            # allocate a slot, but can starve an older ticket repeatedly.
            legacy = dict(pid=FAKE_LIVE_2, token=f"legacy-{i}", kind="test", cmd="sentinel")
            held, reason, _ = g._attempt("test", False, set(), legacy)
            self.assertIsNone(reason)
            overtakes += 1
            self.assertEqual(len(g._live_slots()), 1)
            self.assertIsNotNone(g._attempt("test", False, set(), dict(legacy, token="racer"))[1])
            g._release(held, legacy["token"])
        self.assertEqual(overtakes, 3)
        self.assertEqual(g.run("test", [PY, "-c", "pass"], wait=0), heavy.EX_TEMPFAIL)

    def test_status_queue_order_and_legacy_warning(self):
        self.ticket("normal", created=1)
        self.ticket("high", kind="lint", priority="high", created=2)
        g = self.guard()
        g._record("waiting", FAKE_LIVE_2, dict(guard=FAKE_LIVE_2, kind="test", cmd="legacy"))
        self.assertEqual(g.status(), 0)
        text = self.out.getvalue()
        self.assertIn("1. high lint", text)
        self.assertIn("2. normal test", text)
        self.assertIn("blocked on slots", text)
        self.assertIn("NO TICKET: legacy guard, may overtake queue", text)


class QueueReviewTests(GuardCase):
    """Review reproductions, all state and sentinel children stay in scratch dirs."""

    ticket = QueueTests.ticket
    attempt = QueueTests.attempt
    assert_empty_queue = QueueTests.assert_empty_queue

    def assert_no_owned_resources(self, g):
        self.assertFalse(g._live_slots())
        for kind in heavy.KIND_LOCKS:
            self.assertEqual(g.locks.state(kind), "free")
        self.assert_empty_queue()
        self.assertEqual(g._records("waiting"), [])

    def test_release_never_exposes_slot_before_kind_to_later_ticket(self):
        g = self.guard(level=2)
        holder = dict(pid=FAKE_LIVE, token="holder", kind="browser")
        held, reason, _ = g._attempt("browser", False, set(), holder)
        self.assertIsNone(reason)
        self.ticket("first", kind="browser", created=1)
        later = self.ticket("later", kind="test", created=2)
        release = g.locks.release
        attempts = []
        def observe(name, token):
            release(name, token)
            if not attempts:
                acquired, blocked, _ = self.attempt(g, later)
                attempts.append(blocked)
                for lock in acquired:
                    release(lock, later["token"])
        with patch.object(g.locks, "release", side_effect=observe):
            g._release(held, holder["token"])
        self.assertIsNotNone(attempts[0], "later test overtook the earlier browser during release")

    def test_strict_fifo_reserves_spare_capacity_for_sleeping_head(self):
        g = self.guard(level=1)
        first = self.ticket("first", created=1)
        later = self.ticket("later", created=2)
        self.assertEqual(g.capacity(g.read_memory()), 2)
        self.assertEqual(g._live_slots(), [])
        self.assertIn("earlier queued", self.attempt(g, later)[1])
        held, reason, _ = self.attempt(g, first)
        self.assertIsNone(reason)
        heavy.remove_file(self.heavy_dir("queue", "first.json"))
        held2, reason, _ = self.attempt(g, later)
        self.assertIsNone(reason)
        self.assertEqual(len(g._live_slots()), 2)
        g._release(held, first["token"])
        g._release(held2, later["token"])

    def test_second_sleeping_browser_does_not_relax_strict_slot_fifo(self):
        g = self.guard(level=1)
        self.ticket("browser1", kind="browser", created=1)
        second = self.ticket("browser2", kind="browser", created=2)
        third = self.ticket("test", kind="test", created=3)
        self.assertIn("earlier queued", self.attempt(g, second)[1])
        self.assertIn("earlier queued", self.attempt(g, third)[1])
        self.assertEqual(g._live_slots(), [])

    def test_final_fractional_poll_rereads_memory(self):
        calls = []
        def memory():
            calls.append(self.clock.mono)
            return heavy.Memory(level=4 if self.clock.mono < 0.25 else 2, free_pct=50)
        g = self.guard(reader=memory)
        self.assertEqual(g.run("test", [PY, "-c", "pass"], wait=0.5), 0)
        self.assertEqual(calls, [0, 0.5])

    def test_slot_blocked_browser_does_not_touch_kind_lock(self):
        self.hold("slot-1")
        g = self.guard(level=2)
        with patch.object(g.locks, "try_acquire", wraps=g.locks.try_acquire) as acquire:
            self.assertEqual(g.run("browser", [PY, "-c", "pass"], wait=1), heavy.EX_TEMPFAIL)
        self.assertNotIn("browser", [call.args[0] for call in acquire.call_args_list])

    def test_status_sweeps_dead_and_reused_waiting_records(self):
        g = self.guard(proc_identity=lambda _: "new")
        g._record("waiting", FAKE_DEAD, dict(guard=FAKE_DEAD, kind="test"))
        g._record("waiting", FAKE_LIVE, dict(guard=FAKE_LIVE, kind="test", identity="old"))
        g.status()
        self.assertEqual(g._records("waiting"), [])
        self.assertIn("waiting:   0", self.out.getvalue())

    def test_nested_browser_retains_floor_and_no_ticket(self):
        g = self.guard(free=13, env={heavy.env_name('HEAVY_HELD'): "1"})
        self.assertEqual(g.run("browser", [PY, "-c", "pass"], wait=0), heavy.EX_TEMPFAIL)
        self.assertIn("browser floor", self.err.getvalue())
        self.assert_empty_queue()
        self.assertFalse(g._live_slots())

    def test_already_paused_refuses_without_mutex_or_ticket(self):
        self.write_mode({"mode": "paused"})
        other = self.guard()
        g = self.guard()
        with other._admission():
            self.assertEqual(g.run("test", [PY, "-c", "pass"], wait=1), heavy.EX_TEMPFAIL)
        self.assertEqual(self.clock.sleeps, [])
        self.assertIn("paused", self.err.getvalue())
        self.assert_empty_queue()

    def test_mode_changed_at_admission_removes_ticket_without_rewrite(self):
        g = self.guard()
        states = iter((heavy.ModeState("continuous", heavy.Window.parse(heavy.DEFAULT_WINDOW)),
                       heavy.ModeState("paused", heavy.Window.parse(heavy.DEFAULT_WINDOW))))
        write = heavy.write_json_atomic
        tickets = []
        def observe(path, rec):
            if "/queue/" in path:
                tickets.append(dict(rec))
            return write(path, rec)
        with patch.object(g, "mode_state", side_effect=lambda: next(states)), \
             patch.object(heavy, "write_json_atomic", side_effect=observe):
            self.assertEqual(g.run("test", [PY, "-c", "pass"], wait=0), heavy.EX_TEMPFAIL)
        self.assertEqual([r["blocked_on"] for r in tickets], ["checking"])
        self.assert_empty_queue()

    def test_repeated_signal_during_owned_lock_cleanup_is_ignored(self):
        g = self.guard(level=2)
        acquire = g._acquire
        release = g.locks.release
        def interrupt_acquire(*args):
            result = acquire(*args)
            os.kill(os.getpid(), signal.SIGTERM)
            return result
        def interrupt_release(*args):
            os.kill(os.getpid(), signal.SIGHUP)
            return release(*args)
        with patch.object(g, "_acquire", side_effect=interrupt_acquire), \
             patch.object(g.locks, "release", side_effect=interrupt_release):
            self.assertEqual(g.run("browser", [PY, "-c", "pass"], wait=0), 143)
        self.assert_no_owned_resources(g)

    def test_signal_at_owner_publication_cleans_ownerless_directory(self):
        g = self.guard(level=2)
        write = heavy.write_json_atomic
        fired = []
        def interrupt(path, info):
            if path.endswith("/slot-1/owner.json") and not fired:
                fired.append(True)
                os.kill(os.getpid(), signal.SIGTERM)
            return write(path, info)
        with patch.object(heavy, "write_json_atomic", side_effect=interrupt):
            self.assertEqual(g.run("test", [PY, "-c", "pass"], wait=0), 143)
        self.assert_no_owned_resources(g)

    def test_signal_after_mkdir_before_return_cleans_immediately(self):
        g = self.guard(level=2)
        mkdir = heavy.os.mkdir
        fired = []
        def interrupt(path, *args, **kwargs):
            result = mkdir(path, *args, **kwargs)
            if str(path).endswith("/slot-1") and not fired:
                fired.append(True)
                os.kill(os.getpid(), signal.SIGTERM)
            return result
        with patch.object(heavy.os, "mkdir", side_effect=interrupt):
            self.assertEqual(g.run("test", [PY, "-c", "pass"], wait=0), 143)
        self.assert_no_owned_resources(g)

    def test_signal_during_post_slot_capacity_check_cleans_immediately(self):
        g = self.guard(level=2)
        live = g._live_slots
        fired = []
        def interrupt():
            result = live()
            if result and not fired:
                fired.append(True)
                os.kill(os.getpid(), signal.SIGTERM)
            return result
        with patch.object(g, "_live_slots", side_effect=interrupt):
            self.assertEqual(g.run("test", [PY, "-c", "pass"], wait=0), 143)
        self.assert_no_owned_resources(g)

    def test_signal_at_acquire_handoff_and_second_during_cleanup(self):
        for boundary in ("ticket", "return"):
            with self.subTest(boundary=boundary):
                g = self.guard(level=2)
                remove = heavy.remove_file
                acquire = g._acquire
                fired = []
                def interrupt_remove(path):
                    if path and "/queue/" in path and not fired:
                        fired.append(True)
                        os.kill(os.getpid(), signal.SIGTERM)
                    elif path and "/waiting/" in path and fired:
                        os.kill(os.getpid(), signal.SIGHUP)
                    return remove(path)
                def interrupt_return(*args):
                    result = acquire(*args)
                    os.kill(os.getpid(), signal.SIGTERM)
                    return result
                with patch.object(heavy, "remove_file", side_effect=interrupt_remove if boundary == "ticket" else remove), \
                     patch.object(g, "_acquire", side_effect=interrupt_return if boundary == "return" else acquire):
                    self.assertEqual(g.run("browser", [PY, "-c", "pass"], wait=0), 143)
                self.assert_no_owned_resources(g)


    def test_release_serializes_with_already_classified_ticket(self):
        holder = self.guard(level=2)
        holder.clock = heavy.Clock()
        rec = dict(pid=FAKE_LIVE, token="holder", kind="browser")
        held, _, _ = holder._attempt("browser", False, set(), rec)
        self.ticket("browser", kind="browser", created=1)
        later = self.ticket("test", created=2)
        observer = self.guard(level=2)
        attempted = threading.Event()
        finished = threading.Event()
        flock = heavy.fcntl.flock
        def observe_flock(fd, operation):
            if threading.current_thread() is worker and operation & heavy.fcntl.LOCK_EX:
                attempted.set()
            return flock(fd, operation)
        def release():
            try:
                holder._release(held, rec["token"])
            finally:
                finished.set()
        worker = threading.Thread(target=release)
        with patch.object(heavy.fcntl, "flock", side_effect=observe_flock):
            with observer._admission():
                self.assertEqual(observer._resource("browser", False, set(), observer.read_memory(), observer.mode_state()), "browser")
                worker.start()
                self.assertTrue(attempted.wait(2))
                self.assertFalse(finished.is_set(), "release ran through another guard's eligibility check")
                self.assertIsNotNone(observer._attempt("test", False, set(), later, observer._tickets())[1])
            worker.join(timeout=3)
        self.assertFalse(worker.is_alive())
        self.assertTrue(finished.is_set())
        self.assertEqual(holder._live_slots(), [])

    def test_status_reads_slots_kind_and_waiting_under_admission(self):
        g = self.guard()
        state = g.locks.state
        records = g._records
        def checked_state(name):
            self.assertGreater(g._admission_depth, 0)
            return state(name)
        def checked_records(sub):
            if sub in ("queue", "waiting"):
                self.assertGreater(g._admission_depth, 0)
            return records(sub)
        with patch.object(g.locks, "state", side_effect=checked_state), patch.object(g, "_records", side_effect=checked_records):
            self.assertEqual(g.status(), 0)

    def test_status_never_prints_while_holding_admission(self):
        g = self.guard()
        say = g._say
        def check(line):
            self.assertEqual(g._admission_depth, 0, "stdout can block; never print under admission")
            say(line)
        with patch.object(g, "_say", side_effect=check):
            self.assertEqual(g.status(), 0)

    def test_malformed_configuration_never_prints_under_admission(self):
        keys = (heavy.env_name('MAX_SLOTS'), heavy.env_name('MIN_FREE_PCT_BROWSER'), heavy.env_name('MIN_SWAP_FREE_MB_BROWSER'))
        warn, say = heavy.Guard._warn, heavy.Guard._say
        for operation in ("status", "run"):
            for key in keys:
                with self.subTest(operation=operation, setting=key):
                    warnings, lines = [], []
                    def checked_warn(g, message):
                        self.assertEqual(g._admission_depth, 0, "stderr can block under admission")
                        warnings.append(message)
                        return warn(g, message)
                    def checked_say(g, message):
                        self.assertEqual(g._admission_depth, 0, "stdout can block under admission")
                        lines.append(message)
                        return say(g, message)
                    with patch.object(heavy.Guard, "_warn", checked_warn), \
                         patch.object(heavy.Guard, "_say", checked_say):
                        g = self.guard(env={key: "invalid"})
                        if operation == "status":
                            self.assertEqual(g.status(), 0)
                            self.assertTrue(lines)
                        else:
                            self.assertEqual(g.run("browser", [PY, "-c", "pass"], wait=0), 0)
                    self.assertEqual(sum(key in message for message in warnings), 1)
                    self.assert_no_owned_resources(g)

    def test_signal_after_final_pending_check_never_starts_child(self):
        g = self.guard(level=2)
        sentinel, cmd = self.sentinel_cmd()
        check, popen = g._raise_pending, heavy.subprocess.Popen
        fired = []
        def interrupt_after_check():
            check()
            # Method boundary, independent of line numbers: admission has
            # handed ownership back to run and its final check just returned.
            if not g._admission_depth and g._live_slots() and not fired:
                fired.append(True)
                os.kill(os.getpid(), signal.SIGTERM)
        def child_runs_first(*args, **kwargs):
            child = popen(*args, **kwargs)
            try:
                child.wait(timeout=5)
            finally:
                if child.poll() is None:
                    child.kill()
                    child.wait(timeout=5)
            return child
        with patch.object(g, "_raise_pending", side_effect=interrupt_after_check), \
             patch.object(heavy.subprocess, "Popen", side_effect=child_runs_first) as spawn:
            rc = g.run("browser", cmd, wait=0)
        self.assertTrue(fired)
        self.assertEqual(rc, 143)
        spawn.assert_not_called()
        self.assertFalse(os.path.exists(sentinel))
        self.assert_no_owned_resources(g)

    def test_first_pending_signal_survives_end_of_acquisition_deferral(self):
        g = self.guard(level=2)
        acquire, check = g._acquire, g._raise_pending
        fired = []
        def first_signal(*args):
            held = acquire(*args)
            os.kill(os.getpid(), signal.SIGTERM)
            return held
        def second_signal():
            if g._pending is not None and not g._admission_depth and g._live_slots() and not fired:
                fired.append(True)
                os.kill(os.getpid(), signal.SIGHUP)
            return check()
        with patch.object(g, "_acquire", side_effect=first_signal), \
             patch.object(g, "_raise_pending", side_effect=second_signal), \
             patch.object(g, "_spawn") as spawn:
            self.assertEqual(g.run("browser", [PY, "-c", "pass"], wait=0), 143)
        self.assertTrue(fired)
        spawn.assert_not_called()
        self.assert_no_owned_resources(g)

    def test_refusal_waiting_record_cleanup_finishes_before_deferral_ends(self):
        self.write_mode({"mode": "paused"})
        g = self.guard()
        remove = heavy.remove_file
        fired = []
        def interrupt_remove(path):
            if path and "/waiting/" in path and not fired:
                fired.append(True)
                os.kill(os.getpid(), signal.SIGTERM)
            return remove(path)
        with patch.object(heavy, "remove_file", side_effect=interrupt_remove), \
             patch.object(g, "_spawn") as spawn:
            self.assertEqual(g.run("test", [PY, "-c", "pass"], wait=0), 143)
        self.assertTrue(fired)
        spawn.assert_not_called()
        self.assert_no_owned_resources(g)

    def test_publication_exception_removes_our_new_directory(self):
        g = self.guard()
        with patch.object(heavy, "write_json_atomic", side_effect=heavy._Interrupted(signal.SIGTERM)):
            with self.assertRaises(heavy._Interrupted):
                g.locks.try_acquire("slot-1", dict(pid=FAKE_LIVE, token="ours"))
        self.assertFalse(os.path.exists(self.heavy_dir("slot-1")))

    def test_pending_signal_during_admission_mutex_wait_stops_promptly(self):
        g = self.guard(level=2)
        other = self.guard(level=2)
        self.clock.on_sleep = lambda _: os.kill(os.getpid(), signal.SIGTERM)
        with other._admission():
            self.assertEqual(g.run("test", [PY, "-c", "pass"], wait=10), 143)
        self.assertLessEqual(sum(self.clock.sleeps), 0.05)
        self.assert_no_owned_resources(g)

    def test_signal_interrupts_wait_diagnostic_before_blocked_output(self):
        self.hold("slot-1")
        g = self.guard(level=2)
        warn = g._warn
        def output(message):
            if " is waiting:" in message:
                os.kill(os.getpid(), signal.SIGTERM)
                self.fail("signal was deferred into potentially blocking output")
            return warn(message)
        with patch.object(g, "_warn", side_effect=output):
            self.assertEqual(g.run("test", [PY, "-c", "pass"], wait=10), 143)
        self.assert_empty_queue()
        self.assertEqual(g._records("waiting"), [])

    def test_second_browser_reason_propagates_kind_reservation(self):
        g = self.guard(level=1)
        self.ticket("first", kind="browser", created=1)
        second = self.ticket("second", kind="browser", created=2)
        self.assertIn("waiting for browser", self.attempt(g, second)[1])


class IdentityReviewTests(GuardCase):
    def test_native_identity_ignores_timezone_and_linux_realtime(self):
        if not (sys.platform == "darwin" or sys.platform.startswith("linux")):
            self.skipTest("native immutable process identity is macOS/Linux only")
        identity = heavy.default_proc_identity(os.getpid())
        self.assertTrue(identity)
        with patch.object(heavy.time, "localtime", side_effect=AssertionError("used timezone")), \
             patch.object(heavy.subprocess, "run", side_effect=AssertionError("spawned ps")):
            self.assertEqual(heavy.default_proc_identity(os.getpid()), identity)
        # Linux procfs fixture has a process name containing ')', and no btime
        # is readable. Identity uses only immutable boot ID and start ticks.
        reads = []
        def procfs(path, *args, **kwargs):
            reads.append(path)
            if path == "/proc/42/stat":
                return io.StringIO("42 (name with ) paren) " + " ".join(["0"] * 19 + ["12345"]))
            if path == "/proc/sys/kernel/random/boot_id":
                return io.StringIO("boot-token\n")
            raise AssertionError(f"mutable clock source read: {path}")
        with patch.object(heavy.sys, "platform", "linux"), patch("builtins.open", side_effect=procfs):
            self.assertEqual(heavy.default_proc_identity(42), "linux:boot-token:12345")
        self.assertNotIn("/proc/stat", reads)

    def test_darwin_identity_includes_birth_microseconds(self):
        micros = [1]
        class Libproc:
            @staticmethod
            def proc_pidinfo(pid, flavor, argument, buf, length):
                heavy.ctypes.c_uint64.from_buffer(buf, 120).value = 123456
                heavy.ctypes.c_uint64.from_buffer(buf, 128).value = micros[0]
                return length
        with patch.object(heavy.sys, "platform", "darwin"), patch.object(heavy, "_LIBPROC", Libproc()):
            first = heavy.default_proc_identity(42)
            micros[0] = 2
            second = heavy.default_proc_identity(42)
        self.assertEqual(first, "darwin:123456:1")
        self.assertEqual(second, "darwin:123456:2")

    def test_strong_identity_detects_reuse_for_locks_tickets_and_waiting(self):
        table = {FAKE_LIVE: "birth-new", FAKE_LIVE_2: None}
        g = self.guard(proc_identity=lambda pid: table.get(pid))
        path = self.hold("slot-1")
        self.set_owner(path, identity="birth-old")
        self.assertEqual(g.locks.state("slot-1"), "stale")
        g._record("queue", FAKE_LIVE, dict(pid=FAKE_LIVE, identity="birth-old", token="reuse", kind="test"))
        g._record("waiting", FAKE_LIVE, dict(guard=FAKE_LIVE, identity="birth-old", kind="test"))
        g._record("waiting", FAKE_LIVE_2, dict(guard=FAKE_LIVE_2, identity="birth-unknown", kind="test"))
        g.status()
        self.assertEqual(g._records("queue"), [])
        self.assertEqual([r["guard"] for _, r in g._records("waiting")], [FAKE_LIVE_2])

    def test_legacy_cross_timezone_and_clock_changes_keep_capacity(self):
        for recorded, current in (("Sun Oct 18 12:00:00 2026", "Sun Oct 18 07:00:00 2026"),
                                  ("Sun Oct 18 12:00:00 2026", "Sun Oct 18 12:00:01 2026")):
            with self.subTest(recorded=recorded, current=current):
                g = self.guard(proc_start=lambda _: current, proc_identity=lambda _: "new-birth")
                for name in ("slot-1", "browser", "codex"):
                    path = self.hold(name)
                    self.set_owner(path, lstart=recorded)
                    self.assertEqual(g.locks.state(name), "live")
                    g.locks.release(name, "other")
                g._record("queue", FAKE_LIVE, dict(pid=FAKE_LIVE, lstart=recorded, token="old", kind="test"))
                g._record("waiting", FAKE_LIVE, dict(guard=FAKE_LIVE, lstart=recorded, kind="test"))
                with g._admission():
                    self.assertEqual(len(g._tickets()), 1)
                g.status()
                self.assertEqual(len(g._records("waiting")), 1)

    def test_new_lock_omits_legacy_timestamps_for_old_readers(self):
        g = self.guard(level=2, proc_identity=lambda pid: f"birth:{pid}")
        held_info = []
        def inspect(kind, cmd, env, held, info, nested):
            for name in held:
                owner = g.locks.owner(name)
                held_info.append(owner)
                self.assertNotIn("lstart", owner)
                self.assertNotIn("pgid_lstart", owner)
                # This is exactly the pre-queue/v2 _not_reused rule. Across
                # any TZ, an absent legacy timestamp conservatively keeps it.
                legacy = heavy.Locks(g.heavy_dir, self.pid_alive, self.group_alive, lambda _: "different TZ")
                self.assertTrue(legacy._not_reused(owner["pid"], owner.get("lstart")))
            for _, ticket in g._records("queue"):
                self.assertNotIn("lstart", ticket)
            for _, waiting in g._records("waiting"):
                self.assertNotIn("lstart", waiting)
            return 0
        with patch.object(g, "_spawn", side_effect=inspect):
            self.assertEqual(g.run("browser", [PY, "-c", "pass"], wait=0), 0)
        self.assertEqual(len(held_info), 2)

    def test_stop_all_rejects_strong_reuse_even_when_guard_and_argv_match(self):
        g = self.guard(proc_identity=lambda _: "birth-new", proc_command=lambda _: "python heavy.py")
        g._record("waiting", FAKE_LIVE, dict(guard=FAKE_LIVE, identity="birth-old", kind="test"))
        g._record("running", FAKE_LIVE_2, dict(pid=FAKE_LIVE_2, pgid=FAKE_LIVE_2, guard=FAKE_LIVE,
                                                   identity="birth-old", argv0="python", kind="test"))
        with patch.object(heavy.os, "kill") as kill, patch.object(heavy.os, "killpg") as killpg:
            g.stop_all(grace=0)
        kill.assert_not_called()
        killpg.assert_not_called()

    def test_stop_all_legacy_timestamp_mismatch_does_not_fall_back_to_argv(self):
        g = self.guard(proc_start=lambda _: "different TZ", proc_command=lambda _: "python")
        g._record("waiting", FAKE_LIVE, dict(guard=FAKE_LIVE, lstart="old", kind="test"))
        g._record("running", FAKE_LIVE_2, dict(pid=FAKE_LIVE_2, pgid=FAKE_LIVE_2, guard=FAKE_DEAD,
                                                   lstart="old", argv0="python", kind="test"))
        with patch.object(heavy.os, "kill") as kill, patch.object(heavy.os, "killpg") as killpg:
            g.stop_all(grace=0)
        kill.assert_not_called()
        killpg.assert_not_called()



    def test_stop_all_missing_child_identity_rejects_reused_guard_identity(self):
        for current in ("birth-reused", None):
            with self.subTest(current=current):
                g = self.guard(proc_identity=lambda _: current, proc_command=lambda _: "python heavy.py")
                g._record("running", FAKE_LIVE_2, dict(pid=FAKE_LIVE_2, pgid=FAKE_LIVE_2,
                    guard=FAKE_LIVE, guard_identity="guard-original", argv0="python", kind="test"))
                with patch.object(heavy.os, "killpg") as killpg:
                    g.stop_all(grace=0)
                killpg.assert_not_called()

    def test_stop_all_rechecks_identity_before_escalating(self):
        identity = ["birth-original"]
        g = self.guard(proc_identity=lambda _: identity[0], proc_command=lambda _: "python heavy.py")
        g._record("running", FAKE_LIVE, dict(pid=FAKE_LIVE, pgid=FAKE_LIVE, guard=FAKE_DEAD,
                                              identity="birth-original", kind="test"))
        self.clock.on_sleep = lambda _: identity.__setitem__(0, "birth-reused")
        with patch.object(heavy.os, "killpg") as killpg:
            g.stop_all(grace=0.2)
        self.assertEqual(killpg.call_args_list, [unittest.mock.call(FAKE_LIVE, signal.SIGTERM)])



class ReaderTests(unittest.TestCase):
    def test_parse_swapusage(self):
        total, free = heavy.parse_swapusage(
            "total = 15360.00M  used = 14058.50M  free = 1301.50M  (encrypted)")
        self.assertAlmostEqual(total, 15360.0)
        self.assertAlmostEqual(free, 1301.5)
        total, free = heavy.parse_swapusage("total = 2.00G  used = 1.50G  free = 512.00M")
        self.assertAlmostEqual(total, 2048.0)
        self.assertAlmostEqual(free, 512.0)
        self.assertEqual(heavy.parse_swapusage(""), (None, None))

    def test_read_darwin(self):
        answers = {"kern.memorystatus_vm_pressure_level": "2", "kern.memorystatus_level": "16",
                   "vm.swapusage": "total = 1024.00M  used = 512.00M  free = 512.00M  (encrypted)"}
        mem = heavy.read_darwin(answers.get)
        self.assertEqual((mem.level, mem.free_pct, mem.swap_free_mb), (2, 16.0, 512.0))
        self.assertTrue(mem.swap_dynamic)
        mem = heavy.read_darwin(lambda key: None)
        self.assertEqual((mem.level, mem.free_pct, mem.swap_total_mb), (None, None, None))

    def test_parse_meminfo(self):
        text = ("MemTotal:       16000000 kB\nMemFree:         1000000 kB\n"
                "MemAvailable:    4000000 kB\nSwapTotal:       2097152 kB\nSwapFree:        1048576 kB\n")
        mem = heavy.parse_meminfo(text)
        self.assertAlmostEqual(mem.free_pct, 25.0)
        self.assertEqual(mem.level, heavy.LEVEL_NORMAL)
        self.assertAlmostEqual(mem.swap_total_mb, 2048.0)
        self.assertAlmostEqual(mem.swap_free_mb, 1024.0)

    def test_linux_levels(self):
        self.assertEqual(heavy.level_from_free_pct(40), heavy.LEVEL_NORMAL)
        self.assertEqual(heavy.level_from_free_pct(10), heavy.LEVEL_WARN)
        self.assertEqual(heavy.level_from_free_pct(3), heavy.LEVEL_CRITICAL)
        self.assertIsNone(heavy.level_from_free_pct(None))

    def test_reader_by_platform(self):
        self.assertIs(heavy.default_reader("darwin"), heavy.read_darwin)
        self.assertIs(heavy.default_reader("linux"), heavy.read_linux)
        self.assertIsNone(heavy.default_reader("plan9")().level)

    def test_unreadable_meminfo(self):
        self.assertIsNone(heavy.read_linux("/nonexistent/meminfo").level)


class MaxrssTests(unittest.TestCase):
    def test_normalization(self):
        self.assertEqual(heavy.normalize_maxrss(2048 * 1024, "darwin"), 2048)  # bytes
        self.assertEqual(heavy.normalize_maxrss(2048, "linux"), 2048)  # kilobytes


class RunTests(GuardCase):
    def test_runs_command_and_returns_its_exit_code(self):
        g = self.guard()
        self.assertEqual(g.run("test", [PY, "-c", "import sys; sys.exit(3)"]), 3)
        self.assertEqual(self.guard().run("test", [PY, "-c", "pass"]), 0)

    def test_signal_death_maps_to_128_plus_n(self):
        rc = self.guard().run("test", [PY, "-c", "import os, signal; os.kill(os.getpid(), signal.SIGTERM)"])
        self.assertEqual(rc, 128 + signal.SIGTERM)

    def test_signal_during_memory_read_is_not_swallowed(self):
        # stop-all's SIGTERM can land while a waiting guard reads the sysctls.
        # The reader is wrapped in `except Exception`, which must not eat it.
        def reader():
            os.kill(os.getpid(), signal.SIGTERM)  # the guard's handler raises here
            time.sleep(5)
            return heavy.Memory(level=1)
        path, cmd = self.sentinel_cmd()
        g = self.guard(reader=reader)
        self.assertEqual(g.run("test", cmd, wait=0), 128 + signal.SIGTERM)
        self.assertFalse(os.path.exists(path))
        self.assertEqual(os.listdir(self.heavy_dir("waiting")), [])
        self.assertFalse([n for n in os.listdir(self.heavy_dir()) if n.startswith("slot-")])

    def test_command_not_found(self):
        rc = self.guard().run("test", ["/nonexistent/definitely-not-a-command"])
        self.assertEqual(rc, 127)

    def test_usage_errors(self):
        self.assertEqual(self.guard().run("test", []), heavy.EX_USAGE)
        self.assertEqual(self.guard().run("huge", ["true"]), heavy.EX_USAGE)

    def test_paused_refuses_with_75_and_does_not_run(self):
        self.write_mode({"mode": "paused"})
        path, cmd = self.sentinel_cmd()
        g = self.guard()
        self.assertEqual(g.run("test", cmd), heavy.EX_TEMPFAIL)
        self.assertFalse(os.path.exists(path))
        lines = self.err.getvalue().strip().splitlines()
        self.assertEqual(len(lines), 1)
        self.assertIn("paused", lines[0])
        self.assertEqual(self.clock.sleeps, [])  # mode refusals do not wait
        entry = self.log_entries()[-1]
        self.assertEqual(entry["rc"], heavy.EX_TEMPFAIL)
        self.assertIn("paused", entry["refused"])

    def test_light_runs_in_paused_mode(self):
        self.write_mode({"mode": "paused"})
        path, cmd = self.sentinel_cmd()
        self.assertEqual(self.guard().run("light", cmd), 0)
        self.assertTrue(os.path.exists(path))

    def test_nightshift_outside_window_refuses(self):
        self.write_mode({"mode": "nightshift", "window": "22:00-06:00"})
        path, cmd = self.sentinel_cmd()
        self.assertEqual(self.guard().run("build", cmd), heavy.EX_TEMPFAIL)
        self.assertFalse(os.path.exists(path))
        self.clock = FakeClock(at(1))
        self.assertEqual(self.guard().run("build", cmd), 0)
        self.assertTrue(os.path.exists(path))

    def test_slots_full_refuses_with_75(self):
        self.hold("slot-1")
        path, cmd = self.sentinel_cmd()
        g = self.guard(level=2)  # warn: one slot, already taken
        self.assertEqual(g.run("test", cmd, wait=0), heavy.EX_TEMPFAIL)
        self.assertFalse(os.path.exists(path))
        self.assertIn("busy at warn pressure", self.err.getvalue())

    def test_second_slot_at_normal_pressure(self):
        self.hold("slot-1")
        g = self.guard(level=1)
        self.assertEqual(g.run("test", [PY, "-c", "pass"], wait=0), 0)
        self.assertTrue(os.path.isdir(self.heavy_dir("slot-1")))  # the other holder keeps its slot
        self.assertFalse(os.path.exists(self.heavy_dir("slot-2")))  # ours is released

    def test_holders_beyond_capacity_still_count(self):
        # Two jobs got slots while capacity was higher; pressure then rose to warn.
        self.hold("slot-2")
        self.hold("slot-3", pid=FAKE_LIVE_2)
        g = self.guard(level=1)  # capacity 2, both taken
        self.assertEqual(g.run("test", [PY, "-c", "pass"], wait=0), heavy.EX_TEMPFAIL)

    def test_critical_pressure_allows_nothing_heavy(self):
        g = self.guard(level=4)
        self.assertEqual(g.run("test", [PY, "-c", "pass"], wait=0), heavy.EX_TEMPFAIL)
        self.assertIn("critical", self.err.getvalue())
        self.assertEqual(self.guard(level=4).run("light", [PY, "-c", "pass"], wait=0), 0)

    def test_waits_with_fixed_polling_then_gives_up(self):
        self.hold("slot-1")
        g = self.guard(level=2)
        self.assertEqual(g.run("test", [PY, "-c", "pass"], wait=100), heavy.EX_TEMPFAIL)
        self.assertGreater(len(self.clock.sleeps), 2)
        self.assertAlmostEqual(sum(self.clock.sleeps), 100.0, places=6)
        self.assertTrue(all(delay == heavy.POLL_INTERVAL for delay in self.clock.sleeps))
        self.assertIn("gave up after waiting", self.err.getvalue())
        # One "waiting" line (the reason never changed) plus one refusal line.
        self.assertEqual(len(self.err.getvalue().strip().splitlines()), 2)
        self.assertFalse(os.listdir(self.heavy_dir("waiting")))

    def test_waits_until_slot_frees(self):
        holder = self.hold("slot-1")
        path, cmd = self.sentinel_cmd()

        def free_after_two(n):
            if n == 2:
                self.fake_live.discard(FAKE_LIVE)  # holder exits; its lock is now stale
        self.clock.on_sleep = free_after_two
        g = self.guard(level=2)
        self.assertEqual(g.run("test", cmd, wait=600), 0)
        self.assertTrue(os.path.exists(path))
        self.assertEqual(len(self.clock.sleeps), 2)
        self.assertFalse(os.path.exists(holder))

    def test_mode_change_while_waiting_refuses(self):
        self.hold("slot-1")

        def pause(n):
            self.write_mode({"mode": "paused"})
        self.clock.on_sleep = pause
        g = self.guard(level=2)
        self.assertEqual(g.run("test", [PY, "-c", "pass"], wait=600), heavy.EX_TEMPFAIL)
        self.assertEqual(len(self.clock.sleeps), 1)
        self.assertIn("paused", self.err.getvalue())

    def test_stale_lock_is_recovered(self):
        holder = self.hold("slot-1", pid=FAKE_DEAD)
        path, cmd = self.sentinel_cmd()
        g = self.guard(level=2)
        self.assertEqual(g.run("test", cmd, wait=0), 0)
        self.assertTrue(os.path.exists(path))
        self.assertFalse(os.path.exists(holder))
        self.assertFalse(os.path.exists(holder + ".break"))

    def test_lock_alive_through_its_process_group(self):
        # The guard was killed but the command's process group lives on.
        path = self.hold("slot-1", pid=FAKE_DEAD)
        with open(os.path.join(path, heavy.OWNER_FILE)) as fh:
            info = json.load(fh)
        info["pgid"] = FAKE_LIVE
        with open(os.path.join(path, heavy.OWNER_FILE), "w") as fh:
            json.dump(info, fh)
        self.assertEqual(self.guard(level=2).run("test", [PY, "-c", "pass"], wait=0), heavy.EX_TEMPFAIL)

    def starts(self, table):
        """A proc_start that answers from table for fake pids and asks ps for real ones."""
        return lambda pid: table[pid] if pid in table else heavy.default_proc_start(pid)

    def test_lock_whose_pid_was_reused_is_stale(self):
        # The guard was killed and an unrelated long-lived process got its pid.
        path = self.hold("slot-1", pid=FAKE_LIVE)
        self.set_owner(path, identity="old-birth")
        g = self.guard(level=2, proc_identity=lambda pid: "new-birth" if pid == FAKE_LIVE else heavy.default_proc_identity(pid))
        self.assertEqual(g.run("test", [PY, "-c", "pass"], wait=0), 0)
        self.assertFalse(os.path.exists(path))

    def test_lock_with_matching_or_unreadable_start_is_kept(self):
        path = self.hold("slot-1", pid=FAKE_LIVE)
        self.set_owner(path, lstart="Thu Oct  1 01:00:00 2026")
        for answer in ("Thu Oct  1 01:00:00 2026", None):
            g = self.guard(level=2, proc_start=self.starts({FAKE_LIVE: answer}))
            self.assertEqual(g.run("test", [PY, "-c", "pass"], wait=0), heavy.EX_TEMPFAIL, answer)
            self.assertTrue(os.path.isdir(path))

    def test_reused_process_group_does_not_keep_the_lock(self):
        path = self.hold("slot-1", pid=FAKE_DEAD)
        self.set_owner(path, pgid=FAKE_LIVE, pgid_identity="old-birth")
        g = self.guard(level=2, proc_identity=lambda pid: "old-birth" if pid == FAKE_LIVE else heavy.default_proc_identity(pid))
        self.assertEqual(g.run("test", [PY, "-c", "pass"], wait=0), heavy.EX_TEMPFAIL)
        g = self.guard(level=2, proc_identity=lambda pid: "new-birth" if pid == FAKE_LIVE else heavy.default_proc_identity(pid))
        self.assertEqual(g.run("test", [PY, "-c", "pass"], wait=0), 0)
        self.assertFalse(os.path.exists(path))

    def test_owner_records_start_times(self):
        out = os.path.join(self.tmp, "owner.json")
        owner = os.path.join(self.heavy_dir("slot-1"), heavy.OWNER_FILE)
        # The child waits until the guard has added its process group to the lock.
        child = (
            "import json, time\n"
            "deadline = time.time() + 20\n"
            "while True:\n"
            f"    with open({owner!r}) as fh:\n"
            "        info = json.load(fh)\n"
            "    if 'pgid_identity' in info or time.time() > deadline:\n"
            "        break\n"
            "    time.sleep(0.05)\n"
            f"with open({out!r}, 'w') as fh:\n"
            "    json.dump(info, fh)\n"
        )
        g = self.guard(level=2, proc_identity=lambda pid: f"birth-{pid}")
        self.assertEqual(g.run("test", [PY, "-c", child], wait=0), 0)
        with open(out) as fh:
            info = json.load(fh)
        self.assertEqual(info["identity"], f"birth-{os.getpid()}")
        self.assertEqual(info["pgid_identity"], f"birth-{info['pgid']}")
        self.assertNotIn("lstart", info)
        self.assertNotIn("pgid_lstart", info)

    def test_lock_without_owner_file(self):
        fresh = self.heavy_dir("slot-1")
        os.makedirs(fresh)
        self.assertEqual(self.guard(level=2).run("test", [PY, "-c", "pass"], wait=0), heavy.EX_TEMPFAIL)
        old = time.time() - heavy.FRESH_LOCK_GRACE - 5
        os.utime(fresh, (old, old))
        self.assertEqual(self.guard(level=2).run("test", [PY, "-c", "pass"], wait=0), 0)

    def test_release_keeps_a_lock_someone_else_owns(self):
        locks = heavy.Locks(self.heavy_dir(), self.pid_alive, self.group_alive)
        self.hold("codex", kind="codex")
        locks.release("codex", "not-the-owner-token")
        self.assertTrue(os.path.isdir(self.heavy_dir("codex")))

    def test_locks_released_and_records_removed(self):
        g = self.guard(level=1)
        self.assertEqual(g.run("browser", [PY, "-c", "pass"], wait=0), 0)
        self.assertEqual(sorted(os.listdir(self.heavy_dir())), ["admission.lock", "queue", "running", "waiting"])
        self.assertEqual(os.listdir(self.heavy_dir("running")), [])
        self.assertEqual(os.listdir(self.heavy_dir("waiting")), [])

    def test_child_env_defaults_and_markers(self):
        out = os.path.join(self.tmp, "env.json")
        cmd = [PY, "-c", f"import json, os; json.dump(dict(os.environ), open({out!r}, 'w'))"]
        g = self.guard(env={"GOMAXPROCS": "2", "GOMEMLIMIT": ""})
        self.assertEqual(g.run("browser", cmd, wait=0), 0)
        with open(out) as fh:
            env = json.load(fh)
        self.assertEqual(env["NODE_OPTIONS"], "--max-old-space-size=1536")
        self.assertEqual(env["GOMEMLIMIT"], "768MiB")  # empty counts as unset
        self.assertEqual(env["GOMAXPROCS"], "2")  # set values are kept
        self.assertEqual(env["GOFLAGS"], "-p=2")
        self.assertEqual(env[heavy.env_name('HEAVY_HELD')], "1")
        self.assertEqual(env[heavy.env_name('HEAVY_KIND')], "browser")
        self.assertEqual(env[heavy.env_name('HEAVY_LOCKS')], "browser")

    def test_multi_flag_variables_get_missing_caps_appended(self):
        g = self.guard(env={"NODE_OPTIONS": "--unhandled-rejections=strict", "GOFLAGS": "-mod=mod"})
        env = g.child_env("build", True, set())
        self.assertEqual(env["NODE_OPTIONS"], "--unhandled-rejections=strict --max-old-space-size=1536")
        self.assertEqual(env["GOFLAGS"], "-mod=mod -p=2")
        g = self.guard(env={"NODE_OPTIONS": "--max-old-space-size=3096 --x", "GOFLAGS": "-p=4"})
        env = g.child_env("build", True, set())
        self.assertEqual(env["NODE_OPTIONS"], "--max-old-space-size=3096 --x")  # explicit cap kept
        self.assertEqual(env["GOFLAGS"], "-p=4")

    def test_light_child_is_not_marked_held(self):
        out = os.path.join(self.tmp, "env.json")
        cmd = [PY, "-c", f"import json, os; json.dump(dict(os.environ), open({out!r}, 'w'))"]
        self.assertEqual(self.guard().run("light", cmd), 0)
        with open(out) as fh:
            env = json.load(fh)
        self.assertNotIn(heavy.env_name('HEAVY_HELD'), env)
        self.assertEqual(env[heavy.env_name('HEAVY_KIND')], "light")

    def test_fuzz_runs_niced(self):
        out = os.path.join(self.tmp, "nice")
        cmd = [PY, "-c", f"import os; open({out!r}, 'w').write(str(os.nice(0)))"]
        self.assertEqual(self.guard().run("fuzz", cmd), 0)
        with open(out) as fh:
            self.assertGreaterEqual(int(fh.read()), min(os.nice(0) + 10, 19))

    def test_log_line(self):
        g = self.guard()
        g.run("test", [PY, "-c", "x = bytearray(30 * 1024 * 1024)"])
        entry = self.log_entries()[-1]
        for key in ("ts", "kind", "cmd", "rc", "secs", "maxrss_kb"):
            self.assertIn(key, entry)
        self.assertEqual((entry["kind"], entry["rc"]), ("test", 0))
        self.assertIsInstance(entry["maxrss_kb"], int)
        self.assertGreater(entry["maxrss_kb"], 30 * 1024)  # the 30 MB buffer, in KB
        self.assertLess(entry["maxrss_kb"], 4 * 1024 * 1024)  # not bytes mistaken for KB
        self.assertIn("bytearray", entry["cmd"])

    def test_log_line_maxrss_ignores_injected_platform(self):
        """The ru_maxrss unit is fixed by the real kernel the test runs under,
        not by Guard's injectable `platform` (which only picks a fake memory
        reader elsewhere in this suite). Pin it to the opposite of the real
        host and confirm the logged value is still correct either way: this
        is the regression that let darwin-vs-linux unit confusion pass on
        one OS and fail on the other."""
        other = "linux" if sys.platform != "linux" else "darwin"
        g = self.guard(platform=other)
        g.run("test", [PY, "-c", "x = bytearray(30 * 1024 * 1024)"])
        entry = self.log_entries()[-1]
        self.assertGreater(entry["maxrss_kb"], 30 * 1024)
        self.assertLess(entry["maxrss_kb"], 4 * 1024 * 1024)


class NestedTests(GuardCase):
    def test_nested_run_takes_no_slot(self):
        self.hold("slot-1")
        path, cmd = self.sentinel_cmd()
        g = self.guard(level=2, env={heavy.env_name('HEAVY_HELD'): "1"})
        self.assertEqual(g.run("test", cmd, wait=0), 0)
        self.assertTrue(os.path.exists(path))
        self.assertEqual(self.heavy_slots(), ["slot-1"])
        self.assertTrue(self.log_entries()[-1]["nested"])

    def heavy_slots(self):
        return sorted(n for n in os.listdir(self.heavy_dir()) if n.startswith("slot-"))

    def test_nested_run_skips_mode_gate(self):
        self.write_mode({"mode": "paused"})
        g = self.guard(env={heavy.env_name('HEAVY_HELD'): "1"})
        self.assertEqual(g.run("build", [PY, "-c", "pass"], wait=0), 0)

    def test_nested_run_does_not_need_memory_readings(self):
        calls = []

        def reader():
            calls.append(1)
            return heavy.Memory(level=4)
        g = self.guard(env={heavy.env_name('HEAVY_HELD'): "1"}, reader=reader)
        self.assertEqual(g.run("test", [PY, "-c", "pass"], wait=0), 0)
        self.assertEqual(calls, [])

    def test_nested_browser_uses_inherited_lock(self):
        self.hold("browser", kind="browser")
        g = self.guard(env={heavy.env_name('HEAVY_HELD'): "1", heavy.env_name('HEAVY_LOCKS'): "browser"})
        self.assertEqual(g.run("browser", [PY, "-c", "pass"], wait=0), 0)

    def test_nested_browser_without_the_lock_must_take_it(self):
        self.hold("browser", kind="browser")
        g = self.guard(env={heavy.env_name('HEAVY_HELD'): "1"})
        self.assertEqual(g.run("browser", [PY, "-c", "pass"], wait=0), heavy.EX_TEMPFAIL)
        self.assertIn("browser lock is held", self.err.getvalue())

    def test_held_zero_is_not_nested(self):
        self.hold("slot-1")
        g = self.guard(level=2, env={heavy.env_name('HEAVY_HELD'): "0"})
        self.assertEqual(g.run("test", [PY, "-c", "pass"], wait=0), heavy.EX_TEMPFAIL)


class CIModeTests(GuardCase):
    def test_ci_without_run_dir_is_continuous_with_linux_readers(self):
        missing = os.path.join(self.tmp, "absent")
        g = heavy.Guard(env={"CI": "true", heavy.env_name('RUN_DIR'): missing, "RUNNER_TEMP": self.tmp,
                             "HOME": self.tmp, "PATH": os.environ.get("PATH", "")},
                        platform="darwin", clock=self.clock,
                        stdout=io.StringIO(), stderr=io.StringIO())
        self.assertTrue(g.ci_mode)
        self.assertEqual(g.reader_platform, "linux")
        self.assertEqual(g.mode_state().mode, "continuous")
        self.assertTrue(g.run_dir.startswith(self.tmp))
        self.assertEqual(g.run("test", [PY, "-c", "pass"], wait=0), 0)
        self.assertFalse(os.path.exists(missing))

    def test_ci_with_existing_run_dir_uses_it(self):
        self.write_mode({"mode": "paused"})
        g = self.guard(env={"CI": "true"})
        self.assertFalse(g.ci_mode)
        self.assertEqual(g.mode_state().mode, "paused")


class StatusTests(GuardCase):
    def test_status_lists_everything(self):
        self.write_mode({"mode": "nightshift", "window": "22:00-06:00"})
        self.clock = FakeClock(at(23, 15))
        self.hold("slot-1", cmd="go test ./...")
        self.hold("slot-2", pid=FAKE_DEAD)
        g = self.guard(level=2, free=16, swap_total=13312, swap_free=816)
        g.run("light", [PY, "-c", "pass"])
        self.assertEqual(g.status(), 0)
        text = self.out.getvalue()
        for needle in ("mode:      nightshift", "window:    22:00-06:00", "in window: yes",
                       "pressure:  warn (level 2)", "free mem:  16%", "816 MB free of 13312 MB",
                       "capacity 1 (warn pressure, nightshift window), 1 held",
                       "go test ./...", "stale", "browser:", "codex:", "recent:"):
            self.assertIn(needle, text)

    def test_status_with_unknown_pressure(self):
        g = self.guard(reader=lambda: heavy.Memory())
        self.assertEqual(g.status(), 0)
        self.assertIn("unknown (treated as warn)", self.out.getvalue())
        self.assertIn("capacity 1", self.out.getvalue())


class ProcessTests(GuardCase):
    """Real processes: signal forwarding and stop-all."""

    def env(self, **extra):
        env = clean_environ()
        env[heavy.env_name('RUN_DIR')] = self.run_dir
        env.update(extra)
        return env

    def wait_for_file(self, path, timeout=15.0):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if os.path.exists(path) and os.path.getsize(path) > 0:
                return
            time.sleep(0.05)
        self.fail(f"timed out waiting for {path}")

    def assert_gone(self, pid, timeout=10.0):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if not heavy.default_pid_alive(pid):
                return
            time.sleep(0.05)
        os.kill(pid, signal.SIGKILL)
        self.fail(f"pid {pid} still alive")

    def sleeper_cmd(self, pidfile):
        return [PY, "-c", f"import os, time; open({pidfile!r}, 'w').write(str(os.getpid())); time.sleep(60)"]

    def spawn_orphan(self, pidfile):
        """Start a sleeper in its own session whose parent exits at once.

        init then reaps it when it dies, as happens to real jobs (whose guard
        or shell reaps them). A child of this test process would linger as a
        zombie, and a zombie still answers kill(pid, 0).
        """
        launcher = ("import subprocess, sys; "
                    "subprocess.Popen(sys.argv[1:], start_new_session=True)")
        subprocess.run([PY, "-c", launcher] + self.sleeper_cmd(pidfile), check=True, timeout=30)
        self.wait_for_file(pidfile)
        with open(pidfile) as fh:
            pid = int(fh.read())
        self.addCleanup(self.kill_quietly, pid)
        return pid

    @staticmethod
    def kill_quietly(pid):
        if heavy.default_pid_alive(pid):
            os.kill(pid, signal.SIGKILL)

    def test_real_five_process_fifo_capacity_one(self):
        self.hold("slot-1", pid=os.getpid())
        events = os.path.join(self.tmp, "events.jsonl")
        children = []
        env = self.env(**{heavy.env_name('MAX_SLOTS'): "1"})
        try:
            for index in range(5):
                code = ("import json, os, time; "
                        f"f=open({events!r}, 'a', buffering=1); "
                        f"f.write(json.dumps([{index}, 'start', time.monotonic()])+'\\n'); "
                        "time.sleep(0.2); "
                        f"f.write(json.dumps([{index}, 'end', time.monotonic()])+'\\n')")
                child = subprocess.Popen([PY, HEAVY_PATH, "run", "--kind", "test", "--wait", "30", "--", PY, "-c", code],
                                         env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                children.append(child)
                deadline = time.monotonic() + 10
                while time.monotonic() < deadline:
                    recs = heavy.Guard(env=env)._records("queue")
                    if len(recs) == index + 1 and all(r.get("blocked_on") == "slots" for _, r in recs):
                        break
                    time.sleep(0.02)
                else:
                    self.fail("waiters did not publish ordered tickets")
            heavy.Guard(env=env).locks.release("slot-1", "other")
            for child in children:
                self.assertEqual(child.wait(timeout=30), 0)
            with open(events) as fh:
                records = [json.loads(line) for line in fh]
            self.assertEqual([r[0] for r in records if r[1] == "start"], list(range(5)))
            active = 0
            for _, phase, _ in records:
                active += 1 if phase == "start" else -1
                self.assertIn(active, (0, 1))
            self.assertEqual(active, 0)
            for previous, current in zip(records[1::2], records[2::2]):
                self.assertLess(current[2] - previous[2], 3.0)
            self.assertEqual(os.listdir(self.heavy_dir("queue")), [])
            self.assertEqual(os.listdir(self.heavy_dir("waiting")), [])
            self.assertFalse(heavy.Guard(env=env)._live_slots())
        finally:
            for child in children:
                if child.poll() is None:
                    child.terminate()
                    child.wait(timeout=10)

    def test_full_stderr_pipe_cancellation_exits_without_draining(self):
        code = r"""
import importlib.util, os, sys
source, sentinel = sys.argv[1:]
spec = importlib.util.spec_from_file_location("pipe_heavy", source)
h = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = h
spec.loader.exec_module(h)
g = h.Guard(reader=lambda: h.Memory(level=2, free_pct=50))
warn = g._warn
def output(message):
    if "heavy: refused" in message or " is waiting:" in message:
        print("writing", flush=True)
    return warn(message)
g._warn = output
os.set_blocking(2, False)
try:
    for size in (4096, 1):
        try:
            while True:
                os.write(2, b"x" * size)
        except BlockingIOError:
            pass
finally:
    os.set_blocking(2, True)
sys.exit(g.run("test", [sys.executable, "-c", "open(" + repr(sentinel) + ", 'w').write('x')"], wait=30))
"""
        for case in ("refusal", "waiting"):
            with self.subTest(case=case):
                if case == "refusal":
                    self.write_mode({"mode": "paused"})
                else:
                    self.write_mode({"mode": "continuous"})
                    self.hold("slot-1", pid=os.getpid())
                sentinel = os.path.join(self.tmp, "unexpected-child")
                child = subprocess.Popen([PY, "-c", code, HEAVY_PATH, sentinel],
                                         env=self.env(), stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                         text=True)
                try:
                    # Observe entry to the real warning with an already full
                    # stderr pipe. Readiness uses a separate file descriptor.
                    ready, _, _ = select.select([child.stdout], [], [], 10)
                    self.assertTrue(ready, "guard did not reach its diagnostic")
                    self.assertEqual(child.stdout.readline().strip(), "writing")
                    child.send_signal(signal.SIGTERM)
                    self.assertEqual(child.wait(timeout=5), 143)
                    self.assertFalse(os.path.exists(sentinel))
                    g = heavy.Guard(env=self.env())
                    self.assertEqual(g._records("queue"), [])
                    self.assertEqual(g._records("waiting"), [])
                    self.assertEqual(g._records("running"), [])
                    self.assertEqual(g._live_slots(), [] if case == "refusal" else ["slot-1"])
                    for kind in heavy.KIND_LOCKS:
                        self.assertEqual(g.locks.state(kind), "free")
                finally:
                    if child.poll() is None:
                        child.kill()
                    child.wait(timeout=5)
                    child.stdout.close()
                    child.stderr.close()
                    if case == "waiting":
                        heavy.Guard(env=self.env()).locks.release("slot-1", "other")

    def test_sigterm_is_forwarded_to_the_child(self):
        pidfile = os.path.join(self.tmp, "child.pid")
        guard = subprocess.Popen([PY, HEAVY_PATH, "run", "--kind", "light", "--"] + self.sleeper_cmd(pidfile),
                                 env=self.env(), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            self.wait_for_file(pidfile)
            with open(pidfile) as fh:
                child = int(fh.read())
            self.assertNotEqual(os.getpgid(child), os.getpgid(guard.pid))  # own session
            guard.send_signal(signal.SIGTERM)
            self.assertEqual(guard.wait(timeout=10), 128 + signal.SIGTERM)
            self.assert_gone(child)
            self.assertEqual(os.listdir(self.heavy_dir("running")), [])
        finally:
            if guard.poll() is None:
                guard.kill()
                guard.wait()

    def test_stop_all_terminates_recorded_groups_only(self):
        recorded = self.spawn_orphan(os.path.join(self.tmp, "a.pid"))
        by_argv0 = self.spawn_orphan(os.path.join(self.tmp, "b.pid"))
        stranger = self.spawn_orphan(os.path.join(self.tmp, "c.pid"))
        stranger_2 = self.spawn_orphan(os.path.join(self.tmp, "d.pid"))
        real_argv0 = heavy.default_proc_command(by_argv0).split()[0]
        running = self.heavy_dir("running")
        os.makedirs(running)
        # Every guard is gone, so stop-all must recognize the leaders on its own.
        records = (
            (recorded, {"argv0": PY, "lstart": heavy.default_proc_start(recorded)}),
            (by_argv0, {"argv0": real_argv0}),  # no lstart: argv0 fallback
            (FAKE_DEAD, {"argv0": "gone"}),  # group gone: record pruned
            # Same pids, different processes (pid reuse): leave them alone.
            (stranger, {"argv0": PY, "lstart": "Thu Jan  1 00:00:00 1970"}),
            (stranger_2, {"argv0": "not-this-program"}),
        )
        for pid, extra in records:
            with open(os.path.join(running, f"{pid}.json"), "w") as fh:
                json.dump(dict({"pid": pid, "pgid": pid, "guard": FAKE_DEAD, "kind": "test",
                                "cmd": "sleep"}, **extra), fh)
        out = io.StringIO()
        g = heavy.Guard(env=self.env(), stdout=out, stderr=io.StringIO())
        self.assertEqual(g.stop_all(grace=5), 0)
        self.assert_gone(recorded)
        self.assert_gone(by_argv0)
        self.assertTrue(heavy.default_pid_alive(stranger))
        self.assertTrue(heavy.default_pid_alive(stranger_2))
        text = out.getvalue()
        self.assertIn(f"SIGTERM process group {recorded}", text)
        self.assertIn(f"SIGTERM process group {by_argv0}", text)
        self.assertNotIn("SIGKILL", text)
        self.assertIn(f"skipping pgid {stranger}", text)
        self.assertIn(f"skipping pgid {stranger_2}", text)
        self.assertEqual(os.listdir(running), [])

    def test_running_record_has_start_time(self):
        seen = {}

        def proc_start(pid):
            seen["lstart"] = heavy.default_proc_start(pid)
            return seen["lstart"]
        rec_dir = self.heavy_dir("running")
        # The child polls until the guard has added lstart to its record (that
        # takes a ps call, which can be slow on a loaded machine), then prints it.
        child = (
            "import json, os, time\n"
            f"d = {rec_dir!r}\n"
            "deadline = time.time() + 20\n"
            "while True:\n"
            "    recs = []\n"
            "    for n in os.listdir(d):\n"
            "        if n.endswith('.json'):\n"
            "            with open(os.path.join(d, n)) as fh:\n"
            "                recs.append(json.load(fh))\n"
            "    if (recs and all('lstart' in r for r in recs)) or time.time() > deadline:\n"
            "        break\n"
            "    time.sleep(0.05)\n"
            "print(json.dumps(recs))\n"
        )
        cmd = [PY, "-c", child]
        out = os.path.join(self.tmp, "records.json")
        g = heavy.Guard(env=self.env(), proc_start=proc_start, stdout=io.StringIO(), stderr=io.StringIO())
        with open(out, "w") as fh:
            saved = os.dup(1)
            os.dup2(fh.fileno(), 1)
            try:
                self.assertEqual(g.run("light", cmd), 0)
            finally:
                os.dup2(saved, 1)
                os.close(saved)
        with open(out) as fh:
            records = json.load(fh)
        self.assertEqual(len(records), 1)
        self.assertTrue(seen["lstart"])
        self.assertEqual(records[0]["lstart"], seen["lstart"])
        self.assertEqual(records[0]["pgid"], records[0]["pid"])

    def test_stop_all_stops_a_waiting_guard(self):
        self.hold("slot-1", pid=os.getpid())  # a live holder: this test process
        rcfile = os.path.join(self.tmp, "guard.rc")
        # sh reaps the guard, as make or a login shell would, and records its exit code.
        wrapper = subprocess.Popen(
            ["sh", "-c", '"$@" 2>/dev/null; echo $? > "$RCFILE"', "sh",
             PY, HEAVY_PATH, "run", "--kind", "test", "--wait", "120", "--", PY, "-c", "pass"],
            env=self.env(**{heavy.env_name('MAX_SLOTS'): "1"}, RCFILE=rcfile))
        try:
            waiting = self.heavy_dir("waiting")
            deadline = time.monotonic() + 15
            names = []
            while time.monotonic() < deadline and not names:
                time.sleep(0.05)
                names = [n for n in os.listdir(waiting) if n.endswith(".json")] if os.path.isdir(waiting) else []
            self.assertEqual(len(names), 1)
            guard_pid = int(names[0].split(".")[0])
            self.addCleanup(self.kill_quietly, guard_pid)
            out = io.StringIO()
            g = heavy.Guard(env=self.env(), stdout=out, stderr=io.StringIO())
            self.assertEqual(g.stop_all(grace=5), 0)
            self.assertIn(f"waiting guard pid {guard_pid}", out.getvalue())
            self.assertNotIn("still alive", out.getvalue())
            self.assertEqual(wrapper.wait(timeout=10), 0)
            with open(rcfile) as fh:
                self.assertEqual(int(fh.read()), 128 + signal.SIGTERM)
            self.assertTrue(os.path.isdir(self.heavy_dir("slot-1")))  # not ours to remove
            self.assertEqual(os.listdir(waiting), [])
        finally:
            if wrapper.poll() is None:
                wrapper.kill()
                wrapper.wait()

    def test_stop_all_with_nothing_running(self):
        out = io.StringIO()
        heavy.Guard(env=self.env(), stdout=out, stderr=io.StringIO()).stop_all(grace=1)
        self.assertIn("nothing to stop", out.getvalue())


class CLITests(GuardCase):
    def cli(self, *args):
        env = clean_environ()
        env[heavy.env_name('RUN_DIR')] = self.run_dir
        return subprocess.run([PY, HEAVY_PATH] + list(args), env=env, capture_output=True,
                              text=True, timeout=60)

    def test_help(self):
        res = self.cli("--help")
        self.assertEqual(res.returncode, 0)
        self.assertIn("Mode gate", res.stdout)

    def test_run_needs_double_dash(self):
        res = self.cli("run", "--kind", "light", "echo", "hi")
        self.assertEqual(res.returncode, heavy.EX_USAGE)
        res = self.cli("run", "--kind", "light")
        self.assertEqual(res.returncode, heavy.EX_USAGE)
        self.assertIn("needs --", res.stderr)

    def test_run_passes_flags_after_double_dash(self):
        res = self.cli("run", "--kind", "light", "--", PY, "-c", "import sys; print(sys.argv[1:])",
                       "--kind", "x")
        self.assertEqual(res.returncode, 0)
        self.assertIn("['--kind', 'x']", res.stdout)

    def test_priority_flag_and_help(self):
        res = self.cli("run", "--help")
        self.assertEqual(res.returncode, 0)
        self.assertIn("HEAVY_PRIORITY", res.stdout)
        self.assertIn("coordinator", res.stdout)
        self.assertIn("HEAVY_NOTIFY", res.stdout)
        res = self.cli("run", "--kind", "light", "--priority", "high", "--", PY, "-c", "pass")
        self.assertEqual(res.returncode, 0)
        self.assertEqual(self.cli("run", "--kind", "light", "--priority", "typo", "--", PY, "-c", "pass").returncode,
                         heavy.EX_USAGE)

    def test_mode_round_trip(self):
        self.assertEqual(self.cli("mode", "nightshift", "--window", "22:00-06:00").returncode, 0)
        res = self.cli("mode")
        self.assertIn("window 22:00-06:00", res.stdout)
        res = self.cli("run", "--kind", "light", "--", PY, "-c", "print('ok')")
        self.assertEqual((res.returncode, res.stdout.strip()), (0, "ok"))


class ArgonReviewTests(GuardCase):
    """Findings of an outside review of 7b3cf56, each checked against the code."""

    def broken_stderr(self):
        r, w = os.pipe()
        os.close(r)  # every write now fails with EPIPE (Python ignores SIGPIPE)
        err = os.fdopen(w, "w")
        self.addCleanup(err.close)
        return err

    def test_closed_stderr_does_not_crash_a_refusal(self):
        self.write_mode({"mode": "paused"})
        g = self.guard(env={heavy.env_name('MAX_SLOTS'): "many"})  # warns at creation too
        g.err = self.broken_stderr()
        g._warn("heavy: probe")
        path, cmd = self.sentinel_cmd()
        self.assertEqual(g.run("test", cmd), heavy.EX_TEMPFAIL)
        self.assertEqual(self.log_entries()[-1]["rc"], heavy.EX_TEMPFAIL)

    def test_closed_stderr_waiting_still_ends_in_75(self):
        self.hold("slot-1")
        g = self.guard(level=2)
        g.err = self.broken_stderr()
        path, cmd = self.sentinel_cmd()
        self.assertEqual(g.run("test", cmd, wait=3), heavy.EX_TEMPFAIL)
        self.assertGreater(len(self.clock.sleeps), 0)
        self.assertIn("gave up after waiting", self.log_entries()[-1]["refused"])

    def test_closed_stderr_does_not_orphan_a_started_child(self):
        g = self.guard()
        g.err = self.broken_stderr()
        path, cmd = self.sentinel_cmd()
        with patch.object(heavy, "write_json_atomic", side_effect=OSError("disk full")):
            self.assertEqual(g.run("light", cmd), 0)
        self.assertTrue(os.path.exists(path))

    def test_signal_between_poll_check_and_sleep_is_not_stranded(self):
        self.hold("slot-1")
        g = self.guard(level=2)
        calls = []
        real = self.clock.monotonic

        def monotonic():
            if g._admission_depth == 0 and g._acquiring:
                calls.append(1)
                if len(calls) == 2:  # the remaining-time check after the first poll
                    g._pending = signal.SIGTERM
            return real()
        self.clock.monotonic = monotonic
        path, cmd = self.sentinel_cmd()
        self.assertEqual(g.run("test", cmd, wait=30), 128 + signal.SIGTERM)
        self.assertEqual(self.clock.sleeps, [])
        self.assertNotIn("is waiting", self.err.getvalue())

    def test_signal_during_a_failed_popen_is_honoured(self):
        g = self.guard()

        def popen(*args, **kwargs):
            g._pending = signal.SIGTERM
            raise FileNotFoundError(2, "No such file")
        with patch.object(heavy.subprocess, "Popen", side_effect=popen):
            self.assertEqual(g.run("light", ["no-such-command"]), 128 + signal.SIGTERM)
        self.assertNotIn("cannot start", self.err.getvalue())

    def test_failed_waiting_record_warning_is_interruptible(self):
        self.hold("slot-1")
        g = self.guard(level=2)

        def warn(msg):
            if "waiting record" in msg:
                self.assertFalse(g._acquiring)
                g._on_signal(signal.SIGTERM, None)  # raises now that deferral is off
        g._warn = warn
        real = heavy.write_json_atomic

        def write(path, data):
            if os.sep + "waiting" + os.sep in path:
                raise OSError("disk full")
            return real(path, data)
        path, cmd = self.sentinel_cmd()
        with patch.object(heavy, "write_json_atomic", side_effect=write):
            self.assertEqual(g.run("test", cmd, wait=30), 128 + signal.SIGTERM)
        self.assertFalse(os.path.exists(path))


AGENT = "00000000-0000-0000-0000-000000000001"  # placeholder Paseo agent id
PARENT = "00000000-0000-0000-0000-000000000002"  # its placeholder parent

FAKE_PASEO = r"""#!/usr/bin/env python3
import json, os, sys
try:
    os.getcwd()
except FileNotFoundError:
    # The real CLI (Node) dies the same way: uv_cwd ENOENT.
    print("paseo: uv_cwd ENOENT", file=sys.stderr)
    sys.exit(1)
with open(os.environ["FAKE_PASEO_LOG"], "a") as fh:
    fh.write(json.dumps(sys.argv[1:]) + "\n")
if sys.argv[1:2] == ["inspect"]:
    status = "idle"
    flag = os.environ.get("FAKE_PASEO_BUSY_FILE")
    if flag and os.path.exists(flag):
        status = "running"
    status = os.environ.get("FAKE_PASEO_STATUS", status)
    print(json.dumps({"Id": sys.argv[2], "Status": status,
                      "Provider": os.environ.get("FAKE_PASEO_PROVIDER", ""),
                      "ParentAgentId": os.environ.get("FAKE_PASEO_PARENT")}))
    sys.exit(0)
if os.environ.get("FAKE_PASEO_FAIL"):
    print("paseo: daemon unreachable", file=sys.stderr)
    sys.exit(1)
print(json.dumps({"ok": True}))
"""


class NotifyCase(GuardCase):
    """A fake paseo on PASEO_BIN that records every call as a JSON line."""

    def setUp(self):
        super().setUp()
        self.paseo = os.path.join(self.tmp, "bin", "paseo")
        os.makedirs(os.path.dirname(self.paseo))
        with open(self.paseo, "w") as fh:
            fh.write(FAKE_PASEO)
        os.chmod(self.paseo, 0o755)
        self.paseo_log = os.path.join(self.tmp, "paseo.jsonl")

    def notify_env(self, **extra):
        env = {"PASEO_BIN": self.paseo, "FAKE_PASEO_LOG": self.paseo_log}
        env.update(extra)
        return env

    def paseo_calls(self):
        if not os.path.exists(self.paseo_log):
            return []
        with open(self.paseo_log) as fh:
            return [json.loads(line) for line in fh]

    def sends(self):
        return [c for c in self.paseo_calls() if c[:1] == ["send"]]

    def notifier(self, g, kind="test", cmd=("make", "test-go"), log_lines=("building", "ok all")):
        log = os.path.join(self.tmp, "job.log")
        with open(log, "w") as fh:
            fh.write("\n".join(log_lines) + "\n")
        return heavy.Notifier(g, AGENT, kind, list(cmd), log)


class NotifyResolveTests(NotifyCase):
    def test_off_values_mean_a_blocking_run(self):
        for value in ("", "0", "off", "no", "false"):
            self.assertIsNone(self.guard(env=self.notify_env(HEAVY_NOTIFY=value)).notify_target(None), value)

    def test_auto_reads_paseo_agent_id(self):
        g = self.guard(env=self.notify_env(PASEO_AGENT_ID=AGENT))
        self.assertEqual(g.notify_target("auto"), AGENT)
        g = self.guard(env=self.notify_env(PASEO_AGENT_ID=AGENT, HEAVY_NOTIFY="auto"))
        self.assertEqual(g.notify_target(None), AGENT)
        self.assertIsNone(self.guard(env=self.notify_env()).notify_target(None))

    def test_bad_targets_are_usage_errors_and_run_nothing(self):
        for env, flag in (({}, "auto"), ({"HEAVY_NOTIFY": "nobody"}, None), ({}, "12345")):
            g = self.guard(env=self.notify_env(**env))
            path, cmd = self.sentinel_cmd()
            self.assertEqual(g.run("light", cmd, notify=flag), heavy.EX_USAGE, (env, flag))
            self.assertFalse(os.path.exists(path))
            self.assertIn("notify", self.err.getvalue().lower())

    def test_env_notify_under_make_is_refused_with_the_wrapper_hint(self):
        g = self.guard(env=self.notify_env(HEAVY_NOTIFY=AGENT, MAKELEVEL="1"))
        path, cmd = self.sentinel_cmd()
        with patch.object(heavy.Guard, "_detach", side_effect=AssertionError("detached")):
            self.assertEqual(g.run("test", cmd), heavy.EX_USAGE)
        self.assertFalse(os.path.exists(path))
        self.assertIn("--kind light", self.err.getvalue())
        # An explicit --notify is a deliberate wrapper (for example a make recipe).
        g = self.guard(env=self.notify_env(MAKELEVEL="1"))
        with patch.object(heavy.Guard, "_detach", return_value=0) as detach:
            self.assertEqual(g.run("test", cmd, notify=AGENT), 0)
        self.assertEqual(detach.call_count, 1)

    def test_nested_runs_ignore_notify_and_run_inline(self):
        g = self.guard(env=self.notify_env(HEAVY_NOTIFY=AGENT, **{heavy.env_name('HEAVY_HELD'): "1"}))
        path, cmd = self.sentinel_cmd()
        with patch.object(heavy.Guard, "_detach", side_effect=AssertionError("detached")):
            self.assertEqual(g.run("test", cmd), 0)
        self.assertTrue(os.path.exists(path))
        self.assertEqual(self.paseo_calls(), [])

    def test_mode_refusal_stays_inline(self):
        self.write_mode({"mode": "paused"})
        g = self.guard(env=self.notify_env(HEAVY_NOTIFY=AGENT))
        path, cmd = self.sentinel_cmd()
        with patch.object(heavy.Guard, "_detach", side_effect=AssertionError("detached")):
            self.assertEqual(g.run("test", cmd), heavy.EX_TEMPFAIL)
        self.assertIn("paused", self.err.getvalue())
        self.assertEqual(self.log_entries()[-1]["rc"], heavy.EX_TEMPFAIL)
        self.assertEqual(self.paseo_calls(), [])

    def test_job_env_drops_notify_variables(self):
        g = self.guard(env=self.notify_env(HEAVY_NOTIFY=AGENT, **{heavy.env_name('HEAVY_NOTIFY_AGENT'): AGENT},
                                           **{heavy.env_name('HEAVY_NOTIFY_FD'): "9"}, **{heavy.env_name('HEAVY_NOTIFY_LOG'): "/x"}))
        env = g.child_env("test", True, set())
        for key in ("HEAVY_NOTIFY", heavy.env_name('HEAVY_NOTIFY_AGENT'), heavy.env_name('HEAVY_NOTIFY_FD'), heavy.env_name('HEAVY_NOTIFY_LOG')):
            self.assertNotIn(key, env)
        self.assertEqual(env["PASEO_BIN"], self.paseo)

    def test_ticket_publication_reports_position(self):
        self.hold("slot-1")
        g = self.guard(level=2, env=self.notify_env())
        seen = []
        g.on_queued = lambda token, pos, total: seen.append((len(token), pos, total))
        path, cmd = self.sentinel_cmd()
        self.assertEqual(g.run("test", cmd, wait=2), heavy.EX_TEMPFAIL)
        self.assertEqual(seen, [(32, 1, 1)])
        self.assertIn("gave up after waiting", g.last_refusal)


class NotifyFinishTests(NotifyCase):
    def test_success_message_names_kind_command_exit_duration_log_and_tail(self):
        g = self.guard(env=self.notify_env())
        n = self.notifier(g, log_lines=["\x1b[32mPASS\x1b[0m engine", "heavy-notify: ping sent", "ok all 42"])
        self.clock.mono += 30
        g.started_at = self.clock.monotonic()
        self.clock.mono += 95
        self.assertTrue(n.finish(0, None))
        (call,) = self.sends()
        self.assertEqual(call[:2], ["send", AGENT])
        self.assertEqual(call[3:], ["--no-wait", "--json"])
        text = call[2]
        for part in ("test job", "exit 0", "make test-go", "2m05s", "queued 30s", "ran 1m35s",
                     "job.log", "PASS engine", "ok all 42"):
            self.assertIn(part, text)
        self.assertNotIn("\x1b", text)
        self.assertNotIn("ping sent", text)
        self.assertFalse(text.startswith("-"))

    def test_outcome_words(self):
        g = self.guard(env=self.notify_env())
        n = self.notifier(g)
        self.assertIn("ok", n.outcome(0, None))
        self.assertIn("failed (exit 1)", n.outcome(1, None))
        self.assertIn("refused (exit 75): the mode is paused", n.outcome(75, "the mode is paused"))
        self.assertIn("timed out in the queue (exit 75)", n.outcome(75, "busy; gave up after waiting 1h00m"))
        self.assertIn("stopped by signal 15 (exit 143)", n.outcome(143, None))

    def test_tail_is_bounded(self):
        g = self.guard(env=self.notify_env())
        n = self.notifier(g, log_lines=[f"line {i} " + "x" * 500 for i in range(100)])
        tail = n.tail()
        self.assertLessEqual(len(tail.splitlines()), heavy.NOTIFY_TAIL_LINES)
        self.assertIn("line 99", tail)
        self.assertTrue(all(len(line) <= 200 for line in tail.splitlines()))

    def test_failed_send_retries_then_writes_an_alert(self):
        g = self.guard(env=self.notify_env(FAKE_PASEO_FAIL="1"))
        n = self.notifier(g)
        self.assertFalse(n.finish(1, None))
        self.assertEqual(len(self.sends()), len(heavy.NOTIFY_BACKOFF) + 1)
        self.assertEqual(self.clock.sleeps, list(heavy.NOTIFY_BACKOFF))
        alerts = os.listdir(os.path.join(self.run_dir, "alerts"))
        self.assertEqual(len(alerts), 1)
        self.assertRegex(alerts[0], r"^quota-\d+-heavy-notify-failed\.md$")
        with open(os.path.join(self.run_dir, "alerts", alerts[0])) as fh:
            body = fh.read()
        for part in (AGENT, "job.log", "make test-go", "exit 1", "daemon unreachable"):
            self.assertIn(part, body)

    def test_outcome_waits_a_while_for_a_busy_agent_then_sends_anyway(self):
        busy = os.path.join(self.tmp, "busy")
        open(busy, "w").close()
        g = self.guard(env=self.notify_env(FAKE_PASEO_BUSY_FILE=busy))
        n = self.notifier(g)
        self.clock.on_sleep = lambda count: count == 3 and os.unlink(busy)
        self.assertTrue(n.finish(0, None))
        self.assertEqual(self.clock.sleeps, [heavy.BUSY_POLL] * 3)
        open(busy, "w").close()
        self.clock.sleeps.clear()
        self.clock.on_sleep = None
        self.assertTrue(n.finish(0, None))
        self.assertEqual(sum(self.clock.sleeps), heavy.BUSY_MAX)
        self.assertEqual(len(self.sends()), 2)

    def test_closed_agent_outcome_goes_to_its_parent(self):
        g = self.guard(env=self.notify_env(FAKE_PASEO_STATUS="closed", FAKE_PASEO_PARENT=PARENT))
        n = self.notifier(g)
        self.assertTrue(n.finish(0, None))
        sends = self.sends()
        self.assertEqual(len(sends), 1)
        self.assertEqual(sends[0][1], PARENT)
        self.assertIn(f"agent {AGENT} is closed", sends[0][2])
        self.assertIn("ended: ok (exit 0)", sends[0][2])

    def test_closed_agent_without_a_parent_is_sent_to_as_before(self):
        for parent in ("", "nobody", AGENT):
            if os.path.exists(self.paseo_log):
                os.unlink(self.paseo_log)
            g = self.guard(env=self.notify_env(FAKE_PASEO_STATUS="closed", FAKE_PASEO_PARENT=parent))
            self.assertTrue(self.notifier(g).finish(0, None))
            self.assertEqual([s[1] for s in self.sends()], [AGENT], parent)

    def test_open_agent_keeps_its_outcome(self):
        g = self.guard(env=self.notify_env(FAKE_PASEO_PARENT=PARENT))
        self.assertTrue(self.notifier(g).finish(0, None))
        self.assertEqual([s[1] for s in self.sends()], [AGENT])

    def test_outcome_is_sent_after_the_jobs_directory_is_removed(self):
        # The coordinator merges and removes a worktree while the outcome
        # waits for it to go idle; the send must not run from that directory.
        g = self.guard(env=self.notify_env())
        n = self.notifier(g)
        gone = os.path.join(self.tmp, "worktree")
        os.mkdir(gone)
        here = os.getcwd()
        os.chdir(gone)
        try:
            os.rmdir(gone)
            self.assertTrue(n.finish(0, None))
        finally:
            os.chdir(here)
        self.assertEqual(len(self.sends()), 1)
        self.assertFalse(os.path.exists(os.path.join(self.run_dir, "alerts")))

    def test_missing_paseo_binary_still_alerts(self):
        g = self.guard(env=self.notify_env(PASEO_BIN=os.path.join(self.tmp, "no-such-paseo")))
        n = self.notifier(g)
        self.assertFalse(n.finish(0, None))
        self.assertEqual(len(os.listdir(os.path.join(self.run_dir, "alerts"))), 1)


class NotifyPingTests(NotifyCase):
    def test_claude_pings_every_50_minutes_for_the_first_3_5_hours(self):
        g = self.guard(env=self.notify_env(FAKE_PASEO_PROVIDER="handoff-claude-0cb917b39a28"))
        n = self.notifier(g)
        times = []
        for _ in range(4 * 3600 // 60):
            self.clock.mono += 60
            if n.maybe_ping():
                times.append(self.clock.mono)
        self.assertEqual(times, [3000, 6000, 9000, 12000])
        # One inspect learns the provider early; each due ping checks the agent is idle.
        self.assertEqual(len([c for c in self.paseo_calls() if c[0] == "inspect"]), 1 + len(times))
        text = self.sends()[0][2]
        self.assertIn("one word", text)
        self.assertIn("make test-go", text)
        self.assertIn("queue", text)

    def test_codex_pings_every_25_minutes(self):
        g = self.guard(env=self.notify_env(FAKE_PASEO_PROVIDER="codex"))
        n = self.notifier(g)
        times = []
        for _ in range(3600 // 60):
            self.clock.mono += 60
            if n.maybe_ping():
                times.append(self.clock.mono)
        self.assertEqual(times, [1500, 3000])

    def test_a_running_job_says_so_and_a_short_one_never_pings(self):
        g = self.guard(env=self.notify_env(FAKE_PASEO_PROVIDER="claude"))
        n = self.notifier(g)
        self.clock.mono += 600
        g.started_at = self.clock.monotonic()
        self.clock.mono += 2000
        self.assertFalse(n.maybe_ping())
        self.clock.mono += 400
        self.assertTrue(n.maybe_ping())
        self.assertIn("running", self.sends()[0][2])

    def test_a_busy_agent_is_not_pinged_and_counts_as_contact(self):
        busy = os.path.join(self.tmp, "busy")
        open(busy, "w").close()
        g = self.guard(env=self.notify_env(FAKE_PASEO_PROVIDER="claude", FAKE_PASEO_BUSY_FILE=busy))
        n = self.notifier(g)
        self.clock.mono = 3000
        self.assertFalse(n.maybe_ping())
        os.unlink(busy)
        self.clock.mono = 5940
        self.assertFalse(n.maybe_ping())
        self.clock.mono = 6000
        self.assertTrue(n.maybe_ping())
        self.assertEqual(len(self.sends()), 1)

    def test_a_closed_agent_is_not_pinged(self):
        g = self.guard(env=self.notify_env(FAKE_PASEO_PROVIDER="claude", FAKE_PASEO_STATUS="closed",
                                           FAKE_PASEO_PARENT=PARENT))
        n = self.notifier(g)
        self.clock.mono = 3000
        self.assertFalse(n.maybe_ping())
        self.assertEqual(self.sends(), [])

    def test_no_ping_after_the_outcome(self):
        g = self.guard(env=self.notify_env(FAKE_PASEO_PROVIDER="claude"))
        n = self.notifier(g)
        self.assertTrue(n.finish(0, None))
        self.clock.mono = 3000
        self.assertFalse(n.maybe_ping())
        self.assertEqual(len(self.sends()), 1)

    def test_failed_ping_backs_off_without_counting_as_contact(self):
        g = self.guard(env=self.notify_env(FAKE_PASEO_PROVIDER="claude", FAKE_PASEO_FAIL="1"))
        n = self.notifier(g)
        self.clock.mono = 3000
        self.assertFalse(n.maybe_ping())
        self.clock.mono += 60
        self.assertFalse(n.maybe_ping())
        self.assertEqual(len(self.sends()), 1)
        self.clock.mono += heavy.PING_RETRY
        n.maybe_ping()
        self.assertEqual(len(self.sends()), 2)

    def test_unknown_provider_uses_the_claude_interval_and_asks_again(self):
        g = self.guard(env=self.notify_env())
        n = self.notifier(g)
        self.clock.mono = 1500
        self.assertFalse(n.maybe_ping())
        self.clock.mono = 3000
        self.assertTrue(n.maybe_ping())
        self.assertGreaterEqual(len([c for c in self.paseo_calls() if c[0] == "inspect"]), 2)


class NotifyChildTests(NotifyCase):
    """run_notified, the detached copy, driven in-process with a handshake pipe."""

    def child(self, read_end_open=True, ack=True, **env):
        """A copy whose caller reads the report (unless read_end_open is False) and acks it."""
        r, w = os.pipe()
        ack_r, ack_w = os.pipe()
        if ack:
            os.write(ack_w, b"k")
        os.close(ack_w)
        if not read_end_open:
            os.close(r)
            r = None
        g = self.guard(env=self.notify_env(
            **{heavy.env_name('HEAVY_NOTIFY_AGENT'): AGENT}, **{heavy.env_name('HEAVY_NOTIFY_FD'): str(w)}, **{heavy.env_name('HEAVY_NOTIFY_ACK_FD'): str(ack_r)},
            **{heavy.env_name('HEAVY_NOTIFY_LOG'): os.path.join(self.tmp, "job.log")}, **env))
        return g, r

    def read_all(self, r):
        with os.fdopen(r, "rb") as fh:
            return fh.read().decode()

    def test_refusal_before_queuing_goes_to_the_caller_not_the_agent(self):
        self.write_mode({"mode": "paused"})
        g, r = self.child()
        self.assertEqual(g.run_notified("test", [PY, "-c", "pass"], 1, None), heavy.EX_TEMPFAIL)
        self.assertRegex(self.read_all(r), r"^refused .*paused")
        self.assertEqual(self.sends(), [])

    def test_an_unacknowledged_refusal_is_messaged(self):
        # The caller gave up waiting (or died) just as the report landed in the pipe.
        self.write_mode({"mode": "paused"})
        g, r = self.child(ack=False)
        self.assertEqual(g.run_notified("test", [PY, "-c", "pass"], 1, None), heavy.EX_TEMPFAIL)
        self.assertRegex(self.read_all(r), r"^refused ")
        (call,) = self.sends()
        self.assertIn("refused (exit 75)", call[2])

    def test_refusal_is_messaged_when_the_caller_is_gone(self):
        self.write_mode({"mode": "paused"})
        g, _ = self.child(read_end_open=False)
        self.assertEqual(g.run_notified("test", [PY, "-c", "pass"], 1, None), heavy.EX_TEMPFAIL)
        (call,) = self.sends()
        self.assertIn("refused (exit 75)", call[2])

    def test_queued_job_handshakes_its_ticket_then_messages(self):
        g, r = self.child()
        path, cmd = self.sentinel_cmd()
        self.assertEqual(g.run_notified("test", cmd, 5, None), 0)
        self.assertRegex(self.read_all(r), r"^queued [0-9a-f]{32} 1 1\n$")
        self.assertTrue(os.path.exists(path))
        (call,) = self.sends()
        self.assertIn("ok (exit 0)", call[2])

    def test_guard_error_reaches_the_caller_or_else_the_agent(self):
        g, r = self.child()
        with patch.object(heavy.Guard, "run", side_effect=RuntimeError("boom")):
            self.assertEqual(g.run_notified("test", [PY, "-c", "pass"], 1, None), 1)
        self.assertEqual(self.read_all(r), "ended 1\n")
        self.assertEqual(self.sends(), [])
        g, _ = self.child(read_end_open=False)
        with patch.object(heavy.Guard, "run", side_effect=RuntimeError("boom")):
            self.assertEqual(g.run_notified("test", [PY, "-c", "pass"], 1, None), 1)
        (call,) = self.sends()
        self.assertIn("failed (exit 1)", call[2])


class NotifyProcessTests(NotifyCase):
    """The real CLI: detach, handshake, job, message."""

    def cli_env(self, **extra):
        env = clean_environ()
        env[heavy.env_name('RUN_DIR')] = self.run_dir
        env.update(self.notify_env(**extra))
        return env

    def wait_for_send(self, timeout=30.0):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            sends = self.sends()
            if sends:
                return sends
            time.sleep(0.05)
        self.fail("no paseo send arrived")

    def detached_pid(self, stdout):
        import re
        match = re.search(r"pid (\d+)", stdout)
        self.assertIsNotNone(match, stdout)
        return int(match.group(1))

    def test_light_job_detaches_and_messages_when_it_ends(self):
        go = os.path.join(self.tmp, "go")
        self.addCleanup(lambda: os.path.exists(self.tmp) and open(go, "w").close())
        code = ("import os, time\n"
                "deadline = time.monotonic() + 60\n"
                f"while not os.path.exists({go!r}) and time.monotonic() < deadline: time.sleep(0.05)\n"
                f"print('job says hello', os.environ.get('HEAVY_NOTIFY'), os.environ.get({heavy.env_name('HEAVY_NOTIFY_FD')!r}))\n"
                "raise SystemExit(3)\n")
        res = subprocess.run([PY, HEAVY_PATH, "run", "--kind", "light", "--notify", AGENT, "--", PY, "-c", code],
                             env=self.cli_env(HEAVY_NOTIFY=AGENT), capture_output=True, text=True, timeout=60)
        # The job is still blocked on the go file, so the guard returned before it ended.
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertIn("end your turn", res.stdout)
        self.assertIn("heavy-notify", res.stdout)
        pid = self.detached_pid(res.stdout)
        self.addCleanup(self.kill_if_alive, pid)
        self.assertNotEqual(os.getsid(pid), os.getsid(0))
        self.assertEqual(self.sends(), [])
        open(go, "w").close()
        (call,) = self.wait_for_send()
        self.assertEqual(call[1], AGENT)
        self.assertIn("exit 3", call[2])
        self.assertIn("job says hello None None", call[2])
        self.assert_exits(pid)
        entry = self.log_entries()[-1]
        self.assertEqual((entry["kind"], entry["rc"]), ("light", 3))

    def test_queued_job_reports_its_ticket_and_refusal_is_messaged(self):
        # Hold every slot with this live test process, so the job must queue.
        for i in range(1, 4):
            self.hold(f"slot-{i}", pid=os.getpid())
        res = subprocess.run([PY, HEAVY_PATH, "run", "--kind", "test", "--wait", "1", "--", PY, "-c", "pass"],
                             env=self.cli_env(HEAVY_NOTIFY="auto", PASEO_AGENT_ID=AGENT),
                             capture_output=True, text=True, timeout=60)
        self.assertEqual(res.returncode, 0, res.stderr)
        self.addCleanup(self.kill_if_alive, self.detached_pid(res.stdout))
        self.assertRegex(res.stdout, r"ticket [0-9a-f]{32}, number 1 of 1 in the queue")
        (call,) = self.wait_for_send()
        self.assertIn("timed out in the queue (exit 75)", call[2])
        self.assert_exits(self.detached_pid(res.stdout))
        self.assertEqual(os.listdir(self.heavy_dir("queue")), [])

    def kill_if_alive(self, pid):
        if heavy.default_pid_alive(pid) and "heavy.py" in (heavy.default_proc_command(pid) or ""):
            os.kill(pid, signal.SIGKILL)

    def assert_exits(self, pid, timeout=15.0):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if not heavy.default_pid_alive(pid):
                return
            time.sleep(0.05)
        self.fail(f"detached guard {pid} is still alive")


if __name__ == "__main__":
    unittest.main()
