#!/usr/bin/env python3
"""Model of a small generic standard-cell library.

This module is the single source of truth for the library in two forms:

  * `emit_liberty()` produces the Liberty file that Yosys and ABC map against.
  * `arc_delay()`, `ck_to_q()` and friends provide the same delays to
    scripts/sta.py.

Keeping both in one place means the netlist Yosys produces and the timing
scripts/sta.py reports cannot describe different libraries.

The numbers are synthetic. They are shaped like a 45nm-class library so that
relative comparisons between RTL implementations are meaningful, but they are
not calibrated against any real process: absolute frequencies mean nothing
outside this repository.

Delays are in nanoseconds, capacitances in picofarads, area in arbitrary units.
"""

import argparse
import sys
from dataclasses import dataclass, field

# Lookup table axes shared by every timing arc in the library.
TRANSITION_INDEX = (0.010, 0.200)  # input slew
LOAD_INDEX = (0.0012, 0.0250)  # output capacitance

# Multipliers applied to a cell's base delay to fill its 2x2 table:
#   [fast input edge][light load], [fast][heavy]
#   [slow input edge][light load], [slow][heavy]
TABLE_SHAPE = ((1.00, 1.85), (1.30, 2.20))

INPUT_CAP = 0.0012
CLOCK_CAP = 0.0025
MAX_CAP = 0.050

# Load assumed on a module output port, so driving a port is not free.
OUTPUT_PORT_LOAD = 0.0040

DFF_CK_TO_Q = 0.075
DFF_SETUP = 0.035
DFF_HOLD = 0.010


@dataclass(frozen=True)
class CombCell:
    area: float
    base_delay: float
    function: str
    # Input pin -> Liberty timing_sense, in the order they appear on the cell.
    pins: dict = field(default_factory=dict)


@dataclass(frozen=True)
class SeqCell:
    area: float
    has_reset: bool


COMB_CELLS = {
    "INV_X1":   CombCell(1.0, 0.012, "A'",             {"A": "negative_unate"}),
    "BUF_X1":   CombCell(2.0, 0.016, "A",              {"A": "positive_unate"}),
    "NAND2_X1": CombCell(2.0, 0.024, "(A B)'",         {"A": "negative_unate", "B": "negative_unate"}),
    "NAND3_X1": CombCell(3.0, 0.033, "(A B C)'",       {"A": "negative_unate", "B": "negative_unate", "C": "negative_unate"}),
    "NOR2_X1":  CombCell(2.0, 0.028, "(A+B)'",         {"A": "negative_unate", "B": "negative_unate"}),
    "NOR3_X1":  CombCell(3.0, 0.040, "(A+B+C)'",       {"A": "negative_unate", "B": "negative_unate", "C": "negative_unate"}),
    "AND2_X1":  CombCell(3.0, 0.032, "(A B)",          {"A": "positive_unate", "B": "positive_unate"}),
    "OR2_X1":   CombCell(3.0, 0.034, "(A+B)",          {"A": "positive_unate", "B": "positive_unate"}),
    "XOR2_X1":  CombCell(5.0, 0.058, "(A^B)",          {"A": "non_unate", "B": "non_unate"}),
    "XNOR2_X1": CombCell(5.0, 0.056, "(A^B)'",         {"A": "non_unate", "B": "non_unate"}),
    "AOI21_X1": CombCell(4.0, 0.036, "((A1 A2)+B)'",   {"A1": "negative_unate", "A2": "negative_unate", "B": "negative_unate"}),
    "OAI21_X1": CombCell(4.0, 0.038, "((A1+A2) B)'",   {"A1": "negative_unate", "A2": "negative_unate", "B": "negative_unate"}),
    "MUX2_X1":  CombCell(6.0, 0.052, "(A S') + (B S)", {"A": "positive_unate", "B": "positive_unate", "S": "non_unate"}),
}

SEQ_CELLS = {
    "DFF_X1": SeqCell(10.0, has_reset=False),
    "DFFR_X1": SeqCell(11.0, has_reset=True),
}

