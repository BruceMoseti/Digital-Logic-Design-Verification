#!/usr/bin/env python3
"""Static timing analysis of a Yosys JSON netlist mapped to the generic library.

Written because no static timing tool is available in this environment; it is
deliberately a teaching-grade analyser, and its simplifications are worth being
explicit about:

  * one timing corner, and every arc is evaluated on the pessimistic
    slow-input-slew row of the cell table rather than propagating actual slews
  * capacitive load is the sum of the sink pin capacitances; no wire RC
  * the clock is treated as ideal, so no skew, jitter or insertion delay
  * setup checks only, and no clock-domain or reset-recovery analysis

What it does do is find the true longest topological path through the mapped
netlist, which is what makes two implementations of the same function
comparable.

Fmax is taken from the worst path that ends at a register, which includes paths
starting at an input port: input ports are treated as arriving at time zero, the
equivalent of `set_input_delay 0`. Restricting Fmax to register-to-register
paths would be wrong for a design like the FIR, whose coefficient bus and sample
input feed the multipliers directly -- its longest path to a register starts at a
port. Paths that end at an output port are reported but never constrain Fmax,
since that needs an output delay budget this flow does not have.
"""

import argparse
import json
import os
import sys
from collections import defaultdict

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "syn"))
import cell_library as lib  # noqa: E402

REG2REG = "reg-to-reg"
IN2REG = "input-to-reg"
REG2OUT = "reg-to-output"
IN2OUT = "input-to-output"


class CombinationalLoop(Exception):
    pass


def _bit_key(bit):
    """Yosys emits constants as strings ('0', '1', 'x') and nets as integers."""
    return f"c:{bit}" if isinstance(bit, str) else int(bit)


def _is_const(key):
    return isinstance(key, str)


class Netlist:
    def __init__(self, module):
        self.module = module
        self.drivers = {}
        self.sinks = defaultdict(list)
        self.input_bits = {}
        self.output_bits = {}
        self.names = {}

        for name, port in module.get("ports", {}).items():
            for idx, bit in enumerate(port["bits"]):
                key = _bit_key(bit)
                label = f"{name}[{idx}]" if len(port["bits"]) > 1 else name
                if port["direction"] in ("input", "inout"):
                    self.input_bits[key] = label
                if port["direction"] in ("output", "inout"):
                    self.output_bits[key] = label
                self.names[key] = label

        for name, net in module.get("netnames", {}).items():
            for idx, bit in enumerate(net["bits"]):
                key = _bit_key(bit)
                if key in self.names and net.get("hide_name", 0):
                    continue
                label = f"{name}[{idx}]" if len(net["bits"]) > 1 else name
                self.names.setdefault(key, label)

        for inst, cell in module.get("cells", {}).items():
            ctype = cell["type"]
            if ctype not in lib.COMB_CELLS and not lib.is_sequential(ctype):
                raise ValueError(f"cell {inst} has unmapped type {ctype}")
            out = lib.output_pin(ctype)
            for pin, bits in cell["connections"].items():
                for bit in bits:
                    key = _bit_key(bit)
                    if pin == out:
                        self.drivers[key] = (inst, ctype, pin)
                    else:
                        self.sinks[key].append((inst, ctype, pin))

        self.load = {}
        for key, sink_list in self.sinks.items():
            self.load[key] = sum(lib.input_cap(t, p) for _, t, p in sink_list)
        for key in self.output_bits:
            self.load[key] = self.load.get(key, 0.0) + lib.OUTPUT_PORT_LOAD

    def net_label(self, key):
        if _is_const(key):
            return f"const({key[2:]})"
        return self.names.get(key, f"net{key}")

    def cell_load(self, key):
        return self.load.get(key, lib.OUTPUT_PORT_LOAD)


