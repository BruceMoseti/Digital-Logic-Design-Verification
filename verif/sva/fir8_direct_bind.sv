bind fir8_direct fir_props #(
    .LATENCY(1),
    .ACCW(ACCW)
) u_fir_props (
    .clk(clk),
    .rst_n(rst_n),
    .in_valid(in_valid),
    .out_valid(out_valid),
    .out_sample(out_sample)
);
