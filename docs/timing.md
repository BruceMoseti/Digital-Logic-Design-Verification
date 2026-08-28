# Synthesis and timing results

Reproduce with `make synth`, or `make paths` for the full critical-path
listings. Every number below came out of that flow.

## What the flow is, and what it is not

`scripts/synth.py` maps each design with Yosys onto the cell set defined in
`syn/cell_library.py`, then analyses the resulting netlist with
`scripts/sta.py`.

Two things are worth being blunt about:

* **The library is synthetic.** Its delays are shaped like a 45nm-class library,
  but they are invented. Absolute frequencies mean nothing outside this
  repository; the comparisons between designs mapped with the same library do.
* **The timing analyser is teaching-grade.** One corner, every arc taken from
  the pessimistic slow-slew row of the cell table instead of propagating real
  slews, load from sink pin capacitance with no wire RC, an ideal clock, and
  setup checks only. It does find the true longest topological path through the
  mapped netlist, which is what makes two implementations comparable.

No static timing tool was available in this environment, which is why the
analyser exists at all. `verif/test_sta.py` checks it against netlists whose
delay can be worked out by hand, so the numbers below rest on something.

Fmax is taken from the worst path that *ends at a register*, with input ports
treated as arriving at time zero (`set_input_delay 0`). That detail matters: the
first version of the analyser reported Fmax from register-to-register paths
only, which hid the FIR's real critical path, because the coefficient bus and
sample input feed the multipliers directly from module ports.

## Results

| design | cells | registers | area | critical path | | Fmax |
| --- | --- | --- | --- | --- | --- | --- |
| `alu` (W=32) | 1438 | 0 | 3921 | 1.883 ns | input to output | n/a |
| `sync_fifo` (8x8) | 280 | 74 | 1584 | 0.663 ns | register to register | 1508 MHz |
| `fir8_direct` | 4642 | 76 | 15169 | 2.429 ns | input to register | 412 MHz |
| `fir8_pipelined` | 4854 | 311 | 17665 | 1.423 ns | register to register | 703 MHz |

The ALU has no registers, so it has no Fmax; 1.883 ns is its combinational
delay. Its critical path ends at the `zero` flag rather than at `y`, because
`zero` is a wide NOR reduction sitting behind the adder. If this ALU were ever
placed in a pipeline, the zero flag and not the result would be the thing that
needed attention.

## The FIR iteration

`fir8_direct` and `fir8_pipelined` compute the same function with the same
exact-width accumulator, and both are checked against the same C++ golden model,
so the difference in the table is purely an implementation-quality difference.
Three structures were built and measured.

### Baseline: `fir8_direct`, one cycle

2.429 ns, 412 MHz. Its longest path starts at `in_sample`, runs through eleven
levels of XOR and a short carry chain, and ends at the `out_sample` register.

The eleven XOR levels are the tell: synthesis did not build eight separate
multipliers followed by an adder tree. It fused the whole sum-of-products into a
single partial-product reduction feeding one carry-propagate adder. That is a
good result for a one-cycle design, and it is also why the obvious retiming
backfires.

### Rejected: two taps fused per stage, three cycles

1.774 ns, 564 MHz. Better than the baseline but worse than the version kept.

The idea was to preserve the fusion that makes `fir8_direct` efficient by
keeping two multiplies inside each stage-1 register. Measurement said no: the
stage-1 path is a thirteen-level reduction tree followed by a twelve-gate carry
chain. A registered value has to be a plain binary number, so the
carry-propagate adder cannot be avoided at a register boundary, and fusing two
products into that boundary only deepens the tree in front of an adder that was
going to be there anyway.

### Kept: one product per stage, four cycles

1.423 ns, 703 MHz, **1.71x faster than the baseline** for 16.5% more area and
235 more registers.

Cutting at the individual products leaves one 8x8 multiply as the longest stage,
and the three adder-only stages that follow are well short of it. The stage-1
path is a ten-level reduction tree plus a ten-gate carry chain.

### What would come next

The bottleneck is now a single multiply: reduction tree plus its own
carry-propagate adder. Beating that means pipelining *inside* the multiplier,
keeping partial products in carry-save form across the register boundary so no
carry-propagate adder is needed there. That means writing the compressor tree
explicitly in RTL rather than leaving `*` to synthesis, which is a much larger
change than any of the three above, and it was not attempted here.

## Simulation performance

`verif/fifo_tb.sv` runs under both simulators, so the same testbench and seed
can be timed against each other. 200,000 random cycles, best of three:

| simulator | wall time | throughput | result |
| --- | --- | --- | --- |
| Icarus Verilog 12.0 | 3.243 s | 62 k cycles/s | 673128 checks, 0 failures |
| Verilator 5.020 (compiled, assertions on) | 0.165 s | 1215 k cycles/s | 673128 checks, 0 failures |

Identical check counts and identical coverage, 19.7x faster, and the Verilator
run is doing strictly more work because the bound assertions are active. The
cost is roughly 4-5 s of compilation per model, which is why the event-driven
simulator is still the faster way to iterate on a testbench and the compiled one
is how the long regressions are run.

The C++ harnesses are faster still, since they drive the model directly with no
event scheduler: the exhaustive ALU sweep evaluates about 30 M vectors/s, which
is what makes checking all 1,048,576 input combinations a 35 ms test.
