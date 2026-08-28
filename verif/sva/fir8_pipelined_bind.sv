bind fir8_pipelined fir_props #(
    .LATENCY(4),
    .ACCW(ACCW)
) u_fir_props (
    .clk(clk),
    .rst_n(rst_n),
    .in_valid(in_valid),
    .out_valid(out_valid),
    .out_sample(out_sample)
);
