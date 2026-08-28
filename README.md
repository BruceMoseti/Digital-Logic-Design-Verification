# Digital Logic Design & Verification

Software can be patched after it ships. A chip cannot. Once a design is
committed to silicon, a bug in it is permanent, and fixing it means months and a
new manufacturing run. So most of the real work in hardware is not writing the
design — it is proving the design is right *before* anyone builds it. Industry
teams routinely spend more effort verifying a design than creating it.

This project is four digital circuits and the machinery that proves they work:
a test suite that attacks them from four independent angles, a way to confirm
that the test suite itself would actually catch a real bug, and a flow that
measures how fast and how large each circuit would be once manufactured — then
feeds those measurements back into the design.

Everything runs on free, open-source tools. There is no vendor licence and
nothing to buy.

```
make test      the full regression suite                  ~14 s   → 11/11 pass
make mutation  9 deliberate bugs planted in the designs   ~26 s   → 9/9 caught
make synth     gate-level size and speed of each design   ~6 min
```

---

## What it does

Four designs, chosen because each one fails in a different and instructive way.

| design | what it is, in plain terms | why this one |
| --- | --- | --- |
| **ALU** | the calculator inside a processor: adds, subtracts, compares, shifts bits around | densely packed with edge cases — overflow, negative numbers, shifting further than the number is wide |
| **Synchronous FIFO** | a queue built out of hardware; data goes in one end and comes out the other in the same order | queues are where off-by-one bugs live, especially when completely full or completely empty |
| **FIR filter** (two versions) | a digital filter — the kind of thing that smooths a sensor reading or strips hiss out of audio | the same filter built two different ways, so speed and chip area can be compared head to head |

The two filters are the interesting pair. They compute *identical* results, so
any difference between them is purely a difference in implementation quality —
which is exactly what makes measuring them worthwhile.

---

## How it works

### 1. Describing the circuit

Hardware is written in a *hardware description language*. It looks a little like
ordinary code, but it means something quite different: instead of a list of
steps to run, it describes structure — registers, logic gates, wires — and
everything in it happens simultaneously, once per tick of a clock.

The ALU is written in Verilog and the rest in SystemVerilog. Along with VHDL,
these are the languages most production hardware is described in.

### 2. Checking it four independent ways

The trap in verifying anything is that the test can quietly share the same
misunderstanding as the thing it tests. Both then agree, and both are wrong. The
defence is to check from angles that would not fail the same way, so here there
are four.

**Hand-worked examples.** 35 cases for the ALU where I worked out the correct
answer by hand from the specification: adding two large positive numbers until
they overflow into a negative one, subtracting a bigger number from a smaller
one, shifting a number further than it is wide, comparing values where signed
and unsigned interpretation disagree. These are slow to produce, so there are
few of them, but they are tied to the specification rather than to any code.

**A second, independent implementation.** The same arithmetic is written a
second time in C++, from the specification, without reference to the circuit.
The two are then compared against each other. For an 8-bit ALU this can be taken
to its limit: **all 1,048,576 possible combinations** of both inputs and every
operation are tried, which is not a sample of the design's behaviour but the
whole of it. The 32-bit version is far too large to enumerate, so it gets two
million random cases with awkward values deliberately mixed in.

**Random traffic against a running model.** The FIFO is driven with randomised
reads and writes while a reference queue tracks what *should* be inside it,
checking the data, the occupancy count and both status flags on every single
cycle. The test also refuses to pass unless the random traffic actually reached
the interesting situations — completely full, completely empty, reading and
writing at the same instant, wrapping around the end of the memory. A random
test that has quietly stopped exercising the hard cases will otherwise keep
reporting success forever.

**Assertions.** Rules that must hold at every moment, checked continuously
while the simulation runs. They are deliberately written as properties true of
*any* correct implementation rather than as a restatement of the design: a queue
can never hold more than its capacity; its occupancy can never move by more than
one per cycle; shifting a negative number right must leave it negative. When one
fails it names itself and the exact cycle, which turns debugging from a search
into a lookup.

### 3. Checking that the checks work

A test suite that passes tells you nothing on its own. It might be genuinely
watertight, or it might not be looking. The only way to tell them apart is to
break the design on purpose and see whether anyone notices.

`make mutation` does this automatically. It plants nine realistic bugs, one at a
time — the kind of mistakes that actually happen, like using a plain shift where
a sign-preserving one belongs, applying the overflow rule for addition to
subtraction, a queue that ignores its own "full" signal, a read pointer that
advances by two, a filter that drops its last tap — and then requires the tests
to fail. All nine are caught, and the report names which mechanism caught each
one.

### 4. Measuring speed and size

