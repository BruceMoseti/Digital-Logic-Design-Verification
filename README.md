# Digital Logic Design & Verification

RTL in SystemVerilog and Verilog, verified with reusable testbenches, C++
reference models and SystemVerilog assertions, and measured through a synthesis
and static-timing flow that is used to drive RTL changes rather than just to
produce a number.

Everything here runs from open-source tools; there is no vendor flow and nothing
to license.

```
make test      # 11 tests across Icarus, Verilator and Python, ~14 s
make mutation  # inject 9 RTL faults, require the suite to catch each, ~26 s
make synth     # map to a cell library and report area and timing, ~6 min
make all       # all of the above
```

## Designs

| module | language | what it is |
| --- | --- | --- |
| [`rtl/alu.v`](rtl/alu.v) | Verilog | 10-operation ALU, parameterised width, carry/overflow/zero/negative flags |
| [`rtl/sync_fifo.sv`](rtl/sync_fifo.sv) | SystemVerilog | synchronous FIFO, parameterised width and depth, show-ahead read |
| [`rtl/fir8_direct.sv`](rtl/fir8_direct.sv) | SystemVerilog | 8-tap FIR, programmable coefficients, single-cycle datapath |
| [`rtl/fir8_pipelined.sv`](rtl/fir8_pipelined.sv) | SystemVerilog | the same FIR retimed into four stages |

The two FIR modules are deliberately the same function built two ways. They are
checked against one golden model and compared head to head in synthesis, which
is what makes the timing work in [`docs/timing.md`](docs/timing.md) meaningful
instead of decorative.

## How it is verified

Four independent mechanisms, chosen so that no single misunderstanding can pass
all of them:

**Directed tests with hand-computed expectations.** `verif/alu_tb.sv` holds 35
vectors covering signed overflow at both ends of the range, borrow, arithmetic
versus logical shifts, shift amounts at and beyond the operand width, signed
versus unsigned comparison, and the undefined opcodes. Expected values are
derived by hand from the specification, which is what anchors the C++ model
itself. `verif/fifo_tb.sv` covers fill, drain, writing while full, reading while
empty, concurrent read and write at both boundaries, pointer wrap, and reset in
the middle of traffic.

**Randomised tests with a reference model.** The FIFO testbench drives randomised
traffic against a queue model, checking read data, occupancy and both flags every
cycle. It sweeps read and write pressure so the FIFO spends time at both
boundaries rather than hovering near half full, and it *fails* if the run never
reached full, never reached empty, never had a concurrent read and write, or
never wrapped the pointer. A random test that quietly stopped exercising the
interesting states would otherwise keep passing forever.

**C++ golden models under Verilator.** `verif/cpp/golden.cpp` implements the ALU
and the FIR from their specifications, independently of the RTL. At `W=8` the ALU
harness sweeps **all 1,048,576 combinations** of `(a, b, op)`, which is a
complete check of the mapped function rather than a sample of it; `W=32` runs
2 M random vectors with corner values mixed in. Both FIR variants run against the
same model through one harness.

**SystemVerilog assertions, attached with `bind`.** Properties live in
`verif/sva/` and are bound onto the DUTs, so no verification code sits in the
RTL. They state invariants that hold for any correct implementation rather than
recomputing the expected result: an arithmetic shift preserves the sign, `AND`
returns a subset of both operands, occupancy never exceeds capacity, occupancy
moves by at most one per cycle. The FIFO properties reach through the bind into
`wr_ptr` and `rd_ptr` to check occupancy against the pointers, which localises a
pointer fault to the cycle it happens on.

### Does the suite actually work?

`make mutation` answers that with evidence rather than assertion. It injects nine
faults into the RTL one at a time and requires the tests that should notice to
fail:

```
mutation score: 9/9 faults detected
```

The faults are realistic slips: a logical shift where an arithmetic one belongs,
the addition overflow rule applied to subtraction, a shift amount masked one bit
too narrow, a FIFO that ignores `full`, a read pointer incrementing by two, an
occupancy counter that forgets the concurrent-access case, a dropped FIR tap, an
unsigned coefficient, and `out_valid` asserted at the wrong time. The report
shows which mechanism caught each one — some by scoreboard mismatch, some by
golden-model comparison, some by a named assertion.

## Two simulators, one testbench

