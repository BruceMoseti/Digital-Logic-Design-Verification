// FIFO testbench: a cycle-accurate driver, a queue reference model and two test
// programs selected with +TEST=<directed|random>.
//
// Because rd_data is show-ahead, the driver samples it in the same cycle it
// asserts rd_en, before the edge that pops the entry. Every cycle also checks
// count, full and empty against the model, so a pointer or counter fault is
// caught on the cycle it happens rather than when data eventually diverges.
//
// The random test ends by requiring that the stimulus actually reached the
// interesting states (full, empty, concurrent read and write, pointer wrap). A
// random test that never fills the FIFO proves very little, so failing to reach
// them is treated as a failure of the test itself.

`timescale 1ns / 1ps

module fifo_tb;

  import tb_pkg::*;

  localparam int WIDTH = 8;
  localparam int DEPTH = 8;
  localparam int PTRW = $clog2(DEPTH);

  logic             clk = 1'b0;
  logic             rst_n = 1'b0;
  logic             wr_en = 1'b0;
  logic [WIDTH-1:0] wr_data = '0;
  logic             rd_en = 1'b0;
  logic [WIDTH-1:0] rd_data;
  logic             full;
  logic             empty;
  logic [PTRW:0]    count;

  sync_fifo #(
      .WIDTH(WIDTH),
      .DEPTH(DEPTH)
  ) dut (
      .clk(clk),
      .rst_n(rst_n),
      .wr_en(wr_en),
      .wr_data(wr_data),
      .rd_en(rd_en),
      .rd_data(rd_data),
      .full(full),
      .empty(empty),
      .count(count)
  );

  Checker chk;
  Random  rnd;

  logic [WIDTH-1:0] model[$];

  int unsigned cyc_full;
  int unsigned cyc_empty;
  int unsigned cyc_both;
  int unsigned n_wrapped;
  int unsigned writes_done;

  string       test_name;
  int unsigned seed;
  int unsigned cycles;

  always #5 clk = ~clk;

  // One clock cycle with the given request pattern. Predicts from the pre-edge
  // state, then re-checks the observable state after the edge.
  task automatic cycle(bit req_wr, logic [WIDTH-1:0] data, bit req_rd);
    bit               will_wr;
    bit               will_rd;
    logic [WIDTH-1:0] observed;
    logic [WIDTH-1:0] expected;

    wr_en   = req_wr;
    wr_data = data;
    rd_en   = req_rd;

    will_wr  = req_wr && !full;
    will_rd  = req_rd && !empty;
    observed = rd_data;

    if (full) cyc_full = cyc_full + 1;
    if (empty) cyc_empty = cyc_empty + 1;
    if (will_wr && will_rd) cyc_both = cyc_both + 1;

    @(posedge clk);

    if (will_rd) begin
      expected = model.pop_front();
      chk.eq(64'(observed), 64'(expected), "read data");
    end
    if (will_wr) begin
      model.push_back(data);
      writes_done = writes_done + 1;
      if (writes_done % DEPTH == 0) n_wrapped = n_wrapped + 1;
    end

    #1;
    chk.eq(64'(count), 64'(model.size()), "count");
    chk.ok(full == (model.size() == DEPTH), $sformatf("full=%b size=%0d", full, model.size()));
    chk.ok(empty == (model.size() == 0), $sformatf("empty=%b size=%0d", empty, model.size()));
  endtask

  task automatic idle(int unsigned n);
    for (int unsigned i = 0; i < n; i++) cycle(1'b0, '0, 1'b0);
  endtask

  task automatic do_reset();
    rst_n = 1'b0;
    wr_en = 1'b0;
    rd_en = 1'b0;
    repeat (2) @(posedge clk);
    #1;
    model.delete();
    chk.ok(empty === 1'b1, "empty after reset");
    chk.ok(full === 1'b0, "not full after reset");
    chk.eq(64'(count), 64'd0, "count after reset");
    rst_n = 1'b1;
    @(posedge clk);
    #1;
  endtask

  task automatic run_directed();
    logic [WIDTH-1:0] d;

    do_reset();

    // Fill to capacity.
    for (int i = 0; i < DEPTH; i++) cycle(1'b1, WIDTH'(32'h10 + i), 1'b0);
    chk.ok(full === 1'b1, "full after DEPTH writes");

    // Writes while full are dropped and must not disturb the contents.
    cycle(1'b1, 8'hEE, 1'b0);
    cycle(1'b1, 8'hEF, 1'b0);

    // A concurrent read and write while full: the read proceeds, the write is
    // dropped because full is asserted at the start of the cycle.
    cycle(1'b1, 8'hED, 1'b1);
    chk.eq(64'(count), 64'(DEPTH) - 64'd1, "one slot free after read at full");

    // Drain completely. Bounded, so a DUT that never reports empty fails the
    // test rather than hanging the regression on an unbounded wait.
    for (int i = 0; i < 2 * DEPTH && model.size() > 0; i++) cycle(1'b0, '0, 1'b1);
    chk.ok(model.size() == 0, $sformatf("drained within %0d cycles", 2 * DEPTH));
    chk.ok(empty === 1'b1, "empty after draining");

    // Reads while empty are ignored.
    cycle(1'b0, '0, 1'b1);
    cycle(1'b0, '0, 1'b1);

    // Concurrent read and write while empty: only the write takes effect.
    cycle(1'b1, 8'h5A, 1'b1);
    chk.eq(64'(count), 64'd1, "count is 1 after write+read at empty");
    cycle(1'b0, '0, 1'b1);

    // Push far more than DEPTH entries through to force pointer wrap.
    for (int i = 0; i < 3 * DEPTH; i++) begin
      d = WIDTH'(32'hA0 + i);
      cycle(1'b1, d, 1'b1);
    end

    // Half fill, reset in the middle of traffic, then confirm normal service.
    for (int i = 0; i < DEPTH / 2; i++) cycle(1'b1, WIDTH'(32'h70 + i), 1'b0);
    do_reset();
    cycle(1'b1, 8'h99, 1'b0);
    cycle(1'b0, '0, 1'b1);
    chk.ok(empty === 1'b1, "empty again after post-reset write and read");
  endtask

  task automatic run_random();
    bit req_wr;
    bit req_rd;
    int unsigned wr_pct;
    int unsigned rd_pct;

    do_reset();

    for (int unsigned i = 0; i < cycles; i++) begin
      // Sweep the read/write pressure so the FIFO spends time at both
      // boundaries instead of hovering near half full.
      case ((i / 64) % 3)
        0: begin wr_pct = 85; rd_pct = 25; end
        1: begin wr_pct = 25; rd_pct = 85; end
        default: begin wr_pct = 55; rd_pct = 55; end
      endcase

      req_wr = rnd.chance(wr_pct);
      req_rd = rnd.chance(rd_pct);
      cycle(req_wr, WIDTH'(rnd.next()), req_rd);
    end

    idle(2);

    chk.ok(cyc_full > 0, $sformatf("stimulus reached full (%0d cycles)", cyc_full));
    chk.ok(cyc_empty > 0, $sformatf("stimulus reached empty (%0d cycles)", cyc_empty));
    chk.ok(cyc_both > 0, $sformatf("stimulus had concurrent read+write (%0d)", cyc_both));
    chk.ok(n_wrapped > 1, $sformatf("write pointer wrapped (%0d times)", n_wrapped));
    $display("[INFO] coverage: full=%0d empty=%0d both=%0d wraps=%0d writes=%0d", cyc_full,
             cyc_empty, cyc_both, n_wrapped, writes_done);
  endtask

  initial begin
    cyc_full    = 0;
    cyc_empty   = 0;
    cyc_both    = 0;
    n_wrapped   = 0;
    writes_done = 0;

    if (!$value$plusargs("TEST=%s", test_name)) test_name = "directed";
    if (!$value$plusargs("SEED=%d", seed)) seed = 1;
    if (!$value$plusargs("CYCLES=%d", cycles)) cycles = 2000;

    chk = new($sformatf("fifo_%s", test_name));
    rnd = new(seed);

    if (test_name == "directed") run_directed();
    else if (test_name == "random") run_random();
    else $fatal(1, "unknown +TEST=%s", test_name);

    chk.report();
    $finish;
  end

endmodule
