#!/usr/bin/env python3
"""Regression runner for the RTL and its testbenches.

Each test builds from source and runs to completion; a test passes only if the
simulator exits zero, so an assertion failure, a scoreboard mismatch or a $fatal
all count as failures.

Two modes:

  default     build and run every test against the clean RTL
  --mutation  for each fault injected into the RTL, run the tests that are meant
              to detect it and require that they fail

The mutation mode is what stops the suite from silently rotting into a set of
tests that pass no matter what the hardware does.
"""

import argparse
import os
import re
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field
from typing import Callable, List

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BUILD = os.path.join(ROOT, "build")
CPP = os.path.join(ROOT, "verif", "cpp")

RTL = {
    "alu": "rtl/alu.v",
    "sync_fifo": "rtl/sync_fifo.sv",
    "fir8_direct": "rtl/fir8_direct.sv",
    "fir8_pipelined": "rtl/fir8_pipelined.sv",
}

# Warnings waived for testbench and assertion builds only; RTL is linted with a
# bare -Wall by the lint test.
#   BLKSEQ        blocking assignment in a testbench clock generator
#   DECLFILENAME  tb_pkg.sv holds several small classes rather than one per file
#   SYNCASYNCNET  `disable iff (!rst_n)` samples an async reset synchronously,
#                 which is how SVA is written for an async-reset design
TB_WAIVERS = ["-Wno-BLKSEQ", "-Wno-DECLFILENAME", "-Wno-SYNCASYNCNET"]

FIR_CFLAGS = ["-DDUT_DW=8", "-DDUT_CW=8", "-DDUT_ACCW=19"]

# Parallelism for the C++ compilation Verilator drives.
VERILATOR_JOBS = "4"


def abspaths(rel):
    return [os.path.join(ROOT, p) for p in rel]


@dataclass
class Test:
    name: str
    sim: str
    build: Callable[[str, List[str]], List[List[str]]]
    run: Callable[[str, "Config"], List[str]]
    tags: List[str] = field(default_factory=list)


@dataclass
class Config:
    seed: int = 1
    scale: float = 1.0

    def count(self, nominal):
        return max(1, int(nominal * self.scale))


def iverilog_test(name, sources, top, plusargs, tags=()):
    def build(objdir, defines):
        out = os.path.join(objdir, "sim.vvp")
        cmd = ["iverilog", "-g2012", "-o", out, "-s", top]
        cmd += [f"-D{d}" for d in defines]
        cmd += abspaths(sources)
        return [cmd]

    def run(objdir, cfg):
        return ["vvp", os.path.join(objdir, "sim.vvp")] + plusargs(cfg)

    return Test(name, "icarus", build, run, tags=list(tags))


def verilator_sv_test(name, sources, top, plusargs, tags=()):
    def build(objdir, defines):
        cmd = [
            "verilator", "--binary", "--timing", "--assert", "-Wall",
            *TB_WAIVERS, "-j", VERILATOR_JOBS, "--prefix", "Vdut",
            "--Mdir", objdir, "-o", "sim", "--top-module", top,
        ]
        cmd += [f"-D{d}" for d in defines]
        cmd += abspaths(sources)
        return [cmd]

    def run(objdir, cfg):
        return [os.path.join(objdir, "sim")] + plusargs(cfg)

    return Test(name, "verilator", build, run, tags=list(tags))


def verilator_cpp_test(name, sources, cpp_sources, top, cflags, args,
                       params=(), tags=()):
    def build(objdir, defines):
        cmd = [
            "verilator", "--cc", "--exe", "--build", "--assert", "-Wall",
            *TB_WAIVERS, "-j", VERILATOR_JOBS, "--prefix", "Vdut",
            "--Mdir", objdir, "-o", "sim", "--top-module", top,
        ]
        cmd += list(params)
        cmd += [f"-D{d}" for d in defines]
        cmd += ["-CFLAGS", " ".join(list(cflags) + [f"-I{CPP}"])]
        cmd += abspaths(sources) + abspaths(cpp_sources)
        return [cmd]

    def run(objdir, cfg):
        return [os.path.join(objdir, "sim")] + args(cfg)

    return Test(name, "verilator", build, run, tags=list(tags))


def lint_test():
    def build(objdir, defines):
        return []

    def run(objdir, cfg):
        # A single shell invocation so one command covers every RTL file.
        parts = [
            f"verilator --lint-only -Wall --top-module {top} {os.path.join(ROOT, src)}"
            for top, src in RTL.items()
        ]
        return ["sh", "-c", " && ".join(parts)]

    return Test("lint", "verilator", build, run, tags=["static"])


def python_test(name, script):
    def build(objdir, defines):
        return []

    def run(objdir, cfg):
        return [sys.executable, os.path.join(ROOT, script)]

    return Test(name, "python", build, run, tags=["static"])


