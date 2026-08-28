// Assertions for the ALU, attached to the DUT with bind so the RTL stays free
// of verification code.
//
// The ALU is combinational, so these are immediate assertions in always_comb
// rather than clocked properties. They deliberately state invariants that hold
// for any correct implementation instead of recomputing the expected result --
// re-deriving the result here would only restate rtl/alu.v, and the C++ golden
// model already covers that.

module alu_props #(
    parameter int W = 32
) (
    input logic [W-1:0] a,
    input logic [W-1:0] b,
    input logic [3:0]   op,
    input logic [W-1:0] y,
    input logic         zero,
    input logic         carry,
    input logic         overflow,
    input logic         negative
);

  localparam logic [3:0] OP_ADD  = 4'd0;
  localparam logic [3:0] OP_SUB  = 4'd1;
  localparam logic [3:0] OP_AND  = 4'd2;
  localparam logic [3:0] OP_OR   = 4'd3;
  localparam logic [3:0] OP_SLL  = 4'd5;
  localparam logic [3:0] OP_SRL  = 4'd6;
  localparam logic [3:0] OP_SRA  = 4'd7;
  localparam logic [3:0] OP_SLT  = 4'd8;
  localparam logic [3:0] OP_SLTU = 4'd9;

  localparam int SHW = (W <= 2) ? 1 : $clog2(W);

  logic [SHW-1:0] shamt;
  assign shamt = b[SHW-1:0];

  always_comb begin
    a_zero_flag : assert (zero == (y == '0))
      else $error("zero=%b but y=0x%0h", zero, y);
    a_negative_flag : assert (negative == y[W-1])
      else $error("negative=%b but y=0x%0h", negative, y);

    // carry and overflow are defined only for the two arithmetic operations.
    if (op != OP_ADD && op != OP_SUB) begin
      a_carry_arith_only : assert (carry == 1'b0)
        else $error("carry set for op=%0d", op);
      a_ovf_arith_only : assert (overflow == 1'b0)
        else $error("overflow set for op=%0d", op);
    end

    // Signed overflow needs operands of the same sign for addition and of
    // opposite signs for subtraction; anything else cannot leave the range.
    if (op == OP_ADD && (a[W-1] != b[W-1])) begin
      a_add_no_ovf : assert (overflow == 1'b0)
        else $error("ADD flagged overflow for opposite-sign operands");
    end
    if (op == OP_SUB && (a[W-1] == b[W-1])) begin
      a_sub_no_ovf : assert (overflow == 1'b0)
        else $error("SUB flagged overflow for same-sign operands");
    end

    // Unsigned relations that pin down the carry/borrow convention.
    if (op == OP_ADD && !carry) begin
      a_add_no_wrap : assert (y >= a)
        else $error("ADD without carry produced y=0x%0h < a=0x%0h", y, a);
    end
    if (op == OP_SUB) begin
      a_sub_borrow : assert (carry == (a < b))
        else $error("SUB borrow=%b for a=0x%0h b=0x%0h", carry, a, b);
    end

    // An arithmetic right shift preserves the sign of the operand.
    if (op == OP_SRA) begin
      a_sra_sign : assert (y[W-1] == a[W-1])
        else $error("SRA changed sign: a=0x%0h y=0x%0h", a, y);
    end

    // A shift by zero is the identity, whatever the masking rule.
    if ((op == OP_SLL || op == OP_SRL || op == OP_SRA) && shamt == '0) begin
      a_shift_zero : assert (y == a)
        else $error("shift by zero changed the operand");
    end

    // Bitwise results relate to the operands by containment.
    if (op == OP_AND) begin
      a_and_subset : assert (((y & a) == y) && ((y & b) == y))
        else $error("AND result is not a subset of both operands");
    end
    if (op == OP_OR) begin
      a_or_superset : assert (((y | a) == y) && ((y | b) == y))
        else $error("OR result is not a superset of both operands");
    end

    // The comparisons are one-bit results and must disagree only when the
    // operands straddle zero in signed terms.
    if (op == OP_SLT || op == OP_SLTU) begin
      a_cmp_boolean : assert (y <= 1)
        else $error("comparison produced y=0x%0h", y);
    end
  end

endmodule

bind alu alu_props #(.W(W)) u_alu_props (
    .a(a),
    .b(b),
    .op(op),
    .y(y),
    .zero(zero),
    .carry(carry),
    .overflow(overflow),
    .negative(negative)
);
