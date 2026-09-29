from __future__ import annotations

import os
import subprocess
import sys
import unittest

from world.rng import derive_seed, rng

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class RngTests(unittest.TestCase):
    def test_same_inputs_same_stream(self):
        a = [rng(1, 10, "john", "x").random() for _ in range(3)]
        b = [rng(1, 10, "john", "x").random() for _ in range(3)]
        self.assertEqual(a, b)

    def test_every_input_matters(self):
        base = derive_seed(1, 10, "john", "x")
        for other in (derive_seed(2, 10, "john", "x"), derive_seed(1, 11, "john", "x"),
                      derive_seed(1, 10, "mary", "x"), derive_seed(1, 10, "john", "y")):
            self.assertNotEqual(base, other)

    def test_int_and_str_seed_agree(self):
        self.assertEqual(derive_seed(184729, 5, "a", "p"), derive_seed("184729", 5, "a", "p"))

    def test_stable_across_processes_and_hash_seeds(self):
        code = ("from world.rng import derive_seed; from world.seed import build_world; "
                "from world.db import connect, init_db; c=connect(); init_db(c,7); build_world(c,7); "
                "print(derive_seed(7,3,'ming','p'), c.execute('select sum(money_cents) from people').fetchone()[0], "
                "c.execute('select round(sum(trust),4) from relationships').fetchone()[0])")
        outs = set()
        for hash_seed in ("0", "1", "random"):
            env = {**os.environ, "PYTHONHASHSEED": hash_seed, "PYTHONPATH": ROOT}
            r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env=env, cwd=ROOT)
            self.assertEqual(r.returncode, 0, r.stderr)
            outs.add(r.stdout.strip())
        self.assertEqual(len(outs), 1, outs)

    def test_no_builtin_hash_or_bare_random_in_engine_code(self):
        offenders = []
        for folder in ("world", "agent", "narrative"):
            for name in os.listdir(os.path.join(ROOT, folder)):
                if not name.endswith(".py") or name == "rng.py":
                    continue
                text = open(os.path.join(ROOT, folder, name), encoding="utf-8").read()
                if " hash(" in text or "=hash(" in text or "random.Random(" in text or "random.random(" in text:
                    offenders.append(f"{folder}/{name}")
        self.assertEqual(offenders, [])


if __name__ == "__main__":
    unittest.main()
