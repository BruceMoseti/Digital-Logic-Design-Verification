#!/usr/bin/env python3
"""Synthesise each design to the generic library and report area and timing.

Runs Yosys to map the RTL onto syn/cell_library.py's cell set, then analyses the
resulting netlist with scripts/sta.py. The point of the exercise is the last two
rows of the table: fir8_direct and fir8_pipelined implement the same function, so
the difference in area and Fmax is the cost and benefit of the retiming.
"""

import argparse
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
sys.path.insert(0, os.path.join(ROOT, "syn"))

import cell_library  # noqa: E402
import sta  # noqa: E402

DESIGNS = {
    "alu": "rtl/alu.v",
    "sync_fifo": "rtl/sync_fifo.sv",
    "fir8_direct": "rtl/fir8_direct.sv",
    "fir8_pipelined": "rtl/fir8_pipelined.sv",
}

BUILD = os.path.join(ROOT, "build")


def liberty_path():
    os.makedirs(BUILD, exist_ok=True)
    path = os.path.join(BUILD, "generic.lib")
    with open(path, "w") as f:
        f.write(cell_library.emit_liberty())
    return path


def synthesize(top, source, lib):
    netlist = os.path.join(BUILD, f"{top}.netlist.json")
    script = "; ".join(
        [
            f"read_verilog -sv {os.path.join(ROOT, source)}",
            f"synth -top {top} -flatten",
            f"dfflibmap -liberty {lib}",
            f"abc -liberty {lib}",
            "opt_clean",
            f"write_json {netlist}",
        ]
    )
    proc = subprocess.run(
        ["yosys", "-q", "-p", script], capture_output=True, text=True, cwd=ROOT
    )
    if proc.returncode != 0:
        sys.stderr.write(proc.stdout + proc.stderr)
        raise SystemExit(f"yosys failed for {top}")
    return netlist


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--top", action="append", choices=sorted(DESIGNS),
                    help="design to synthesise (default: all)")
    ap.add_argument("--paths", action="store_true", help="also print critical paths")
    args = ap.parse_args()

    tops = args.top or list(DESIGNS)
    lib = liberty_path()

    results = {}
    for top in tops:
        netlist = synthesize(top, DESIGNS[top], lib)
        results[top] = sta.analyze(netlist, top)

    header = f"{'design':<16} {'cells':>6} {'seq':>5} {'area':>9} {'critical':>10} {'path':>15} {'fmax':>10}"
    print(header)
    print("-" * len(header))
    for top in tops:
        r = results[top]
        crit = r["critical"]
        fmax = f"{r['fmax_mhz']:.0f} MHz" if r["fmax_mhz"] else "n/a"
        print(
            f"{top:<16} {r['cells']:>6} {r['sequential']:>5} {r['area']:>9.1f} "
            f"{crit['delay']:>7.3f} ns {crit['kind']:>15} {fmax:>10}"
        )

    if "fir8_direct" in results and "fir8_pipelined" in results:
        d, p = results["fir8_direct"], results["fir8_pipelined"]
        print()
        print("fir8_direct -> fir8_pipelined:")
        print(f"  critical path  {d['critical']['delay']:.3f} ns -> "
              f"{p['critical']['delay']:.3f} ns "
              f"({d['critical']['delay'] / p['critical']['delay']:.2f}x faster)")
        print(f"  fmax           {d['fmax_mhz']:.0f} MHz -> {p['fmax_mhz']:.0f} MHz")
        print(f"  area           {d['area']:.0f} -> {p['area']:.0f} "
              f"({100.0 * (p['area'] - d['area']) / d['area']:+.1f}%)")
        print(f"  registers      {d['sequential']} -> {p['sequential']}")

    if args.paths:
        for top in tops:
            print()
            print("=" * 72)
            print(sta.format_report(results[top]))

    return 0


if __name__ == "__main__":
    sys.exit(main())
