// 8-tap FIR filter, retimed into four pipeline stages:
//   S1: eight products                 S2: four partial sums
//   S3: two partial sums               S4: final sum
// Arithmetically identical to fir8_direct (same coefficients, same exact-width
// accumulator), with a latency of 4 cycles instead of 1.
//
// Synthesis fuses the whole of fir8_direct into one partial-product reduction
// feeding a single carry-propagate adder, so its longest path runs from the
// coefficient and sample inputs through that entire structure: 2.43 ns. Cutting
// it at the products leaves one multiply as the longest stage at 1.42 ns, with
// the adder-only stages well short of that.
//
// Grouping two taps per stage-1 register was measured as well and is worse
// (1.77 ns): a registered value has to be a plain binary number, so the
// carry-propagate adder cannot be avoided at the boundary, and fusing two
// products only deepens the reduction tree in front of it. See docs/timing.md.

module fir8_pipelined #(
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

  logic signed [DW-1:0]    sr[TAPS];
  logic signed [DW-1:0]    nxt[TAPS];
  logic signed [DW+CW-1:0] prod[TAPS];

  logic signed [DW+CW-1:0] s1[TAPS];
  logic signed [DW+CW:0]   s2[4];
  logic signed [DW+CW+1:0] s3[2];

  logic v1, v2, v3;

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

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      v1         <= 1'b0;
      v2         <= 1'b0;
      v3         <= 1'b0;
      out_valid  <= 1'b0;
      out_sample <= '0;
      for (int i = 0; i < TAPS; i++) begin
        sr[i] <= '0;
        s1[i] <= '0;
      end
      for (int i = 0; i < 4; i++) s2[i] <= '0;
      for (int i = 0; i < 2; i++) s3[i] <= '0;
    end else begin
      v1        <= in_valid;
      v2        <= v1;
      v3        <= v2;
`ifdef BUG_FIR_VALID
      out_valid <= v2;
`else
      out_valid <= v3;
`endif

      if (in_valid) begin
        for (int i = 0; i < TAPS; i++) begin
          sr[i] <= nxt[i];
`ifdef BUG_FIR_TAP
          s1[i] <= (i == TAPS - 1) ? '0 : prod[i];
`else
          s1[i] <= prod[i];
`endif
        end
      end

      if (v1) begin
        for (int j = 0; j < 4; j++) s2[j] <= (DW+CW+1)'(s1[2*j]) + (DW+CW+1)'(s1[2*j+1]);
      end

      if (v2) begin
        for (int k = 0; k < 2; k++) s3[k] <= (DW+CW+2)'(s2[2*k]) + (DW+CW+2)'(s2[2*k+1]);
      end

      if (v3) out_sample <= ACCW'(s3[0]) + ACCW'(s3[1]);
    end
  end

endmodule