def all_tests():
    return [
        lint_test(),
        python_test("sta_selfcheck", "verif/test_sta.py"),

        iverilog_test(
            "alu_directed",
            ["verif/tb_pkg.sv", "verif/alu_tb.sv", "rtl/alu.v"],
            "alu_tb",
            lambda cfg: [],
            tags=["alu"],
        ),
        iverilog_test(
            "fifo_directed",
            ["verif/tb_pkg.sv", "verif/fifo_tb.sv", "rtl/sync_fifo.sv"],
            "fifo_tb",
            lambda cfg: ["+TEST=directed"],
            tags=["fifo"],
        ),
        iverilog_test(
            "fifo_random",
            ["verif/tb_pkg.sv", "verif/fifo_tb.sv", "rtl/sync_fifo.sv"],
            "fifo_tb",
            lambda cfg: [f"+SEED={cfg.seed}", f"+CYCLES={cfg.count(4000)}",
                         "+TEST=random"],
            tags=["fifo"],
        ),

        # Same testbenches again under Verilator, which activates the bound
        # assertions the event-driven simulator cannot compile.
        verilator_sv_test(
            "fifo_directed_sva",
            ["verif/tb_pkg.sv", "verif/fifo_tb.sv", "rtl/sync_fifo.sv",
             "verif/sva/fifo_props.sv"],
            "fifo_tb",
            lambda cfg: ["+TEST=directed"],
            tags=["fifo", "sva"],
        ),
        verilator_sv_test(
            "fifo_random_sva",
            ["verif/tb_pkg.sv", "verif/fifo_tb.sv", "rtl/sync_fifo.sv",
             "verif/sva/fifo_props.sv"],
            "fifo_tb",
            lambda cfg: [f"+SEED={cfg.seed}", f"+CYCLES={cfg.count(4000)}",
                         "+TEST=random"],
            tags=["fifo", "sva"],
        ),

        verilator_cpp_test(
            "alu_exhaustive",
            ["rtl/alu.v", "verif/sva/alu_props.sv"],
            ["verif/cpp/tb_alu.cpp", "verif/cpp/golden.cpp"],
            "alu",
            cflags=["-DDUT_W=8"],
            params=["-GW=8"],
            args=lambda cfg: ["--exhaustive"],
            tags=["alu", "sva"],
        ),
        verilator_cpp_test(
            "alu_random_w32",
            ["rtl/alu.v", "verif/sva/alu_props.sv"],
            ["verif/cpp/tb_alu.cpp", "verif/cpp/golden.cpp"],
            "alu",
            cflags=["-DDUT_W=32"],
            params=["-GW=32"],
            args=lambda cfg: ["--vectors", str(cfg.count(2000000)),
                              "--seed", str(cfg.seed)],
            tags=["alu", "sva"],
        ),

        verilator_cpp_test(
            "fir_direct",
            ["rtl/fir8_direct.sv", "verif/sva/fir_props.sv",
             "verif/sva/fir8_direct_bind.sv"],
            ["verif/cpp/tb_fir.cpp", "verif/cpp/golden.cpp"],
            "fir8_direct",
            cflags=FIR_CFLAGS + ["-DDUT_LATENCY=1"],
            args=lambda cfg: ["--vectors", str(cfg.count(50000)),
                              "--seed", str(cfg.seed)],
            tags=["fir", "sva"],
        ),
        verilator_cpp_test(
            "fir_pipelined",
            ["rtl/fir8_pipelined.sv", "verif/sva/fir_props.sv",
             "verif/sva/fir8_pipelined_bind.sv"],
            ["verif/cpp/tb_fir.cpp", "verif/cpp/golden.cpp"],
            "fir8_pipelined",
            cflags=FIR_CFLAGS + ["-DDUT_LATENCY=4"],
            args=lambda cfg: ["--vectors", str(cfg.count(50000)),
                              "--seed", str(cfg.seed)],
            tags=["fir", "sva"],
        ),
    ]


# Fault injected into the RTL -> tests that are expected to detect it.
MUTATIONS = [
    ("BUG_ALU_SRA", ["alu_directed", "alu_exhaustive"]),
    ("BUG_ALU_SUB_OVF", ["alu_directed", "alu_exhaustive"]),
    ("BUG_ALU_SHAMT", ["alu_directed", "alu_exhaustive"]),
    ("BUG_FIFO_OVERWRITE", ["fifo_directed", "fifo_random", "fifo_random_sva"]),
    ("BUG_FIFO_PTR", ["fifo_directed", "fifo_random", "fifo_random_sva"]),
    ("BUG_FIFO_COUNT", ["fifo_directed", "fifo_random", "fifo_random_sva"]),
    ("BUG_FIR_TAP", ["fir_direct", "fir_pipelined"]),
    ("BUG_FIR_SIGN", ["fir_direct", "fir_pipelined"]),
    ("BUG_FIR_VALID", ["fir_direct", "fir_pipelined"]),
]

