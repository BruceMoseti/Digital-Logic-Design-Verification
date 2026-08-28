// Combinational ALU. Plain Verilog (no SystemVerilog constructs) so that the
// project exercises both source languages.
//
// Flag semantics, which the C++ golden model mirrors exactly:
//   carry    - ADD: carry-out. SUB: borrow-out (set when a < b unsigned). 0 otherwise.
//   overflow - signed overflow, ADD/SUB only. 0 otherwise.
//   negative - MSB of the result.
//   zero     - result is all zeroes.
// Shift amounts use the low $clog2(W) bits of b, so shifts by >= W wrap rather
// than flushing the register (RISC-V style).

`default_nettype none

module alu #(
    parameter W = 32
) (
    input  wire [W-1:0] a,
    input  wire [W-1:0] b,
    input  wire [3:0]   op,
    output wire [W-1:0] y,
    output wire         zero,
    output wire         carry,
    output wire         overflow,
    output wire         negative
);

  localparam ALU_ADD  = 4'd0;
  localparam ALU_SUB  = 4'd1;
  localparam ALU_AND  = 4'd2;
  localparam ALU_OR   = 4'd3;
  localparam ALU_XOR  = 4'd4;
  localparam ALU_SLL  = 4'd5;
  localparam ALU_SRL  = 4'd6;
  localparam ALU_SRA  = 4'd7;
  localparam ALU_SLT  = 4'd8;
  localparam ALU_SLTU = 4'd9;

  localparam SHW = (W <= 2) ? 1 : $clog2(W);

`ifdef BUG_ALU_SHAMT
  wire [SHW-1:0] shamt = {1'b0, b[SHW-2:0]};
`else
  wire [SHW-1:0] shamt = b[SHW-1:0];
`endif

  wire [W:0] sum  = {1'b0, a} + {1'b0, b};
  wire [W:0] diff = {1'b0, a} - {1'b0, b};

  reg [W-1:0] result;
  reg         carry_out;
  reg         ovf;

  always @(*) begin
    carry_out = 1'b0;
    ovf       = 1'b0;
    case (op)
      ALU_ADD: begin
        result    = sum[W-1:0];
        carry_out = sum[W];
        ovf       = (a[W-1] == b[W-1]) && (result[W-1] != a[W-1]);
      end
      ALU_SUB: begin
        result    = diff[W-1:0];
        carry_out = diff[W];
`ifdef BUG_ALU_SUB_OVF
        ovf       = (a[W-1] == b[W-1]) && (result[W-1] != a[W-1]);
`else
        ovf       = (a[W-1] != b[W-1]) && (result[W-1] != a[W-1]);
`endif
      end
      ALU_AND:  result = a & b;
      ALU_OR:   result = a | b;
      ALU_XOR:  result = a ^ b;
      ALU_SLL:  result = a << shamt;
      ALU_SRL:  result = a >> shamt;
`ifdef BUG_ALU_SRA
      ALU_SRA:  result = a >> shamt;
`else
      ALU_SRA:  result = $signed(a) >>> shamt;
`endif
      ALU_SLT:  result = {{(W - 1) {1'b0}}, ($signed(a) < $signed(b))};
      ALU_SLTU: result = {{(W - 1) {1'b0}}, (a < b)};
      default:  result = {W{1'b0}};
    endcase
  end

  assign y        = result;
  assign zero     = ~(|result);
  assign carry    = carry_out;
  assign overflow = ovf;
  assign negative = result[W-1];

endmodule

`default_nettype wire
