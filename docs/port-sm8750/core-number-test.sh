#!/bin/bash
# Host test of the core numbering in xnuloader/loader.c (struct platform's core_shift/core_stride and
# the core_number()/core_mpidr() pair). It extracts those definitions out of loader.c itself, so it
# tests the shipped code rather than a copy of it, and it runs on the development machine: it proves
# the arithmetic, not the silicon. There is no dodge hardware here (docs/port-sm8750/loader.md).
#
#   docs/port-sm8750/core-number-test.sh        exit 0 = the eight SM8750 MPIDRs get eight numbers
#
# Redwood's behaviour is asserted too (one cluster: number == MPIDR >> 8), because it must not change.
set -e
cd "$(dirname "$(readlink -f "$0")")/../.."
T=$(mktemp -d)
trap 'rm -rf "$T"' EXIT

python3 - "$T/helpers.inc" <<'PY'
import sys
src = open('xnuloader/loader.c').read()
struct = src[src.index('struct platform {'):src.index('static const struct platform platform_qemu_virt')]
helpers = src[src.index("/*\n * A core's number, and the MPIDR of a number."):src.index('static void\nreboot(void)')]
open(sys.argv[1], 'w').write(struct + helpers)
PY

cat > "$T/test.c" <<'EOF'
#include <stdint.h>
#include <stdio.h>
#include <assert.h>
__HELPERS__
static const struct platform plat_redwood = { .name = "redwood", .cores = 8, .core_shift = 8, .core_stride = 0, .small_cores = 0x0f };
static const struct platform plat_dodge   = { .name = "dodge",   .cores = 8, .core_shift = 8, .core_stride = 6, .small_cores = 0x3f };
static const struct platform plat_qemu    = { .name = "qemu-virt", .cores = 8, .core_shift = 0, .core_stride = 0 };

int main(void)
{
	/* redwood: one cluster, the second affinity field is the number -- unchanged behaviour */
	for (uint32_t n = 0; n < 8; n++) {
		uint64_t m = core_mpidr(&plat_redwood, n);
		assert(m == ((uint64_t)n << 8));
		assert(core_number(&plat_redwood, m) == n);
	}
	assert(core_number(&plat_redwood, 0x700) == 7);
	/* qemu-virt: shift 0 */
	for (uint32_t n = 0; n < 8; n++) {
		assert(core_mpidr(&plat_qemu, n) == n);
		assert(core_number(&plat_qemu, n) == n);
	}
	/* dodge: six performance cores 0x0..0x500, then two prime cores 0x10000, 0x10100 */
	static const uint64_t want[8] = { 0x0, 0x100, 0x200, 0x300, 0x400, 0x500, 0x10000, 0x10100 };
	for (uint32_t n = 0; n < 8; n++) {
		uint64_t m = core_mpidr(&plat_dodge, n);
		if (m != want[n]) {
			printf("dodge %u -> %llx, want %llx\n", n, (unsigned long long)m, (unsigned long long)want[n]);
			return 1;
		}
		if (core_number(&plat_dodge, m) != n) {
			printf("dodge round trip %u failed\n", n);
			return 1;
		}
	}
	/* the collision the single-field version had: 0x10000 and 0x0 are different numbers now */
	assert(core_number(&plat_dodge, 0x10000) == 6);
	assert(core_number(&plat_dodge, 0x0) == 0);
	uint32_t seen = 0;
	for (int i = 0; i < 8; i++) seen |= 1u << core_number(&plat_dodge, want[i]);
	assert(seen == 0xff);
	/* small_cores 0x3f marks exactly the six performance cores (numbers 0..5) */
	for (int i = 0; i < 8; i++) {
		int is_small = (plat_dodge.small_cores >> core_number(&plat_dodge, want[i])) & 1;
		if (is_small != (i < 6)) { printf("small_cores bit %d wrong\n", i); return 1; }
	}
	printf("core numbering: redwood/qemu unchanged; dodge 0..5 -> 0x0..0x500, 6,7 -> 0x10000,0x10100\n");
	return 0;
}
EOF

python3 - "$T/helpers.inc" "$T/test.c" <<'PY'
import sys
helpers = open(sys.argv[1]).read()
src = open(sys.argv[2]).read().replace('__HELPERS__', helpers)
open(sys.argv[2], 'w').write(src)
PY
clang -std=c11 -Wall -O1 -o "$T/test" "$T/test.c"
"$T/test"