DETAIL_PATTERNS = [
    re.compile(r"^RESULT: .*$", re.M),
    re.compile(r"^\[(?:PASS|FAIL)\] .*$", re.M),
    re.compile(r"^%Error.*$", re.M),
    re.compile(r"^\s*Assertion failed.*$", re.M),
]


def summarize(output):
    """Pick one line to show: whichever reports a failure, else the last match."""
    for pattern in DETAIL_PATTERNS:
        matches = pattern.findall(output)
        if not matches:
            continue
        for line in matches:
            if any(word in line for word in ("FAIL", "Error", "Assertion")):
                return line.strip()[:110]
        return matches[-1].strip()[:110]
    return ""


def execute(test, cfg, defines, objdir, timeout=1800):
    if os.path.isdir(objdir):
        shutil.rmtree(objdir)
    os.makedirs(objdir, exist_ok=True)

    log = []
    for cmd in test.build(objdir, defines):
        proc = subprocess.run(cmd, capture_output=True, text=True, cwd=ROOT,
                              timeout=timeout)
        log.append(proc.stdout + proc.stderr)
        if proc.returncode != 0:
            return False, "build failed: " + summarize(log[-1]), "".join(log)

    proc = subprocess.run(test.run(objdir, cfg), capture_output=True, text=True,
                          cwd=ROOT, timeout=timeout)
    log.append(proc.stdout + proc.stderr)
    return proc.returncode == 0, summarize(log[-1]), "".join(log)


def run_regression(tests, cfg, verbose):
    print(f"{'test':<20} {'sim':<10} {'result':<7} {'time':>7}  detail")
    print("-" * 100)
    failures = []
    for test in tests:
        objdir = os.path.join(BUILD, "regress", test.name)
        t0 = time.time()
        try:
            ok, detail, log = execute(test, cfg, [], objdir)
        except subprocess.TimeoutExpired:
            ok, detail, log = False, "timed out", ""
        elapsed = time.time() - t0
        status = "PASS" if ok else "FAIL"
        print(f"{test.name:<20} {test.sim:<10} {status:<7} {elapsed:>6.1f}s  {detail}")
        if not ok:
            failures.append(test.name)
            if verbose:
                print(log)
    print()
    if failures:
        print(f"FAILED {len(failures)}/{len(tests)}: {', '.join(failures)}")
        return 1
    print(f"PASSED {len(tests)}/{len(tests)} tests")
    return 0


def run_mutations(tests, cfg, mutations, verbose):
    by_name = {t.name: t for t in tests}
    print(f"{'fault':<22} {'detected by':<22} {'result':<9} {'time':>7}  detail")
    print("-" * 100)
    escaped = []
    for bug, detectors in mutations:
        caught_by = []
        for name in detectors:
            test = by_name.get(name)
            if test is None:
                continue
            objdir = os.path.join(BUILD, "mutation", bug, name)
            t0 = time.time()
            try:
                ok, detail, log = execute(test, cfg, [bug], objdir)
            except subprocess.TimeoutExpired:
                ok, detail, log = True, "timed out", ""
            elapsed = time.time() - t0
            # The mutation is meant to break the design: a passing test means
            # the fault escaped detection.
            detected = not ok
            if detected:
                caught_by.append(name)
            print(f"{bug:<22} {name:<22} "
                  f"{'detected' if detected else 'ESCAPED':<9} {elapsed:>6.1f}s  {detail}")
            if verbose and not detected:
                print(log)
        if not caught_by:
            escaped.append(bug)
    print()
    total = len(mutations)
    print(f"mutation score: {total - len(escaped)}/{total} faults detected")
    if escaped:
        print(f"ESCAPED: {', '.join(escaped)}")
        return 1
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--seed", type=int, default=1, help="stimulus seed")
    ap.add_argument("--scale", type=float, default=1.0,
                    help="multiply every stimulus count (default 1.0)")
    ap.add_argument("--filter", help="only run tests whose name contains this")
    ap.add_argument("--list", action="store_true", help="list tests and exit")
    ap.add_argument("--mutation", action="store_true",
                    help="check that each injected fault is detected")
    ap.add_argument("--verbose", action="store_true",
                    help="print the full log of anything unexpected")
    args = ap.parse_args()

    tests = all_tests()
    if args.list:
        for t in tests:
            print(f"{t.name:<20} {t.sim:<10} {' '.join(t.tags)}")
        return 0

    cfg = Config(seed=args.seed, scale=args.scale)

    if args.mutation:
        mutations = MUTATIONS
        if args.filter:
            mutations = [m for m in MUTATIONS if args.filter in m[0]]
        # Faults show up almost immediately, so the long random runs are wasted
        # here unless the caller asks for them.
        if args.scale == 1.0:
            cfg.scale = 0.05
        return run_mutations(tests, cfg, mutations, args.verbose)

    if args.filter:
        tests = [t for t in tests if args.filter in t.name]
    if not tests:
        print("no tests matched")
        return 1
    return run_regression(tests, cfg, args.verbose)


if __name__ == "__main__":
    sys.exit(main())