`verif/fifo_tb.sv` runs under both Icarus Verilog and Verilator. That is why
`verif/tb_pkg.sv` carries a small xorshift generator instead of using
`$urandom`: a given seed then produces bit-identical stimulus under either
simulator, so a seed that fails in one reproduces in the other. 200,000 random
cycles, same seed:

| simulator | wall time | throughput | result |
| --- | --- | --- | --- |
| Icarus Verilog 12.0 | 3.243 s | 62 k cycles/s | 673128 checks, 0 failures |
| Verilator 5.020 (compiled, assertions on) | 0.165 s | 1215 k cycles/s | 673128 checks, 0 failures |

Identical results, 19.7x faster, and the compiled run is doing more work because
the bound assertions are active there. Icarus cannot compile concurrent
assertions, so it runs the testbench semantics; Verilator runs the same
testbench with the properties enabled and carries the long regressions.

## Synthesis and timing

`make synth` maps every design onto the cell library in `syn/cell_library.py`
and analyses the netlist with `scripts/sta.py`.

| design | cells | registers | area | critical path | Fmax |
| --- | --- | --- | --- | --- | --- |
| `alu` (W=32) | 1438 | 0 | 3921 | 1.883 ns (combinational) | n/a |
| `sync_fifo` (8x8) | 280 | 74 | 1584 | 0.663 ns | 1508 MHz |
| `fir8_direct` | 4642 | 76 | 15169 | 2.429 ns | 412 MHz |
| `fir8_pipelined` | 4854 | 311 | 17665 | 1.423 ns | **703 MHz** |

Retiming the FIR bought **1.71x** on the critical path for 16.5% more area.
Getting there took three attempts, and the interesting part is why the obvious
one failed: synthesis fuses all eight multiplies in `fir8_direct` into a single
partial-product reduction with one carry-propagate adder, so a retiming that
tries to preserve that fusion by grouping two taps per register lands *slower*
than cutting at the individual products. Full path listings, measurements for
all three variants, and the honest limitations of the flow are in
[`docs/timing.md`](docs/timing.md).

Two caveats worth reading before quoting any frequency: the cell library is
synthetic, so only the comparisons are meaningful, and the timing analyser is a
single-corner topological one written for this project because no static timing
tool was available. `verif/test_sta.py` validates it against netlists whose
delay can be computed by hand.

## Layout

```
rtl/                 designs, with `ifdef-guarded fault injections
verif/
  tb_pkg.sv          shared testbench classes: xorshift source, checker
  alu_tb.sv          directed edge-case vectors
  fifo_tb.sv         cycle-accurate driver, queue model, coverage gate
  sva/               property modules and their bind statements
  cpp/               C++ golden models and Verilator harnesses
  test_sta.py        self-check for the timing analyser
syn/cell_library.py  cell library: emits Liberty, and answers delay queries
scripts/
  run_regression.py  test definitions, regression and mutation modes
  synth.py           Yosys mapping and the comparison table
  sta.py             static timing analysis over a Yosys JSON netlist
docs/timing.md       synthesis and timing results, and how they were reached
```

`syn/cell_library.py` is the single source of truth for the library: it emits the
Liberty file Yosys and ABC map against, and it answers the delay queries
`scripts/sta.py` makes. The netlist that gets synthesised and the netlist that
gets analysed therefore cannot describe different libraries.

## Prerequisites

Icarus Verilog 12.0, Verilator 5.020, Yosys 0.33 with `yosys-abc`, a C++17
compiler, Python 3.8 or newer (tested on 3.12). On Debian or Ubuntu:

```bash
sudo apt-get install -y iverilog verilator yosys build-essential python3
```

No Python packages beyond the standard library.

## Notes on the tools

Two simulator limitations shaped the code, and both are worth knowing about
before wondering why something is written the way it is:

* Icarus Verilog 12.0 silently drops `x++` on a class property. It compiles and
  runs, but the increment does not stick, which made the checkers report a single
  check no matter how many had run. `verif/tb_pkg.sv` uses `x = x + 1`
  throughout.
* Verilator 5.020 does not support `##` cycle delays in sequence expressions, so
  `verif/sva/fir_props.sv` expresses the expected `out_valid` timing with a
  reference valid pipeline instead of `in_valid |=> ##(LATENCY-1) out_valid`.