Working is necessary but not sufficient; a design also has to be fast enough and
small enough. Two more steps answer that.

*Synthesis* converts the design into the actual gates that would be
manufactured — a netlist of ANDs, ORs and flip-flops — which gives a size.
*Static timing analysis* then traces every path a signal can take through those
gates and finds the slowest one. That slowest path sets the maximum clock speed,
because the clock cannot tick again until the slowest signal has arrived.

No timing tool could be installed in this environment, so I wrote the analyser.
It is validated against small circuits whose delay can be worked out by hand.

---

## The process

The order things were done in mattered more than any individual step.

**Find out what the tools can actually do, before designing around them.** The
first hour went on small probe files rather than on the project, which turned up
two limitations worth knowing in advance: one simulator silently discards a
common way of incrementing a counter, and the other rejects a standard piece of
assertion syntax. Both would have been confusing bugs later. Found early, they
were just constraints.

**Write the design, then lint it.** All four designs pass the strictest warning
level with no suppressions.

**Write the independent model and run it to exhaustion.** The exhaustive ALU
sweep either passes completely or fails immediately, so this was the fastest
possible feedback on whether the arithmetic was right.

**Add the assertions.** Then deliberately break the design to confirm each
assertion fires — an assertion that has never failed is an assertion you have no
reason to trust.

**Prove the suite catches bugs.** The mutation suite was built next, and it is
what justifies calling any of the earlier steps "verified".

**Measure, then let the measurement drive the design.** This is where the
project got interesting, below.

**Finally, try to break it.** After everything passed, I injected a fault that
was deliberately *not* in the mutation list — an off-by-one in the FIFO's
"empty" signal — to see what would happen. The tests noticed, but one of them
noticed by hanging instead of failing: a loop in my own test code sat waiting
for a queue that would never drain. A hang is far worse than a failure, because
it stalls the whole run and reports nothing at the end of it. That loop is now
bounded, the per-test time limit dropped from 30 minutes to 5, and the same
fault is now reported by all four FIFO tests within 2.3 seconds.

### The part I got wrong

The two filters exist to answer one question: does splitting the work across
pipeline stages make the circuit faster?

The theory is standard. Doing less work between clock ticks means the ticks can
come closer together. I split the filter's eight multiplications into separate
stages, expecting a solid speedup.

**It came out slower.** 1.42 nanoseconds against the original's 1.12.

The timing report explained why. The single-cycle version's slowest path is a
long chain of one kind of gate; the pipelined version's is that same chain plus
a second long chain of a different kind. Synthesis had been quietly doing
something clever with the original: rather than building eight separate
multipliers and adding up their results, it had merged all eight into one
combined structure that finishes with a *single* addition at the end. Adding a
pipeline register in the middle forced every multiplication to complete on its
own and pay for its own final addition — eight of them instead of one.

So I tried to preserve that merging by grouping two multiplications per stage.
That was slower still, at 1.77 ns. A value stored in a register has to be a
finished number, so the final addition is unavoidable at any register boundary;
grouping only made the work in front of it deeper.

Which reframed the result. Cutting at the individual multiplications is right
after all — and reading the *original* measurement correctly showed the win was
there the whole time. My first comparison had measured only paths that begin and
end at a register, and the single-cycle filter's true slowest path begins at an
input pin. Once measured properly:

**2.43 ns → 1.42 ns, a 1.71× speedup, for 16.5% more area.**

Three attempts, one of them a mistake in the design and one a mistake in how I
was measuring. The version in the repository is the one that won on measurement,
and the two that lost are written up in [`docs/timing.md`](docs/timing.md).

---

## Results

Every number here comes from `make all` on a clean checkout and reproduces
exactly.

**Correctness**

| check | result |
| --- | --- |
| Regression suite | 11 of 11 pass, ~14 s |
| Exhaustive ALU proof | 1,048,576 of 1,048,576 combinations correct |
| Random ALU vectors | 2,000,000 correct, at 32 bits |
| Planted bugs caught | 9 of 9 |
| Warnings at the strictest lint level | none |

**Size and speed after synthesis**

| design | gates | registers | area | slowest path | max clock |
| --- | --- | --- | --- | --- | --- |
| ALU (32-bit) | 1438 | 0 | 3921 | 1.883 ns | — |
| FIFO (8×8) | 280 | 74 | 1584 | 0.663 ns | 1508 MHz |
| FIR, single-cycle | 4642 | 76 | 15169 | 2.429 ns | 412 MHz |
| FIR, pipelined | 4854 | 311 | 17665 | 1.423 ns | **703 MHz** |

