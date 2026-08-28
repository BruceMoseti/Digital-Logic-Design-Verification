// Synchronous FIFO with combinational (show-ahead) read data.
//
// DEPTH must be a power of two. Writes are dropped when full and reads are
// ignored when empty, so a concurrent read and write at either boundary leaves
// the FIFO consistent. rd_data is only meaningful while empty is low.

module sync_fifo #(
    parameter int WIDTH = 8,
    parameter int DEPTH = 8
) (
    input  logic                   clk,
    input  logic                   rst_n,
    input  logic                   wr_en,
    input  logic [WIDTH-1:0]       wr_data,
    input  logic                   rd_en,
    output logic [WIDTH-1:0]       rd_data,
    output logic                   full,
    output logic                   empty,
    output logic [$clog2(DEPTH):0] count
);

  localparam int PTRW = $clog2(DEPTH);
  localparam logic [PTRW:0] CAPACITY = (PTRW + 1)'(DEPTH);

  logic [WIDTH-1:0] mem[DEPTH];
  logic [PTRW-1:0]  wr_ptr;
  logic [PTRW-1:0]  rd_ptr;
  logic [PTRW:0]    cnt;

  logic do_wr;
  logic do_rd;

`ifdef BUG_FIFO_OVERWRITE
  assign do_wr = wr_en;
`else
  assign do_wr = wr_en && !full;
`endif
  assign do_rd = rd_en && !empty;

  assign full    = (cnt == CAPACITY);
  assign empty   = (cnt == '0);
  assign count   = cnt;
  assign rd_data = mem[rd_ptr];

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      wr_ptr <= '0;
      rd_ptr <= '0;
      cnt    <= '0;
    end else begin
      if (do_wr) wr_ptr <= wr_ptr + 1'b1;
`ifdef BUG_FIFO_PTR
      if (do_rd) rd_ptr <= rd_ptr + PTRW'(2);
`else
      if (do_rd) rd_ptr <= rd_ptr + 1'b1;
`endif
`ifdef BUG_FIFO_COUNT
      if (do_wr) cnt <= cnt + 1'b1;
      else if (do_rd) cnt <= cnt - 1'b1;
`else
      if (do_wr && !do_rd) cnt <= cnt + 1'b1;
      else if (do_rd && !do_wr) cnt <= cnt - 1'b1;
`endif
    end
  end

  always_ff @(posedge clk) begin
    if (do_wr) mem[wr_ptr] <= wr_data;
  end

endmodule
