#!/usr/bin/env python3
"""Self-check for scripts/sta.py against netlists whose delay is hand-computable.

The timing comparison between the two FIR implementations is only as trustworthy
as the analyser producing it, so these cases pin the arithmetic down on netlists
small enough to work out by hand. They are written directly as Yosys JSON rather
than synthesised, because synthesis would optimise away a buffer chain built
purely to have a known depth.
"""

import json
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
sys.path.insert(0, os.path.join(ROOT, "syn"))

import cell_library as lib  # noqa: E402
import sta  # noqa: E402

TOL = 1e-9


def netlist(cells, ports):
    return {"modules": {"t": {"ports": ports, "cells": cells, "netnames": {}}}}


def cell(ctype, connections):
    return {"type": ctype, "connections": connections}


def run(design):
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
        json.dump(design, f)
        path = f.name
    try:
        return sta.analyze(path, "t")
    finally:
        os.unlink(path)


def case_single_gate():
    """reg -> NAND2 -> reg: launch + one arc + setup."""
    design = netlist(
        cells={
            "src": cell("DFF_X1", {"CK": [2], "D": [3], "Q": [4]}),
            "g": cell("NAND2_X1", {"A": [4], "B": [4], "Y": [5]}),
            "dst": cell("DFF_X1", {"CK": [2], "D": [5], "Q": [6]}),
        },
        ports={"clk": {"direction": "input", "bits": [2]},
               "o": {"direction": "output", "bits": [6]}},
    )
    r = run(design)

    # Net 4 drives both NAND inputs, so it carries two input pin loads.
    launch = lib.ck_to_q(2 * lib.INPUT_CAP)
    # Net 5 drives one flop data pin.
    arc = max(lib.arc_delay("NAND2_X1", p, lib.INPUT_CAP) for p in ("A", "B"))
    expected = launch + arc + lib.DFF_SETUP

    got = r["worst"][sta.REG2REG]["delay"]
    assert abs(got - expected) < TOL, f"single gate: got {got}, expected {expected}"
    assert abs(r["fmax_mhz"] - 1000.0 / expected) < 1e-6
    assert r["sequential"] == 2 and r["combinational"] == 1
    assert abs(r["area"] - (2 * lib.SEQ_CELLS["DFF_X1"].area + lib.COMB_CELLS["NAND2_X1"].area)) < TOL
    return expected


def case_inverter_chain():
    """reg -> INV -> INV -> INV -> reg accumulates three arcs."""
    design = netlist(
        cells={
            "src": cell("DFF_X1", {"CK": [2], "D": [3], "Q": [10]}),
            "i0": cell("INV_X1", {"A": [10], "Y": [11]}),
            "i1": cell("INV_X1", {"A": [11], "Y": [12]}),
            "i2": cell("INV_X1", {"A": [12], "Y": [13]}),
            "dst": cell("DFF_X1", {"CK": [2], "D": [13], "Q": [14]}),
        },
        ports={"clk": {"direction": "input", "bits": [2]},
               "o": {"direction": "output", "bits": [14]}},
    )
    r = run(design)

    inv = lib.arc_delay("INV_X1", "A", lib.INPUT_CAP)
    expected = lib.ck_to_q(lib.INPUT_CAP) + 3 * inv + lib.DFF_SETUP
    got = r["worst"][sta.REG2REG]["delay"]
    assert abs(got - expected) < TOL, f"chain: got {got}, expected {expected}"
    assert len(r["critical"]["hops"]) == 3, r["critical"]["hops"]
    return expected


def case_combinational_only():
    """No registers: no Fmax, and the path is classified input to output."""
    design = netlist(
        cells={"g": cell("XOR2_X1", {"A": [2], "B": [3], "Y": [4]})},
        ports={
            "a": {"direction": "input", "bits": [2]},
            "b": {"direction": "input", "bits": [3]},
            "y": {"direction": "output", "bits": [4]},
        },
    )
    r = run(design)
    assert r["fmax_mhz"] is None, "combinational design should report no Fmax"
    assert sta.IN2OUT in r["worst"]
    expected = lib.arc_delay("XOR2_X1", "B", lib.OUTPUT_PORT_LOAD)
    got = r["worst"][sta.IN2OUT]["delay"]
    assert abs(got - expected) < TOL, f"comb: got {got}, expected {expected}"
    return expected


def case_load_dependence():
    """A gate driving eight sinks must be slower than one driving a single sink."""
    def build(fanout):
        cells = {
            "src": cell("DFF_X1", {"CK": [2], "D": [3], "Q": [10]}),
            "g": cell("INV_X1", {"A": [10], "Y": [11]}),
        }
        for i in range(fanout):
            cells[f"dst{i}"] = cell("DFF_X1", {"CK": [2], "D": [11], "Q": [20 + i]})
        ports = {"clk": {"direction": "input", "bits": [2]}}
        return netlist(cells, ports)

    light = run(build(1))["worst"][sta.REG2REG]["delay"]
    heavy = run(build(8))["worst"][sta.REG2REG]["delay"]
    assert heavy > light, f"fanout of 8 ({heavy}) should be slower than 1 ({light})"
    return heavy - light


def case_loop_detected():
    design = netlist(
        cells={
            "g0": cell("INV_X1", {"A": [30], "Y": [31]}),
            "g1": cell("INV_X1", {"A": [31], "Y": [30]}),
        },
        ports={"o": {"direction": "output", "bits": [31]}},
    )
    try:
        run(design)
    except sta.CombinationalLoop:
        return True
    raise AssertionError("combinational loop was not detected")


def main():
    checks = [
        ("single gate", case_single_gate),
        ("inverter chain", case_inverter_chain),
        ("combinational only", case_combinational_only),
        ("load dependence", case_load_dependence),
        ("loop detection", case_loop_detected),
    ]
    failures = 0
    for name, fn in checks:
        try:
            value = fn()
            print(f"[ok]   {name}: {value}")
        except AssertionError as exc:
            failures += 1
            print(f"[FAIL] {name}: {exc}")
    print(f"[{'PASS' if failures == 0 else 'FAIL'}] sta_selfcheck: "
          f"{len(checks)} checks, {failures} failures")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
