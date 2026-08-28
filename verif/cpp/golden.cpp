#include "golden.h"

#include <cassert>
#include <cstddef>

namespace golden {

namespace {

uint64_t mask_to(uint64_t v, int width) {
  return (width >= 64) ? v : (v & ((1ULL << width) - 1));
}

// Matches $clog2 for width >= 2, with the same floor of 1 the RTL applies.
int shift_amount_bits(int width) {
  if (width <= 2) return 1;
  int bits = 0;
  while ((1 << bits) < width) bits++;
  return bits;
}

bool msb(uint64_t v, int width) { return (v >> (width - 1)) & 1ULL; }

}  // namespace

int64_t sign_extend(uint64_t v, int bits) {
  if (bits >= 64) return static_cast<int64_t>(v);
  const uint64_t m = 1ULL << (bits - 1);
  v = mask_to(v, bits);
  return static_cast<int64_t>((v ^ m) - m);
}

const char *alu_op_name(int op) {
  switch (op) {
    case ALU_ADD: return "ADD";
    case ALU_SUB: return "SUB";
    case ALU_AND: return "AND";
    case ALU_OR: return "OR";
    case ALU_XOR: return "XOR";
    case ALU_SLL: return "SLL";
    case ALU_SRL: return "SRL";
    case ALU_SRA: return "SRA";
    case ALU_SLT: return "SLT";
    case ALU_SLTU: return "SLTU";
    default: return "UNDEF";
  }
}

AluResult alu(uint64_t a, uint64_t b, int op, int width) {
  assert(width >= 4 && width <= 63);
  a = mask_to(a, width);
  b = mask_to(b, width);

  const uint64_t shamt = b & ((1ULL << shift_amount_bits(width)) - 1);
  const int64_t sa = sign_extend(a, width);
  const int64_t sb = sign_extend(b, width);

  AluResult r;
  switch (op) {
    case ALU_ADD: {
      const uint64_t sum = a + b;
      r.y = mask_to(sum, width);
      r.carry = (sum >> width) & 1ULL;
      r.overflow = (msb(a, width) == msb(b, width)) &&
                   (msb(r.y, width) != msb(a, width));
      break;
    }
    case ALU_SUB: {
      r.y = mask_to(a - b, width);
      r.carry = (a < b);
      r.overflow = (msb(a, width) != msb(b, width)) &&
                   (msb(r.y, width) != msb(a, width));
      break;
    }
    case ALU_AND:  r.y = a & b; break;
    case ALU_OR:   r.y = a | b; break;
    case ALU_XOR:  r.y = a ^ b; break;
    case ALU_SLL:  r.y = mask_to(a << shamt, width); break;
    case ALU_SRL:  r.y = a >> shamt; break;
    case ALU_SRA:  r.y = mask_to(static_cast<uint64_t>(sa >> shamt), width); break;
    case ALU_SLT:  r.y = (sa < sb) ? 1 : 0; break;
    case ALU_SLTU: r.y = (a < b) ? 1 : 0; break;
    default:       r.y = 0; break;
  }

  r.zero = (r.y == 0);
  r.negative = msb(r.y, width);
  return r;
}

int64_t fir8(const std::array<int64_t, 8> &coeffs,
             const std::array<int64_t, 8> &samples) {
  int64_t acc = 0;
  for (std::size_t i = 0; i < coeffs.size(); i++) acc += coeffs[i] * samples[i];
  return acc;
}

}  // namespace golden
