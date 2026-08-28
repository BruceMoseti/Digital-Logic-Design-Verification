// Assertions shared by both FIR implementations. Only the control behaviour is
// checked here -- out_valid timing and output stability -- because the
// arithmetic is checked against the C++ golden model in tb_fir.cpp.
//
// Note that ## cycle delays in sequences are unsupported by Verilator 5.020, so
// the expected out_valid timing is expressed with a reference valid pipeline
// rather than `in_valid |=> ##(LATENCY-1) out_valid`.

module fir_props #(
    parameter int LATENCY = 1,
    parameter int ACCW = 19
) (
    input logic                   clk,
    input logic                   rst_n,
    input logic                   in_valid,
    input logic                   out_valid,
    input logic signed [ACCW-1:0] out_sample
);

  logic [LATENCY-1:0] vpipe;

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      vpipe <= '0;
    end else begin
      vpipe[0] <= in_valid;
      for (int i = 1; i < LATENCY; i++) vpipe[i] <= vpipe[i-1];
    end
  end

  a_reset_state : assert property (@(posedge clk)
      !rst_n |-> (!out_valid && out_sample == '0));

  // Every accepted sample produces exactly one output, LATENCY cycles later.
  a_valid_latency : assert property (@(posedge clk) disable iff (!rst_n)
      out_valid == vpipe[LATENCY-1]);

  // The output register only moves on the cycle it is announced.
  a_output_held : assert property (@(posedge clk) disable iff (!rst_n)
      !out_valid |-> $stable(out_sample));

endmodule