# Pin roles for the sequential cells, used by the timing analyser.
SEQ_CLOCK_PIN = "CK"
SEQ_DATA_PIN = "D"
SEQ_OUTPUT_PIN = "Q"
SEQ_RESET_PIN = "RN"


def is_sequential(cell_type: str) -> bool:
    return cell_type in SEQ_CELLS


def area(cell_type: str) -> float:
    if cell_type in COMB_CELLS:
        return COMB_CELLS[cell_type].area
    return SEQ_CELLS[cell_type].area


def output_pin(cell_type: str) -> str:
    return SEQ_OUTPUT_PIN if is_sequential(cell_type) else "Y"


def input_pins(cell_type: str):
    if cell_type in COMB_CELLS:
        return list(COMB_CELLS[cell_type].pins)
    return [SEQ_DATA_PIN, SEQ_CLOCK_PIN] + (
        [SEQ_RESET_PIN] if SEQ_CELLS[cell_type].has_reset else []
    )


def input_cap(cell_type: str, pin: str) -> float:
    if is_sequential(cell_type):
        return CLOCK_CAP if pin == SEQ_CLOCK_PIN else INPUT_CAP
    return INPUT_CAP


def _pin_scale(cell_type: str, pin: str) -> float:
    """Later inputs of a gate are marginally slower than the first."""
    return 1.0 + 0.05 * list(COMB_CELLS[cell_type].pins).index(pin)


def _interpolate_load(low: float, high: float, load: float) -> float:
    load = min(max(load, 0.0), MAX_CAP)
    span = LOAD_INDEX[1] - LOAD_INDEX[0]
    frac = (load - LOAD_INDEX[0]) / span
    return low + (high - low) * frac


def arc_delay(cell_type: str, pin: str, load: float) -> float:
    """Delay from `pin` to the cell output at the given output load.

    Evaluated on the slow-input-slew row of the table, which is the pessimistic
    corner. A full analyser would propagate the actual slew; this one does not,
    which is the largest single simplification in the timing flow.
    """
    base = COMB_CELLS[cell_type].base_delay * _pin_scale(cell_type, pin)
    return _interpolate_load(base * TABLE_SHAPE[1][0], base * TABLE_SHAPE[1][1], load)


def ck_to_q(load: float) -> float:
    return _interpolate_load(
        DFF_CK_TO_Q * TABLE_SHAPE[1][0], DFF_CK_TO_Q * TABLE_SHAPE[1][1], load
    )


def _table(group: str, base: float, indent: str = "        ") -> str:
    rows = ", ".join(
        '"' + ", ".join(f"{base * m:.4f}" for m in row) + '"' for row in TABLE_SHAPE
    )
    return f"{indent}{group}(delay_2x2) {{ values({rows}); }}"


def _constraint(group: str, base: float, indent: str = "        ") -> str:
    shape = ((1.00, 1.15), (1.10, 1.30))
    rows = ", ".join(
        '"' + ", ".join(f"{base * m:.4f}" for m in row) + '"' for row in shape
    )
    return f"{indent}{group}(constraint_2x2) {{ values({rows}); }}"


def _comb_cell_liberty(name: str, cell: CombCell) -> str:
    lines = [f"  cell({name}) {{", f"    area : {cell.area};"]
    for pin in cell.pins:
        lines.append(f"    pin({pin}) {{ direction : input; capacitance : {INPUT_CAP}; }}")
    lines.append("    pin(Y) {")
    lines.append(
        f'      direction : output; function : "{cell.function}"; '
        f"max_capacitance : {MAX_CAP};"
    )
    for pin, sense in cell.pins.items():
        d = cell.base_delay * _pin_scale(name, pin)
        lines.append(f'      timing() {{ related_pin : "{pin}"; timing_sense : {sense};')
        lines.append(_table("cell_rise", d))
        lines.append(_table("cell_fall", d * 0.90))
        lines.append(_table("rise_transition", d * 0.80))
        lines.append(_table("fall_transition", d * 0.70))
        lines.append("      }")
    lines += ["    }", "  }"]
    return "\n".join(lines)