The ALU has no clock of its own — it is pure logic that settles in 1.883 ns —
so it has no maximum clock speed. Its slowest path ends at the "is the result
zero?" output rather than at the result itself, which is a useful thing to know:
if this ALU were ever put into a pipeline, that flag and not the arithmetic
would be the thing to fix first.

**Simulation speed**

The same FIFO test runs under both simulators from the same random seed, so they
can be timed against each other over 200,000 cycles:

| simulator | time | throughput | result |
| --- | --- | --- | --- |
| Icarus Verilog | 3.243 s | 62 k cycles/s | 673,128 checks, 0 failures |
| Verilator (compiled) | 0.165 s | 1,215 k cycles/s | 673,128 checks, 0 failures |

Identical results, **19.7× faster**, and the faster one is doing strictly more
work because the assertions are active there. Getting both to agree exactly is
the reason the test generates its own random numbers instead of using the
built-in generator: the built-in one differs between simulators, and a bug found
in one that cannot be reproduced in the other is a bug you cannot debug.

---

## Running it

```bash
sudo apt-get install -y iverilog verilator yosys build-essential python3
git clone https://github.com/BruceMoseti/Digital-Logic-Design-Verification
cd Digital-Logic-Design-Verification
make all
```

Icarus Verilog 12.0, Verilator 5.020, Yosys 0.33, a C++17 compiler and Python
3.8 or newer (tested on 3.12). No Python packages beyond the standard library.

| command | what it does |
| --- | --- |
| `make test` | build and run all 11 tests |
| `make mutation` | plant each bug in turn and require the suite to catch it |
| `make synth` | synthesise every design and report area and timing |
| `make paths` | the same, plus the full gate-by-gate critical path listings |
| `make all` | all of the above |

`make test SEED=42 SCALE=3.0` changes the random seed and multiplies the volume
of stimulus. The random tests have been run across six different seeds and pass
on all of them, with both simulators agreeing on the exact number of checks
performed for each.

---

## Layout

```
rtl/                 the four designs
verif/
  alu_tb.sv          the 35 hand-worked ALU cases
  fifo_tb.sv         FIFO driver, reference queue, coverage requirements
  tb_pkg.sv          shared test infrastructure: random source, result checker
  sva/               assertions, attached to the designs without touching them
  cpp/               C++ reference models and the harnesses that drive them
  test_sta.py        proves the timing analyser itself is correct
syn/cell_library.py  the gate library: sizes and delays
scripts/
  run_regression.py  test definitions, plus the regression and mutation modes
  synth.py           synthesis and the comparison table
  sta.py             the timing analyser
docs/timing.md       full timing results and the three FIR attempts
```

Two structural details worth pointing out. The assertions are attached to the
designs from the outside using `bind`, so no test code lives in the hardware
that would be manufactured, while the checks can still see internal signals a
test would normally be blind to. And `syn/cell_library.py` is the single source
of truth for the gate library in both directions — it writes the file the
synthesis tool reads, and it answers the timing analyser's questions — so the
circuit that gets built and the circuit that gets measured cannot drift apart.

---

## What this is not

Three limits worth stating plainly, because a result is only as good as the
reader's ability to check it.

**The gate library is invented.** Its delays are shaped like a real 45nm
manufacturing process but are not measured from one. Comparisons between designs
built with it are meaningful; the absolute megahertz figures are not, and should
not be quoted as though they were.

**The timing analyser is mine, and it is simplified.** One operating condition,
pessimistic assumptions about signal edges, no modelling of wire resistance, and
an ideal clock. It does find the genuine longest path through the circuit, which
is what makes two designs comparable, and `verif/test_sta.py` checks its
arithmetic against circuits simple enough to verify by hand.

**This is simulation, not silicon.** Nothing here has been placed, routed or
manufactured. The verification results stand on their own; the physical numbers
are estimates from a synthetic library.

---

## Terms

| term | meaning |
| --- | --- |
| **RTL** | register-transfer level — the style of hardware code that describes registers and the logic between them |
| **Testbench** | a program that pretends to be the outside world: it feeds the design inputs and checks the outputs |
| **Golden model** | a second implementation, written independently from the specification, used as the reference to compare against |
| **Assertion** | a rule that must always hold, checked continuously during simulation |
| **Synthesis** | converting the design into the actual gates that would be manufactured |
| **Static timing analysis** | tracing every path through those gates to find the slowest one, which sets the clock speed |
| **Pipelining** | splitting work across several clock ticks so that less happens per tick and the clock can run faster |
| **Critical path** | the slowest route a signal takes through a circuit; the thing that limits clock speed |
| **Mutation testing** | deliberately introducing bugs to confirm the tests would catch them |
| **Lint** | automated checks for suspicious code, run before any simulation |
