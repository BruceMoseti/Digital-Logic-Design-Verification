// Golden reference models for the RTL under test.
//
// These are written from the module specifications, independently of the RTL, so
// that a shared misunderstanding between design and testbench shows up as a
// mismatch. The directed SystemVerilog tests use hand-computed expected values
// and act as a second, independent anchor on the same specifications.

#pragma once

#include <array>
#include <cstdint>

namespace golden {

enum AluOp : int {
  ALU_ADD = 0,
  ALU_SUB = 1,
  ALU_AND = 2,
  ALU_OR = 3,
  ALU_XOR = 4,
  ALU_SLL = 5,
  ALU_SRL = 6,
  ALU_SRA = 7,
  ALU_SLT = 8,
  ALU_SLTU = 9,
  ALU_NUM_OPS = 10,
};

const char *alu_op_name(int op);

struct AluResult {
  uint64_t y = 0;
  bool zero = false;
  bool carry = false;
  bool overflow = false;
  bool negative = false;

  bool operator==(const AluResult &o) const {
    return y == o.y && zero == o.zero && carry == o.carry &&
           overflow == o.overflow && negative == o.negative;
  }
};

// width must be in [4, 63]. a and b are interpreted as width-bit values; bits
// above width are ignored.
AluResult alu(uint64_t a, uint64_t b, int op, int width);

// Sum of eight signed products. samples[0] is the newest sample and pairs with
// coeffs[0]. The RTL accumulator is wide enough that this never overflows.
int64_t fir8(const std::array<int64_t, 8> &coeffs,
             const std::array<int64_t, 8> &samples);

// Sign-extend the low `bits` of `v` to a full int64_t.
int64_t sign_extend(uint64_t v, int bits);

}  // namespace golden
