// 8-tap FIR filter, direct form: every multiply and the whole adder tree sit in
// one clock cycle. Latency is 1 cycle from in_valid to out_valid.
//
// Coefficients arrive on a flat bus, tap 0 (newest sample) in the low bits, and
// are treated as signed. ACCW = DW + CW + 3 is wide enough that the sum of
// eight products can never overflow, so the result is always exact.
//
// fir8_pipelined implements the same function with a retimed datapath; the two
// are checked against the same C++ golden model and compared in synthesis.

module fir8_direct #(
    parameter int DW   = 8,
    parameter int CW   = 8,
    parameter int ACCW = DW + CW + 3
) (
    input  logic                   clk,
    input  logic                   rst_n,
    input  logic                   in_valid,
    input  logic signed [DW-1:0]   in_sample,
    input  logic [8*CW-1:0]        coeff_flat,
    output logic                   out_valid,
    output logic signed [ACCW-1:0] out_sample
);

  localparam int TAPS = 8;

  logic signed [DW-1:0]      sr[TAPS];
  logic signed [DW-1:0]      nxt[TAPS];
  logic signed [DW+CW-1:0]   prod[TAPS];
  logic signed [ACCW-1:0]    acc;

  always_comb begin
    nxt[0] = in_sample;
    for (int i = 1; i < TAPS; i++) nxt[i] = sr[i-1];
  end

  always_comb begin
    for (int i = 0; i < TAPS; i++) begin
`ifdef BUG_FIR_SIGN
      prod[i] = signed'({1'b0, coeff_flat[i*CW+:CW]}) * nxt[i];
`else
      prod[i] = signed'(coeff_flat[i*CW+:CW]) * nxt[i];
`endif
    end
  end

  always_comb begin
    acc = '0;
`ifdef BUG_FIR_TAP
    for (int i = 0; i < TAPS - 1; i++) acc = acc + ACCW'(prod[i]);
`else
    for (int i = 0; i < TAPS; i++) acc = acc + ACCW'(prod[i]);
`endif
  end

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      out_valid  <= 1'b0;
      out_sample <= '0;
      for (int i = 0; i < TAPS; i++) sr[i] <= '0;
    end else begin
`ifdef BUG_FIR_VALID
      if (in_valid) out_valid <= 1'b1;
`else
      out_valid <= in_valid;
`endif
      if (in_valid) begin
        out_sample <= acc;
        for (int i = 0; i < TAPS; i++) sr[i] <= nxt[i];
      end
    end
  end

endmodule
