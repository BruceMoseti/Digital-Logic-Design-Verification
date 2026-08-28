// Verilator harness shared by both FIR implementations. Verilator is invoked
// with --prefix Vdut so the same source drives either variant; the only
// difference is DUT_LATENCY.
//
// Stimulus runs in bursts. Coefficients change only while the pipeline is
// drained, which keeps the expected value of every in-flight sample unambiguous
// for both the 1-cycle and the 4-cycle datapath.

#include <verilated.h>

#include <array>
#include <chrono>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <deque>
#include <memory>
#include <random>
#include <vector>

#include "Vdut.h"
#include "golden.h"

#if !defined(DUT_DW) || !defined(DUT_CW) || !defined(DUT_ACCW) || \
    !defined(DUT_LATENCY)
#error "DUT_DW, DUT_CW, DUT_ACCW and DUT_LATENCY must all be defined"
#endif

namespace {

constexpr int kTaps = 8;
constexpr int kMaxReports = 10;
constexpr int kBurstCycles = 64;

struct Harness {
  Vdut *dut;
  VerilatedContext *ctx;
  std::array<int64_t, kTaps> coeffs{};
  std::array<int64_t, kTaps> hist{};
  std::deque<int64_t> expected;
  uint64_t samples_in = 0;
  uint64_t samples_out = 0;
  uint64_t mismatches = 0;

  void eval() {
    ctx->timeInc(1);
    dut->eval();
  }

  void reset() {
    dut->rst_n = 0;
    dut->in_valid = 0;
    dut->in_sample = 0;
    dut->clk = 0;
    eval();
    for (int i = 0; i < 2; i++) {
      dut->clk = 1;
      eval();
      dut->clk = 0;
      eval();
    }
    dut->rst_n = 1;
    hist.fill(0);
    expected.clear();
  }

  void set_coeffs(const std::array<int64_t, kTaps> &c) {
    coeffs = c;
    uint64_t flat = 0;
    const uint64_t field_mask = (1ULL << DUT_CW) - 1;
    for (int i = 0; i < kTaps; i++)
      flat |= (static_cast<uint64_t>(c[i]) & field_mask) << (i * DUT_CW);
    dut->coeff_flat = flat;
  }

  // Applies one clock cycle with the currently driven inputs and checks any
  // output that appears.
  void step(bool valid, int64_t sample) {
    dut->in_valid = valid;
    dut->in_sample = static_cast<uint64_t>(sample) & ((1ULL << DUT_DW) - 1);

    if (valid) {
      for (int i = kTaps - 1; i > 0; i--) hist[i] = hist[i - 1];
      hist[0] = sample;
      expected.push_back(golden::fir8(coeffs, hist));
      samples_in++;
    }

    dut->clk = 1;
    eval();

    if (dut->out_valid) {
      const int64_t got = golden::sign_extend(dut->out_sample, DUT_ACCW);
      samples_out++;
      if (expected.empty()) {
        mismatches++;
        if (mismatches <= kMaxReports)
          std::printf("[FAIL] out_valid with no pending sample, got=%lld\n",
                      static_cast<long long>(got));
      } else {
        const int64_t exp = expected.front();
        expected.pop_front();
        if (got != exp) {
          mismatches++;
          if (mismatches <= kMaxReports)
            std::printf("[FAIL] sample %llu: rtl=%lld model=%lld\n",
                        static_cast<unsigned long long>(samples_out),
                        static_cast<long long>(got),
                        static_cast<long long>(exp));
        }
      }
    }

    dut->clk = 0;
    eval();
  }

  void drain() {
    for (int i = 0; i < DUT_LATENCY + 2; i++) step(false, 0);
    if (!expected.empty()) {
      mismatches++;
      std::printf("[FAIL] %zu samples never produced an output\n",
                  expected.size());
      expected.clear();
    }
  }
};

int64_t pick(std::mt19937_64 &rng, int bits) {
  const int64_t lo = -(1LL << (bits - 1));
  const int64_t hi = (1LL << (bits - 1)) - 1;
  if ((rng() % 100) < 25) {
    const int64_t corners[] = {0, 1, -1, lo, hi};
    return corners[rng() % 5];
  }
  return lo + static_cast<int64_t>(rng() % static_cast<uint64_t>(hi - lo + 1));
}

}  // namespace

int main(int argc, char **argv) {
  uint64_t vectors = 20000;
  uint64_t seed = 1;

  for (int i = 1; i < argc; i++) {
    if (!std::strcmp(argv[i], "--vectors") && i + 1 < argc) {
      vectors = std::strtoull(argv[++i], nullptr, 0);
    } else if (!std::strcmp(argv[i], "--seed") && i + 1 < argc) {
      seed = std::strtoull(argv[++i], nullptr, 0);
    } else {
      std::fprintf(stderr, "unknown argument: %s\n", argv[i]);
      return 2;
    }
  }

  const auto contextp = std::make_unique<VerilatedContext>();
  contextp->commandArgs(argc, argv);
  const auto dut = std::make_unique<Vdut>(contextp.get(), "fir");

  Harness h{dut.get(), contextp.get()};
  std::mt19937_64 rng(seed);

  h.reset();

  const uint64_t bursts = (vectors + kBurstCycles - 1) / kBurstCycles;
  for (uint64_t burst = 0; burst < bursts; burst++) {
    std::array<int64_t, kTaps> c{};
    for (int i = 0; i < kTaps; i++) c[i] = pick(rng, DUT_CW);
    h.set_coeffs(c);

    for (int i = 0; i < kBurstCycles; i++) {
      const bool valid = (rng() % 100) < 70;
      h.step(valid, valid ? pick(rng, DUT_DW) : 0);
    }
    h.drain();
  }

  dut->final();

  const bool pass = (h.mismatches == 0) && (h.samples_in == h.samples_out);
  std::printf("RESULT: %s latency=%d samples_in=%llu samples_out=%llu "
              "mismatches=%llu\n",
              pass ? "PASS" : "FAIL", DUT_LATENCY,
              static_cast<unsigned long long>(h.samples_in),
              static_cast<unsigned long long>(h.samples_out),
              static_cast<unsigned long long>(h.mismatches));
  return pass ? 0 : 1;
}