def analyze(netlist_path, top=None):
    with open(netlist_path) as f:
        design = json.load(f)

    modules = design.get("modules", {})
    if top is None:
        if len(modules) != 1:
            raise ValueError(f"specify --top, netlist has {sorted(modules)}")
        top = next(iter(modules))
    nl = Netlist(modules[top])

    cells = modules[top].get("cells", {})
    seq_cells = {i: c for i, c in cells.items() if lib.is_sequential(c["type"])}
    comb_cells = {i: c for i, c in cells.items() if not lib.is_sequential(c["type"])}

    # arrival[net] = (time, origin, previous hop)
    arrival = {}
    origin = {}
    prev = {}

    def seed(key, time, origin_desc):
        arrival[key] = time
        origin[key] = origin_desc
        prev[key] = None

    for key in nl.input_bits:
        seed(key, 0.0, ("input", nl.input_bits[key]))
    for key in list(nl.sinks) + list(nl.drivers):
        if _is_const(key):
            seed(key, 0.0, ("const", nl.net_label(key)))

    for inst, cell in seq_cells.items():
        for bit in cell["connections"].get(lib.SEQ_OUTPUT_PIN, []):
            key = _bit_key(bit)
            seed(key, lib.ck_to_q(nl.cell_load(key)), ("reg", inst))

    # Any net without a driver that is not already seeded is dangling; treat it
    # as arriving at time zero so one loose end cannot stall the whole sweep.
    for key in list(nl.sinks):
        if key not in arrival and key not in nl.drivers:
            seed(key, 0.0, ("undriven", nl.net_label(key)))

    pending = dict(comb_cells)
    while pending:
        progressed = False
        for inst in list(pending):
            cell = pending[inst]
            ctype = cell["type"]
            out_pin = lib.output_pin(ctype)
            in_bits = [
                (pin, _bit_key(bit))
                for pin, bits in cell["connections"].items()
                if pin != out_pin
                for bit in bits
            ]
            if any(key not in arrival for _, key in in_bits):
                continue
            out_bits = [_bit_key(b) for b in cell["connections"].get(out_pin, [])]
            for out_key in out_bits:
                load = nl.cell_load(out_key)
                best_time = -1.0
                best = None
                for pin, key in in_bits:
                    t = arrival[key] + lib.arc_delay(ctype, pin, load)
                    if t > best_time:
                        best_time = t
                        best = (key, pin)
                arrival[out_key] = best_time
                origin[out_key] = origin[best[0]]
                prev[out_key] = (best[0], inst, ctype, best[1], best_time - arrival[best[0]])
            del pending[inst]
            progressed = True
        if not progressed:
            raise CombinationalLoop(
                "combinational loop involving: " + ", ".join(sorted(pending)[:10])
            )

    endpoints = []
    for inst, cell in seq_cells.items():
        for bit in cell["connections"].get(lib.SEQ_DATA_PIN, []):
            key = _bit_key(bit)
            if key not in arrival:
                continue
            kind = REG2REG if origin[key][0] == "reg" else IN2REG
            endpoints.append(
                {
                    "kind": kind,
                    "delay": arrival[key] + lib.DFF_SETUP,
                    "setup": lib.DFF_SETUP,
                    "net": key,
                    "endpoint": f"{inst}/{lib.SEQ_DATA_PIN}",
                }
            )
    for key, label in nl.output_bits.items():
        if key not in arrival:
            continue
        kind = REG2OUT if origin[key][0] == "reg" else IN2OUT
        endpoints.append(
            {
                "kind": kind,
                "delay": arrival[key],
                "setup": 0.0,
                "net": key,
                "endpoint": label,
            }
        )

    def path_of(key):
        hops = []
        cur = key
        while prev.get(cur) is not None:
            src, inst, ctype, pin, delay = prev[cur]
            hops.append(
                {
                    "cell": inst,
                    "type": ctype,
                    "pin": pin,
                    "delay": delay,
                    "net": nl.net_label(cur),
                }
            )
            cur = src
        hops.reverse()
        return origin[key], hops, cur

    worst = {}
    for ep in endpoints:
        cur = worst.get(ep["kind"])
        if cur is None or ep["delay"] > cur["delay"]:
            worst[ep["kind"]] = ep

    for ep in worst.values():
        start, hops, start_net = path_of(ep["net"])
        ep["start"] = start
        ep["hops"] = hops
        # Launch time is the arrival already computed for the start net, which
        # is the CK->Q delay for a register and zero for an input port.
        ep["launch"] = arrival[start_net]

    # Anything ending at a register is timed against the clock period; output
    # ports are not, so they only become the reported critical path when the
    # design has no registers at all.
    to_register = [worst[k] for k in (REG2REG, IN2REG) if k in worst]
    if to_register:
        critical = max(to_register, key=lambda ep: ep["delay"])
        fmax = 1000.0 / critical["delay"]
    else:
        to_output = [worst[k] for k in (IN2OUT, REG2OUT) if k in worst]
        critical = max(to_output, key=lambda ep: ep["delay"]) if to_output else None
        fmax = None

    return {
        "top": top,
        "cells": len(cells),
        "sequential": len(seq_cells),
        "combinational": len(comb_cells),
        "area": sum(lib.area(c["type"]) for c in cells.values()),
        "worst": worst,
        "critical": critical,
        "fmax_mhz": fmax,
    }


def format_report(result, show_path=True, max_hops=40):
    out = []
    out.append(f"module            : {result['top']}")
    out.append(
        f"cells             : {result['cells']} "
        f"({result['combinational']} combinational, {result['sequential']} sequential)"
    )
    out.append(f"area              : {result['area']:.1f}")
    for kind in (REG2REG, IN2REG, REG2OUT, IN2OUT):
        ep = result["worst"].get(kind)
        if ep:
            out.append(f"worst {kind:<14}: {ep['delay']:.3f} ns  -> {ep['endpoint']}")
    if result["fmax_mhz"] is not None:
        out.append(f"fmax              : {result['fmax_mhz']:.1f} MHz")
    else:
        out.append("fmax              : n/a (no paths end at a register)")

    if show_path and result["critical"]:
        ep = result["critical"]
        out.append("")
        out.append(f"critical path ({ep['kind']}), {ep['delay']:.3f} ns:")
        kind, name = ep["start"]
        running = ep["launch"]
        if kind == "reg":
            out.append(f"  {'launch':<10} {running:>7.3f}  {name} CK->Q")
        else:
            out.append(f"  {'start':<10} {running:>7.3f}  {name} ({kind})")
        for hop in ep["hops"]:
            running += hop["delay"]
            out.append(
                f"  {hop['type']:<10} {hop['delay']:>7.3f}  {running:>7.3f}  {hop['net']}"
            )
            if len(out) > max_hops + 12:
                out.append(f"  ... {len(hops)} stages total")
                break
        if ep["setup"]:
            running += ep["setup"]
            out.append(f"  {'setup':<10} {ep['setup']:>7.3f}  {running:>7.3f}  {ep['endpoint']}")
    return "\n".join(out)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("netlist", help="Yosys JSON netlist")
    ap.add_argument("--top", help="module to analyse")
    ap.add_argument("--no-path", action="store_true", help="omit the path listing")
    args = ap.parse_args()

    try:
        result = analyze(args.netlist, args.top)
    except (CombinationalLoop, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(format_report(result, show_path=not args.no_path))
    return 0


if __name__ == "__main__":
    sys.exit(main())
