// Directed edge-case tests for the ALU.
//
// Every expected result here is derived by hand from the flag definitions in
// rtl/alu.v, independently of the C++ golden model. The C++ harness proves the
// RTL matches the model exhaustively; this file is what pins the model itself
// to the specification, so a shared misreading of, say, the borrow convention
// cannot pass both.
//
// zero and negative are derived from the expected result rather than listed per
// vector: that is still an independent check of the DUT's flag logic, and it
// removes 70 hand-copied bits that would only add transcription errors.

`timescale 1ns / 1ps

module alu_tb;

  import tb_pkg::*;

  localparam int W = 32;

  localparam logic [3:0] OP_ADD  = 4'd0;
  localparam logic [3:0] OP_SUB  = 4'd1;
  localparam logic [3:0] OP_AND  = 4'd2;
  localparam logic [3:0] OP_OR   = 4'd3;
  localparam logic [3:0] OP_XOR  = 4'd4;
  localparam logic [3:0] OP_SLL  = 4'd5;
  localparam logic [3:0] OP_SRL  = 4'd6;
  localparam logic [3:0] OP_SRA  = 4'd7;
  localparam logic [3:0] OP_SLT  = 4'd8;
  localparam logic [3:0] OP_SLTU = 4'd9;

  logic [W-1:0] a, b, y;
  logic [3:0]   op;
  logic         zero, carry, overflow, negative;

  Checker chk;

  alu #(.W(W)) dut (
      .a(a),
      .b(b),
      .op(op),
      .y(y),
      .zero(zero),
      .carry(carry),
      .overflow(overflow),
      .negative(negative)
  );

  task automatic check(string label, logic [3:0] op_i, logic [W-1:0] a_i, logic [W-1:0] b_i,
                       logic [W-1:0] exp_y, bit exp_carry, bit exp_ovf);
    a  = a_i;
    b  = b_i;
    op = op_i;
    #1;
    chk.eq(64'(y), 64'(exp_y), $sformatf("%s: result", label));
    chk.ok(carry == exp_carry, $sformatf("%s: carry got=%b expected=%b", label, carry, exp_carry));
    chk.ok(overflow == exp_ovf,
           $sformatf("%s: overflow got=%b expected=%b", label, overflow, exp_ovf));
    chk.ok(zero == (exp_y == '0), $sformatf("%s: zero got=%b", label, zero));
    chk.ok(negative == exp_y[W-1], $sformatf("%s: negative got=%b", label, negative));
  endtask

  initial begin
    chk = new("alu_directed");

    //                                            a                b            expected y   carry ovf
    check("add small",       OP_ADD,  32'd1,            32'd1,            32'd2,            0, 0);
    check("add wrap",        OP_ADD,  32'hFFFF_FFFF,    32'h0000_0001,    32'h0000_0000,    1, 0);
    check("add ovf max+1",   OP_ADD,  32'h7FFF_FFFF,    32'h0000_0001,    32'h8000_0000,    0, 1);
    check("add ovf min+min", OP_ADD,  32'h8000_0000,    32'h8000_0000,    32'h0000_0000,    1, 1);
    check("add carry no ovf",OP_ADD,  32'hFFFF_FFFF,    32'hFFFF_FFFF,    32'hFFFF_FFFE,    1, 0);

    check("sub to zero",     OP_SUB,  32'd5,            32'd5,            32'h0000_0000,    0, 0);
    check("sub borrow",      OP_SUB,  32'h0000_0000,    32'h0000_0001,    32'hFFFF_FFFF,    1, 0);
    check("sub min-1",       OP_SUB,  32'h8000_0000,    32'h0000_0001,    32'h7FFF_FFFF,    0, 1);
    check("sub max-neg1",    OP_SUB,  32'h7FFF_FFFF,    32'hFFFF_FFFF,    32'h8000_0000,    1, 1);
    check("sub neg1-max",    OP_SUB,  32'hFFFF_FFFF,    32'h7FFF_FFFF,    32'h8000_0000,    0, 0);

    check("and mask",        OP_AND,  32'hF0F0_F0F0,    32'h0FF0_0FF0,    32'h00F0_00F0,    0, 0);
    check("or fill",         OP_OR,   32'hF0F0_F0F0,    32'h0F0F_0F0F,    32'hFFFF_FFFF,    0, 0);
    check("xor invert",      OP_XOR,  32'hAAAA_AAAA,    32'hFFFF_FFFF,    32'h5555_5555,    0, 0);
    check("xor self",        OP_XOR,  32'h1234_5678,    32'h1234_5678,    32'h0000_0000,    0, 0);

    check("sll to msb",      OP_SLL,  32'h0000_0001,    32'd31,           32'h8000_0000,    0, 0);
    check("sll shamt 32",    OP_SLL,  32'h0000_0001,    32'd32,           32'h0000_0001,    0, 0);
    check("sll shamt 33",    OP_SLL,  32'h0000_0001,    32'd33,           32'h0000_0002,    0, 0);
    check("sll byte",        OP_SLL,  32'h0000_00FF,    32'd24,           32'hFF00_0000,    0, 0);

    check("srl from msb",    OP_SRL,  32'h8000_0000,    32'd31,           32'h0000_0001,    0, 0);
    check("srl shamt 32",    OP_SRL,  32'h8000_0000,    32'd32,           32'h8000_0000,    0, 0);
    check("srl nibble",      OP_SRL,  32'hF000_0000,    32'd4,            32'h0F00_0000,    0, 0);

    check("sra sign fill",   OP_SRA,  32'h8000_0000,    32'd31,           32'hFFFF_FFFF,    0, 0);
    check("sra one",         OP_SRA,  32'h8000_0000,    32'd1,            32'hC000_0000,    0, 0);
    check("sra positive",    OP_SRA,  32'h7FFF_FFFF,    32'd4,            32'h07FF_FFFF,    0, 0);
    check("sra all ones",    OP_SRA,  32'hFFFF_FFFF,    32'd5,            32'hFFFF_FFFF,    0, 0);
    check("sra shamt 32",    OP_SRA,  32'h8000_0000,    32'd32,           32'h8000_0000,    0, 0);

    check("slt neg lt pos",  OP_SLT,  32'hFFFF_FFFF,    32'h0000_0001,    32'h0000_0001,    0, 0);
    check("slt pos lt neg",  OP_SLT,  32'h0000_0001,    32'hFFFF_FFFF,    32'h0000_0000,    0, 0);
    check("slt min lt max",  OP_SLT,  32'h8000_0000,    32'h7FFF_FFFF,    32'h0000_0001,    0, 0);
    check("slt equal",       OP_SLT,  32'd5,            32'd5,            32'h0000_0000,    0, 0);

    check("sltu max lt one", OP_SLTU, 32'hFFFF_FFFF,    32'h0000_0001,    32'h0000_0000,    0, 0);
    check("sltu one lt max", OP_SLTU, 32'h0000_0001,    32'hFFFF_FFFF,    32'h0000_0001,    0, 0);
    check("sltu equal",      OP_SLTU, 32'd5,            32'd5,            32'h0000_0000,    0, 0);

    check("undef op 10",     4'd10,   32'h1234_5678,    32'h9ABC_DEF0,    32'h0000_0000,    0, 0);
    check("undef op 15",     4'd15,   32'h1234_5678,    32'h9ABC_DEF0,    32'h0000_0000,    0, 0);

    chk.report();
    $finish;
  end

endmodule
