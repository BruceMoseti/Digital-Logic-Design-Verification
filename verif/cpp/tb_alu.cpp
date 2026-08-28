// Verilator harness for the ALU: compares every result and flag against the C++
// golden model. At DUT_W = 8 the whole input space (a, b, op) fits in about a
// million vectors, so --exhaustive is a complete check of the mapped function
// rather than a sample of it. Wider instances use directed corner values mixed
// into a random stream.

#include <verilated.h>

#include <chrono>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <memory>
#include <random>
#include <vector>

#include "Vdut.h"
#include "golden.h"

#ifndef DUT_W
#error "DUT_W must be defined and match the -GW parameter given to Verilator"
#endif

namespace {

constexpr int kMaxReports = 10;

uint64_t mask(uint64_t v) {
  return (DUT_W >= 64) ? v : (v & ((1ULL << DUT_W) - 1));
}

golden::AluResult read_dut(Vdut *dut) {
  golden::AluResult r;
  r.y = dut->y;
  r.zero = dut->zero;
  r.carry = dut->carry;
  r.overflow = dut->overflow;
  r.negative = dut->negative;
  return r;
}

void print_result(const char *label, const golden::AluResult &r) {
  std::printf("  %-6s y=0x%llx z=%d c=%d v=%d n=%d\n", label,
              static_cast<unsigned long long>(r.y), r.zero, r.carry, r.overflow,
              r.negative);
}

std::vector<uint64_t> corner_values() {
  const uint64_t top = 1ULL << (DUT_W - 1);
  return {0, 1, 2, mask(~0ULL), mask(~0ULL - 1), top, top - 1, top + 1,
          mask(DUT_W), mask(DUT_W - 1), mask(DUT_W + 1)};
}

struct Stats {
  uint64_t vectors = 0;
  uint64_t mismatches = 0;
};

void check(Vdut *dut, uint64_t a, uint64_t b, int op, Stats &st) {
  dut->a = a;
  dut->b = b;
  dut->op = op;
  dut->eval();

  const golden::AluResult got = read_dut(dut);
  const golden::AluResult exp = golden::alu(a, b, op, DUT_W);
  st.vectors++;
  if (!(got == exp)) {
    st.mismatches++;
    if (st.mismatches <= kMaxReports) {
      std::printf("[FAIL] op=%s a=0x%llx b=0x%llx\n", golden::alu_op_name(op),
                  static_cast<unsigned long long>(a),
                  static_cast<unsigned long long>(b));
      print_result("rtl", got);
      print_result("model", exp);
    }
  }
}

}  // namespace

int main(int argc, char **argv) {
  bool exhaustive = false;
  uint64_t vectors = 100000;
  uint64_t seed = 1;

  for (int i = 1; i < argc; i++) {
    if (!std::strcmp(argv[i], "--exhaustive")) {
      exhaustive = true;
    } else if (!std::strcmp(argv[i], "--vectors") && i + 1 < argc) {
      vectors = std::strtoull(argv[++i], nullptr, 0);
    } else if (!std::strcmp(argv[i], "--seed") && i + 1 < argc) {
      seed = std::strtoull(argv[++i], nullptr, 0);
    } else {
      std::fprintf(stderr, "unknown argument: %s\n", argv[i]);
      return 2;
    }
  }

  if (exhaustive && DUT_W > 10) {
    std::fprintf(stderr, "--exhaustive is only practical for DUT_W <= 10\n");
    return 2;
  }

  const auto contextp = std::make_unique<VerilatedContext>();
  contextp->commandArgs(argc, argv);
  const auto dut = std::make_unique<Vdut>(contextp.get(), "alu");

  Stats st;
  const auto t0 = std::chrono::steady_clock::now();

  if (exhaustive) {
    const uint64_t n = 1ULL << DUT_W;
    for (uint64_t a = 0; a < n; a++)
      for (uint64_t b = 0; b < n; b++)
        for (int op = 0; op < 16; op++) check(dut.get(), a, b, op, st);
  } else {
    std::mt19937_64 rng(seed);
    const std::vector<uint64_t> corners = corner_values();
    for (uint64_t i = 0; i < vectors; i++) {
      const bool corner_a = (rng() % 100) < 25;
      const bool corner_b = (rng() % 100) < 25;
      const uint64_t a = corner_a ? corners[rng() % corners.size()] : mask(rng());
      const uint64_t b = corner_b ? corners[rng() % corners.size()] : mask(rng());
      check(dut.get(), a, b, static_cast<int>(rng() % 16), st);
    }
  }

  dut->final();

  const double secs = std::chrono::duration<double>(
                          std::chrono::steady_clock::now() - t0)
                          .count();
  const bool pass = (st.mismatches == 0);
  std::printf("RESULT: %s width=%d mode=%s vectors=%llu mismatches=%llu "
              "elapsed=%.3fs rate=%.0f vec/s\n",
              pass ? "PASS" : "FAIL", DUT_W,
              exhaustive ? "exhaustive" : "random",
              static_cast<unsigned long long>(st.vectors),
              static_cast<unsigned long long>(st.mismatches), secs,
              secs > 0 ? st.vectors / secs : 0.0);
  return pass ? 0 : 1;
}