def _seq_cell_liberty(name: str, cell: SeqCell) -> str:
    lines = [f"  cell({name}) {{", f"    area : {cell.area};", "    ff(IQ, IQN) {"]
    lines.append(f'      clocked_on : "{SEQ_CLOCK_PIN}"; next_state : "{SEQ_DATA_PIN}";')
    if cell.has_reset:
        lines.append(f"      clear : \"{SEQ_RESET_PIN}'\";")
    lines.append("    }")
    lines.append(
        f"    pin({SEQ_CLOCK_PIN}) {{ direction : input; clock : true; "
        f"capacitance : {CLOCK_CAP}; }}"
    )
    if cell.has_reset:
        lines.append(
            f"    pin({SEQ_RESET_PIN}) {{ direction : input; capacitance : {INPUT_CAP}; }}"
        )
    lines.append(f"    pin({SEQ_DATA_PIN}) {{ direction : input; capacitance : {INPUT_CAP};")
    for kind, value in (("setup_rising", DFF_SETUP), ("hold_rising", DFF_HOLD)):
        lines.append(f'      timing() {{ related_pin : "{SEQ_CLOCK_PIN}"; timing_type : {kind};')
        lines.append(_constraint("rise_constraint", value))
        lines.append(_constraint("fall_constraint", value))
        lines.append("      }")
    lines.append("    }")
    lines.append(
        f'    pin({SEQ_OUTPUT_PIN}) {{ direction : output; function : "IQ"; '
        f"max_capacitance : {MAX_CAP};"
    )
    lines.append(
        f'      timing() {{ related_pin : "{SEQ_CLOCK_PIN}"; timing_type : rising_edge;'
    )
    lines.append(_table("cell_rise", DFF_CK_TO_Q))
    lines.append(_table("cell_fall", DFF_CK_TO_Q * 0.94))
    lines.append(_table("rise_transition", 0.014))
    lines.append(_table("fall_transition", 0.012))
    lines += ["      }", "    }", "  }"]
    return "\n".join(lines)


def emit_liberty() -> str:
    header = f"""library(generic_45) {{
  delay_model : table_lookup;
  time_unit : "1ns";
  voltage_unit : "1V";
  current_unit : "1mA";
  capacitive_load_unit (1, pf);
  default_input_pin_cap : {INPUT_CAP};
  default_output_pin_cap : 0.0;
  default_inout_pin_cap : {INPUT_CAP};
  default_fanout_load : 1.0;
  default_max_transition : 0.500;

  lu_table_template(delay_2x2) {{
    variable_1 : input_net_transition;
    variable_2 : total_output_net_capacitance;
    index_1 ("{TRANSITION_INDEX[0]:.3f}, {TRANSITION_INDEX[1]:.3f}");
    index_2 ("{LOAD_INDEX[0]:.4f}, {LOAD_INDEX[1]:.4f}");
  }}
  lu_table_template(constraint_2x2) {{
    variable_1 : related_pin_transition;
    variable_2 : constrained_pin_transition;
    index_1 ("{TRANSITION_INDEX[0]:.3f}, {TRANSITION_INDEX[1]:.3f}");
    index_2 ("{TRANSITION_INDEX[0]:.3f}, {TRANSITION_INDEX[1]:.3f}");
  }}
"""
    parts = [header]
    parts += [_comb_cell_liberty(n, c) for n, c in COMB_CELLS.items()]
    parts += [_seq_cell_liberty(n, c) for n, c in SEQ_CELLS.items()]
    parts.append("}")
    return "\n".join(parts) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser(description="Emit the generic library as Liberty.")
    ap.add_argument("-o", "--output", help="output path (default: stdout)")
    args = ap.parse_args()
    text = emit_liberty()
    if args.output:
        with open(args.output, "w") as f:
            f.write(text)
    else:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
