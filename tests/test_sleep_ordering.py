"""Check the packaged helpers against systemd's actual sleep transactions.

Run as an unprivileged user: python3 -m unittest discover -s tests -v
systemd --test loads units and reports ordering; it starts no services.
"""
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SYSTEMD = next((p for p in ("/usr/lib/systemd/systemd", "/lib/systemd/systemd")
                if Path(p).is_file()), None)
UNITS = next((Path(p) for p in ("/usr/lib/systemd/system", "/lib/systemd/system")
              if (Path(p) / "sleep.target").is_file()), None)
MODES = ("suspend", "hibernate", "hybrid-sleep", "suspend-then-hibernate")


def precedes(graph, first, last):
    pending, seen = [first], set()
    while pending:
        node = pending.pop()
        if node == last:
            return True
        if node not in seen:
            seen.add(node)
            pending.extend(graph.get(node, ()))
    return False


@unittest.skipUnless(SYSTEMD and UNITS, "requires installed systemd unit files")
@unittest.skipIf(os.geteuid() == 0, "systemd --test must run unprivileged")
class SleepOrderingTest(unittest.TestCase):
    def transaction(self, mode):
        with tempfile.TemporaryDirectory(prefix="open-fprintd-ordering-") as tmp:
            units = Path(tmp)
            # Use the real distro sleep chain and the unchanged packaged helpers.
            for name in ("sleep.target", mode + ".target",
                         "systemd-" + mode + ".service"):
                shutil.copyfile(UNITS / name, units / name)
            for phase in ("suspend", "resume"):
                name = "open-fprintd-" + phase + ".service"
                shutil.copyfile(ROOT / "debian" / name, units / name)
                wants = units / (mode + ".target.wants")
                wants.mkdir(exist_ok=True)
                (wants / name).symlink_to("../" + name)
            # Minimal boot targets keep this independent of host boot services.
            for name in ("sysinit.target", "basic.target", "shutdown.target"):
                (units / name).write_text("[Unit]\nDefaultDependencies=no\n")
            env = dict(os.environ, LC_ALL="C", SYSTEMD_UNIT_PATH=tmp,
                       SYSTEMD_GENERATOR_PATH="/dev/null",
                       SYSTEMD_ENVIRONMENT_GENERATOR_PATH="/dev/null",
                       SYSTEMD_LOG_LEVEL="err", SYSTEMD_LOG_COLOR="0")
            result = subprocess.run(
                [SYSTEMD, "--system", "--test", "--unit=" + mode + ".target"],
                env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                encoding="utf-8", errors="replace", timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("ordering cycle", result.stderr.lower(), result.stderr)
        graph, current = {}, None
        for line in result.stdout.splitlines():
            unit = re.match(r"\s*(?:→|->) Unit (\S+):$", line)
            if unit:
                current = unit.group(1)
                graph.setdefault(current, set())
            edge = re.match(r"\s*(Before|After): (\S+)", line)
            if current and edge:
                kind, other = edge.groups()
                first, last = (current, other) if kind == "Before" else (other, current)
                graph.setdefault(first, set()).add(last)
        for name in ("open-fprintd-suspend.service", "open-fprintd-resume.service",
                     "systemd-" + mode + ".service"):
            self.assertIn(name, graph, "expected unit missing from dry-run output")
        return graph

    def test_helpers_bracket_the_sleep_operation(self):
        for mode in MODES:
            with self.subTest(mode=mode):
                graph = self.transaction(mode)
                operation = "systemd-" + mode + ".service"
                self.assertTrue(precedes(graph, "open-fprintd-suspend.service", operation),
                                "suspend helper can race " + operation)
                self.assertTrue(precedes(graph, operation, "open-fprintd-resume.service"),
                                "resume helper can run before " + operation)
                self.assertFalse(precedes(graph, operation, "open-fprintd-suspend.service"),
                                 "suspend helper must not run after " + operation)


if __name__ == "__main__":
    unittest.main()
