// Testbench infrastructure shared by the directed and randomised SystemVerilog
// testbenches. Deliberately small: a deterministic random source and a checker
// that accumulates results, which is all both testbenches need.
//
// Kept to the intersection of Icarus Verilog and Verilator class support, so no
// parameterised classes and no in-class member initialisers.
//
// Class properties are updated with `x = x + 1` rather than `x++`: Icarus
// Verilog 12.0 silently drops the increment on a class property, which made the
// checkers report a single check no matter how many ran.

`timescale 1ns / 1ps

package tb_pkg;

  // 32-bit xorshift. $urandom is not guaranteed to produce the same stream
  // across simulators, and a failing seed has to reproduce under either one.
  class Random;
    logic [31:0] state;

    function new(int unsigned seed);
      state = (seed == 0) ? 32'h1 : seed[31:0];
    endfunction

    function logic [31:0] next();
      state = state ^ (state << 13);
      state = state ^ (state >> 17);
      state = state ^ (state << 5);
      return state;
    endfunction

    // Inclusive on both ends.
    function int unsigned range(int unsigned lo, int unsigned hi);
      return lo + (next() % (hi - lo + 1));
    endfunction

    function bit chance(int unsigned percent);
      return (range(0, 99) < percent);
    endfunction
  endclass

  class Checker;
    string       name;
    int unsigned checks;
    int unsigned failures;
    int unsigned reports;
    int unsigned max_reports;

    function new(string checker_name);
      name        = checker_name;
      checks      = 0;
      failures    = 0;
      reports     = 0;
      max_reports = 10;
    endfunction

    function void note_failure(string what);
      failures = failures + 1;
      if (reports < max_reports) begin
        reports = reports + 1;
        $display("[FAIL] %s @%0t: %s", name, $time, what);
      end
    endfunction

    // !== so that an X or Z on a DUT output is a failure rather than a match.
    function void eq(logic [63:0] got, logic [63:0] exp, string what);
      checks = checks + 1;
      if (got !== exp)
        note_failure($sformatf("%s: got=0x%0h expected=0x%0h", what, got, exp));
    endfunction

    function void ok(bit cond, string what);
      checks = checks + 1;
      if (cond !== 1'b1) note_failure(what);
    endfunction

    function void report();
      if (checks == 0) begin
        $display("[FAIL] %s: no checks were executed", name);
        $fatal(1, "%s executed no checks", name);
      end
      $display("[%s] %s: %0d checks, %0d failures", (failures == 0) ? "PASS" : "FAIL",
               name, checks, failures);
      if (failures != 0) $fatal(1, "%s: %0d failures", name, failures);
    endfunction
  endclass

endpackage
