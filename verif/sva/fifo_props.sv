// Assertions for the synchronous FIFO. The bind at the bottom reaches into the
// DUT for wr_ptr and rd_ptr, which is the point of using bind rather than
// wrapping the DUT: the pointer/count invariant is the check most likely to
// localise a fault, and it is not visible at the port boundary.

module fifo_props #(
    parameter int DEPTH = 8
) (
    input logic                   clk,
    input logic                   rst_n,
    input logic                   wr_en,
    input logic                   rd_en,
    input logic                   full,
    input logic                   empty,
    input logic [$clog2(DEPTH):0] count,
    input logic [$clog2(DEPTH)-1:0] wr_ptr,
    input logic [$clog2(DEPTH)-1:0] rd_ptr
);

  localparam int PTRW = $clog2(DEPTH);
  localparam logic [PTRW:0] CAPACITY = (PTRW + 1)'(DEPTH);

  // While reset is asserted the FIFO must present itself as empty.
  a_reset_state : assert property (@(posedge clk)
      !rst_n |-> (count == '0 && empty && !full));

  a_count_bounded : assert property (@(posedge clk) disable iff (!rst_n)
      count <= CAPACITY);

  a_full_flag : assert property (@(posedge clk) disable iff (!rst_n)
      full == (count == CAPACITY));

  a_empty_flag : assert property (@(posedge clk) disable iff (!rst_n)
      empty == (count == '0));

  // One entry in, one entry out at most, so the occupancy moves by one at most.
  a_count_step : assert property (@(posedge clk) disable iff (!rst_n)
      (count == $past(count)) || (count == $past(count) + 1'b1) ||
      (count == $past(count) - 1'b1));

  // A write to a full FIFO is dropped and a read from an empty one is ignored.
  a_no_overflow : assert property (@(posedge clk) disable iff (!rst_n)
      (full && wr_en && !rd_en) |=> $stable(count));

  a_no_underflow : assert property (@(posedge clk) disable iff (!rst_n)
      (empty && rd_en && !wr_en) |=> $stable(count));

  // Occupancy and pointers must agree modulo the depth. This also covers the
  // full case, where the pointers are equal and the low bits of count are zero.
  a_ptr_count_coherent : assert property (@(posedge clk) disable iff (!rst_n)
      count[PTRW-1:0] == (wr_ptr - rd_ptr));

endmodule

bind sync_fifo fifo_props #(
    .DEPTH(DEPTH)
) u_fifo_props (
    .clk(clk),
    .rst_n(rst_n),
    .wr_en(wr_en),
    .rd_en(rd_en),
    .full(full),
    .empty(empty),
    .count(count),
    .wr_ptr(wr_ptr),
    .rd_ptr(rd_ptr)
);
