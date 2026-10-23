# Kernel side: what the SM8750 port changes in the redwood driver set

Teammate: kernel-soc. Task: task-2. Evidence base: `docs/port-sm8750/FACTS.md` (not re-researched).

## Verification ceiling — read this first

**No kernel has been booted on an SM8750 phone, and none can be from here.** There is no OnePlus 13
in this environment and nothing can be flashed. Specifically:

- **Not done:** any run on hardware; any probe of a real SM8750 peripheral; any measurement.
- **Done:** each touched file compiles clean with the tree's own exact compile line
  (`xnu-clang` + the flags from the generated `bsd/DEVELOPMENT/Makefile`), and `redwood_soc.c`
  is listed in `bsd/conf/files`, so it is part of the bsd component. Confirmation that it reaches
  the link is build-verify's step (`nm` on the unstripped kernel), not mine.
- **Not done here:** the full `./xnu-build.sh -j12 -k` link (build-verify owns the obj dir; I did
  not run make to avoid colliding with their builds).

So: the mechanism is real code with real call sites, and it compiles — but "the kernel boots on
dodge" is **not** claimed and cannot be claimed from this environment.

## Mechanism chosen, and why

One table, one discriminator, one fallback, in `bsd/sys/redwood_soc.h` (declaration) and
`bsd/dev/redwood_soc.c` (the rows and the lookup).

**Discriminator: `/arm-io` `device_type`.** The loader already writes it from the row of its own
platform table it picked for the phone in front of it — `xnuloader/loader.c:3232`,
`dt_prop_str(&w, "device_type", plat->name)` — and the kernel already depends on that node for its
interrupt controller (`osfmk/arm64/gic_v3_irq.c:428-434` reads `/arm-io/gic` `reg`). So the
kernel and the loader cannot disagree, no boot-arg has to be kept in step with the hardware, and a
device added to the loader later is identified with no kernel change.

Alternatives rejected, for the record: a boot-arg (`soc=dodge`) adds a second thing that must be
right on the command line and can silently disagree with the hardware; a compile-time `#define`
would fork the build, and this tree ships one kernel for many phones; a per-driver `#define` per SoC
would multiply by 33 files.

**Fallback: redwood.** `redwood_soc()` returns the redwood row when `/arm-io` is absent, the
property is absent, `SecureDTLookupEntry`/`SecureDTGetProperty` fail (`kError` when the DT is not
initialised — `pexpert/gen/device_tree.c:334`), or the name matches no row. That is exactly what the
kernel did before this file existed, so **behaviour on redwood is unchanged**; the numbers in its row
are the same literals the drivers had.

Rows match on a small list of names (`names[]`), not one string, because the loader's name for a
device is the loader's to choose: SM8750's row accepts `"dodge"` (the loader's `platform_dodge`,
which loader-port is adding), plus `"sm8750"`/`"pakala"` as aliases. **Risk to keep in mind:** a
loader row whose name is in no list falls back silently to redwood — correct for behaviour, wrong for
SM8750's addresses. So if either side renames, both must change. (Flagged by build-verify too.)

What deliberately is *not* in the table, because it already follows the SoC by itself:

- the interrupt controller — the kernel reads `/arm-io/gic` and the loader fills it from its row's
  `gic_dist`/`gic_redist`;
- core count and core numbering into the DT — the loader writes `/cpus/cpu@N` `reg` from the
  MPIDRs PSCI reported.

## The table: constant | redwood value | SM8750 value | confidence | source

Line numbers are in `xnu/files/bsd/dev/redwood_soc.c` (identical in the tree at
`xnu-src/xnu-8796.121.2`). "redwood source" is the original `file:line` the literal came from,
i.e. the proof that redwood is unchanged.

| constant | redwood value | SM8750 value | confidence | source |
|---|---|---|---|---|
| row name | `"redwood"` | `"dodge"` (+ aliases `sm8750`, `pakala`) | high | SM8750 row :82; loader writes it at xnuloader/loader.c:3232 |
| `epss_base` | `0x18591000` (:27, from redwood_cpufreq.c:57 `EPSS_PHYS`) | `0x17D91000` (:93) | **UNVERIFIED** | sm8750 has no cpufreq/EPSS node in mainline *or* the vendor DT; value is the sibling-generation pattern (eliza/milos/sar2130p = 0x17D91000/2000/3000). FACTS.md "cpufreq / EPSS" |
| `epss_domain_size` | `0x1000` (:28, from redwood_cpufreq.c:58) | `0x1000` | **UNVERIFIED** | same as above (siblings are 0x1000 apart) |
| `epss_domains` | `3` (:29, from redwood_cpufreq.c:59) | **`0` = never write EPSS** (:95) | high (as a guard) | SM8750 address unverified ⇒ disabling is the only safe value. FACTS.md says keep cpufreq off |
| `epss_domain_of[]` | `{0,0,0,0,1,1,1,2, 0xff…}` (:30-33, from redwood_cpufreq.c:82 `domain_of()`) | `{0,0,0,0,0,0,1,1, 0xff…}` (:96-99) | low (unused while `epss_domains==0`) | the 6+2 cluster split, vendor DT `cpu-map` cluster0/cluster1 |
| `core_shift` | `8` (:35) | `8` (:102) | high | both SoCs put the core number in MPIDR affinity level 1; dpc dodge DT `reg` = 0x0,0x100,…; FACTS.md "CPUs" |
| `core_stride` | `0` (:36 — redwood: one field, 0-7) | `6` (:103 — cluster 1 continues at 6) | high | dodge DT: cluster0 = cores 0-5, cluster1 = cpu@10000/cpu@10100 ⇒ 6,7. FACTS.md agrees; loader-port is aligning `platform` to this |
| `ufshc_phys` | `0x1d84000` (:38, from redwood_ufshc.c:76 `UFSHC_PHYS`) | `0x1d84000` (:105) | high | dodge DT `ufs@1d84000` `qcom,sm8750-ufshc` = redwood's HC_PA. FACTS.md "UFS" |
| `rsc_phys` | `0x18220000` (:40, from redwood_cpufreq.c:381 `RSC_PHYS`) | **`0` = no vote** (:113) | UNKNOWN for SM8750 | SM8750's rpmh RSC address not in the vendor DT and not verified; 0 is deliberate. See "address 0" below |
| `cmd_db_phys` / size | `0x80860000`/`0x20000` (:42-43, from redwood_cpufreq.c:309-310) | **`0`** (:115-116) | UNKNOWN for SM8750 | cmd-db is placed at run time by firmware; nothing in the documents read here gives SM8750's |
| `spmi_core_phys` / size | `0x0c440000`/`0x1100` (:45-46, from redwood_buttons.c:96-97) | `0x0c400000`/`0x3000` (:128-129) | high for the window, **medium** for the version/channel/owner offsets | dodge DT `spmi@c400000` `reg-names = core/chnls/obsrvr/intr/cnfg`; the registers this driver reads (ARB_VERSION 0x000, ARB_FEATURES 0x004, ARB_CHANNEL 0x900+) are inside the 0x3000 `core` window |
| `spmi_cnfg_phys` / size | `0x0c40a000`/`0x1000` (:47-48, from redwood_buttons.c:98-99) | `0x0c42d000`/`0x4000` (:130-131) | high | same DT node, `cnfg` window; ARB_OWNER 0x700+ is inside it |
| `spmi_observer_phys` / size | `0x0e600000`/`0x10000` (:49-50, from redwood_buttons.c:100-101) | `0x0c440000`/`0x10000` (:132-133) | high for the base, **medium** for the per-system stride | `obsrvr` = 0xc440000 size 0x80000; 0x80000/8 systems = 0x10000 each, and DT `qcom,ee = 0` matches `ARB_SYSTEM 0` |
| `spmi_pon_id` / name | `0x013` (:51, from redwood_buttons.c:152) | `0x013` (:134) | high | dodge DT `pmic@0` (pm8550) → `pon@1300` `qcom,pmk8350-pon` `reg = <0x1300 0x800>`, `pwrkey` `qcom,pmk8350-pwrkey` ⇒ slave 0, 0x1300, same as redwood |
| `spmi_pin_id` / name | `0x18d` (:53, from redwood_buttons.c:153) | `0x18d` (:136) | medium | dodge DT: only volume-**down** exists as a key, `gpio-keys/key-volume-down` → `pm8550 gpio@8800` **GPIO6** (`gpio-ranges` base 0), i.e. slave 1, 0x8d00, id 0x18d. Same id as redwood's PM7325 GPIO6 **coincidentally** — different chip |
| `tlmm_phys` / size | `0x0f100000`/`0x100000` (:56-57) | `0x0f100000`/`0x102000` (:139-140) | high | dodge DT `pinctrl@f100000` `qcom,sm8750-tlmm` `reg = <0xf100000 0x102000>`; same base as redwood, size is 0x2000 larger. Not used by a driver yet |
| `gcc_phys` | `0x00100000` (:58, from redwood_goodix.c:265 `GCC_PHYS`) | `0x00100000` (:141) | high (address) / **low** (register offsets) | dodge DT `clock-controller@100000` `qcom,sm8750-gcc` size 0x1f4200. The addresses *inside* GCC that redwood_goodix.c uses (0x52008, 0x18004…) are sc7280's and were **not** verified for SM8750 |
| `gic_dist` / redist | `0x17A00000`/`0x17A60000` (:59-60) | `0x16000000`/`0x16080000` (:142-143) | high | dodge DT `arm,gic-v3`; **reference only** — the kernel reads `/arm-io/gic`, which the loader fills from its own row |

## Call sites: the three files that actually go through the table

All three keep redwood behaviour identical: the values are the same literals, reached through the
table instead of a `#define`.

### `bsd/dev/redwood_cpufreq.c` (68 insertions / 43 deletions)

- `EPSS_PHYS`/`EPSS_DOMAIN_SIZE`/`EPSS_DOMAINS` (`:57-59`) removed → `soc->epss_base`,
  `soc->epss_domain_size`, `soc->epss_domains`. `raise_domain()` now takes the row.
- `domain_of()`'s `core < 4 ? 0 : core < 7 ? 1 : 2` (`:82`) removed → `redwood_soc_domain()`
  (table lookup), and the core *number* itself → `redwood_soc_core()` so SM8750's two-field
  numbering (cores 6,7) is right.
- **`epss_domains == 0` ⇒ the whole file does nothing.** `cpufreq_wanted()` returns false and says
  why (`cpufreq: not done: no EPSS address is known for this SoC`), so with `cpufreq=1` on SM8750
  **no EPSS register is ever touched**. This is the guard that makes the unverified address safe.
- `CMD_DB_PHYS`/`CMD_DB_SIZE` (`:309-310`), `RSC_PHYS`/`RSC_SIZE` (`:381-382`) removed →
  `soc->cmd_db_phys/size`, `soc->rsc_phys/size`; `ddr_look`, `ddr_slots`, `cmd_db_address`,
  `ddr_raise` all take the row.
- The `cpufreq=` value is still parsed into `enabled` before the guard, so the pre-existing
  `membench=` fall-through behaviour (`cpufreq=2` with no `membench=` meaning `membench=2`) is
  unchanged.

### `bsd/dev/redwood_buttons.c` (22 insertions / 15 deletions)

- `ARB_CORE_PHYS/SIZE`, `ARB_CNFG_PHYS/SIZE`, `ARB_OBSERVER_PHYS/SIZE` (`:96-101`) removed →
  `soc->spmi_*`. `ARB_OBSERVER_STRIDE 0x10000` replaces the magic `0x10000UL` in `spmi_read()`.
- `pon`/`pin` are no longer initialised at `:152-153`; `buttons_thread()` fills name+id from the row,
  so SM8750's `"the PM8550's power-on block"`/`"GPIO6 of the PM8550"` are named correctly in the log.
- The read-only discipline of this driver is untouched.

### `bsd/dev/redwood_ufshc.c` (8 insertions / 4 deletions)

- `UFSHC_PHYS` (`:76`) removed → `redwood_soc()->ufshc_phys` at the loader cross-check
  (`:1157`), the `ml_io_map` (`:1170`) and the log line (`:1189`). Same value on both SoCs, so
  the loader's `hc_pa` comparison still holds on dodge.

## `rsc_phys`/`cmd_db_phys` = 0 for SM8750: guarded, never mapped

Stated explicitly because address 0 would otherwise be mapped and read. **Every path that uses either
field tests for 0 first:**

1. `ddr_raise()` — `if (soc->rsc_phys == 0 || soc->cmd_db_phys == 0) { tell("ddr: no vote: no
   RPMh/cmd-db address is known for this SoC…"); return; }` **before** `cmd_db_address()` and
   `ml_io_map(soc->rsc_phys, …)`. So with `ddr=2` (the default) on SM8750 nothing is mapped.
2. `redwood_cpufreq_init()` — the `ddr=1` diagnostic path is likewise wrapped: `if (soc->cmd_db_phys
   == 0 || soc->rsc_phys == 0) { tell("ddr: nothing to look at…"); } else { ddr_look(soc);
   ddr_slots(soc); }`. So `ddr=1` on SM8750 also maps nothing.
3. `redwood_ddr_quiesce()` (the way back to the loader) returns immediately unless `ddr_voted` is
   set, and `ddr_voted` can only become true through `ddr_raise()`, which the guard above blocks.
   So the quiesce path cannot reach `ddr_rsc` either.

Net effect on dodge: no RPMh vote is made, and therefore none is torn down on the way out — which
matches milestone 1's boot args. **Follow-up:** to enable `ddr=` on SM8750, fill both fields and
re-check.

## What is still unknown (follow-ups, not guesses)

1. **SM8750 EPSS base / domain count / domain split** — unverified (no mainline node, none in the
   vendor DT). Blocks `cpufreq=1` on dodge. One on-hardware read of `0x17D91000/2000/3000`, or one
   line of a Linux boot on the same phone, settles it; then set `epss_domains = 3` (or whatever the
   read shows).
2. **SM8750 RPMh RSC address and cmd-db location** — unknown, hence `rsc_phys`/`cmd_db_phys` = 0 and
   no memory-bandwidth vote on dodge.
3. **SPMI arbiter version on SM8750** — the driver accepts version 5 only
   (`ARB_VERSION_5 <= v < ARB_VERSION_7`). sm8750's DT says `qcom,spmi-pmic-arb` with an
   `intr`/`chnls` layout that *looks* like v5, but nothing here proves the version register reads
   `0x50000000`. If it reads v7 the driver will say so and leave the keys alone — a safe failure, but
   the power key then does nothing.
4. **The per-system observer stride (0x10000) on SM8750** — derived from 0x80000/8, not observed.
5. **Volume up on dodge** — the vendor DT has no second key: only `key-volume-down` (PM8550 GPIO6).
   So on SM8750 the driver will watch power and volume-down, and volume-up has no input to watch.
   Nothing to fix in code; it needs a DT/hardware check of whether volume-up is a PMIC GPIO the DT
   omits or a different key path entirely.
6. **GIC redistributor stride** — the frame walk in `osfmk/arm64/gic_v3_irq.c` used to be a
   hardcoded `GICR_FRAME_SIZE 0x20000`, which is right for redwood/QEMU and **wrong for SM8750**
   (its frames are 0x40000 apart across a 0x200000 region): the walk stepped into the middle of
   frames, matched no `GICR_TYPER` affinity, and panicked `gic: no redistributor for MPIDR ...`
   before the kernel could start. Fixed, not merely documented — `gic_v3_irq_cpu_init()` now reads
   `redistributor-stride` from `/arm-io/gic` next to `reg` into `gicr_stride` and
   `gic_find_redistributor()` steps by that; `GICR_FRAME_SIZE` became
   `GICR_FRAME_SIZE_DEFAULT 0x20000`, the value used when the property is absent. Two things to
   keep in mind: the property is written as **two 32-bit cells** (`<0 stride>`), so it is read as
   `uint32_t const *` and combined `cells[0] << 32 | cells[1]` — **not** cast to `uint64_t const *`
   like `reg` above it, which really is native u64s (a u64 read would yield 0x400000000); and the
   stride is sanity-guarded (power of two, >= 0x10000, and frames of all cores fitting in `reg[3]`)
   with a panic naming the value otherwise. Redwood is unchanged and now **explicit**, not implicit:
   its `/arm-io/gic` carries `redistributor-stride = <0 0x20000>`, restating exactly the number that
   was hardcoded before, so the value it walks at is the same one it always did. `GICR_TYPER_LAST`
   still breaks the walk, as the safety net when the frame count is unknown.
7. **GCC register offsets** (redwood_goodix.c: 0x52008, 0x18004, 0x185fc, 0x18600…) are sc7280's;
   SM8750's `qcom,sm8750-gcc` is a different block. Only the base is in the table; touch is out of
   scope anyway.
7. **TLMM is in the table but unused** — no driver of the three touched here reads GPIO; the six that
   do (goodix, haptic, camera, mic, speaker, sound) were left on redwood's constants.

## Explicitly out of scope for milestone 1 (recorded as gaps, not attempted)

- **Touch**: the phone's panel is **Synaptics S3910** on `spi@a90000` (`qcom,geni-spi`, QUP2, IRQ gpio
  0xA2, reset 0xA1). `redwood_goodix.c` is a Goodix GT9916 / FocalTech FT3680 driver at SE 0x00A94000
  — a different chip, different protocol, different SE. **Gap, not a port.**
- **GPU**: Adreno 830 (SM8750) vs `redwood_adreno.c`'s Adreno 642L / a660 firmware names. Gap.
- **Wi-Fi/BT**: WCN7850 → ath12k, not ath11k. `WIFI_ATH11K=0`.
- **Audio**: ADSP at `remoteproc@6800000`. Gap.
- **Camera**: out.

## Files touched

New (final path under `xnu/files/`, and the same paths in the tree):

- `bsd/sys/redwood_soc.h` — the struct, the inline helpers, the mechanism documented at the top.
- `bsd/dev/redwood_soc.c` — the two rows, `redwood_soc()`, the `/arm-io` lookup.

Changed:

- `bsd/dev/redwood_cpufreq.c`, `bsd/dev/redwood_buttons.c`, `bsd/dev/redwood_ufshc.c`.
- `osfmk/arm64/gic_v3_irq.c` — the redistributor stride, read from the device tree (see follow-up 6
  above). This is an existing new file in `files/`, not a patched Apple file, so the patch's
  `diff --git` count is unchanged.
- `xnu/redwood.patch` — `bsd/conf/files` gains `bsd/dev/redwood_soc.c standard`, plus build-verify's
  `bsd/kern/makesyscalls.sh` fix (see below).
- `bsd/conf/files` in the tree (the patch is generated from it by `xnu/export.sh`).

Not touched, per the working agreements: `common/devices`, `xnuloader`, `uefi`, `xnu-deps/tools`.

## Patch hygiene

`xnu/export.sh` is authoritative: it regenerates `redwood.patch` (Apple's files) and `files/` (new
files) from the tree. The patch was regenerated from a tree that is a superset of both, and verified
by re-applying it to a clean `c54f35ca` clone plus `files/` and diffing against the live tree:
**no differences**. It contains 74 `diff --git` sections, including build-verify's
`bsd/kern/makesyscalls.sh` fix (the escaped `\(sy_call_t *\)` → `(sy_call_t *)`, without which
Debian awk generates an `init_sysent.c` that cannot compile).

## What was verified, exactly

- All four touched/added C files: clean `-fsyntax-only` pass with the tree's own compile line
  (`xnu-clang`, `-DBSD_BUILD -DBSD_KERNEL_PRIVATE`, the real include paths). The check was itself
  validated by injecting a deliberate error (a bad field designator in the table) and confirming it
  fails — so the pass is meaningful, not a vacuous one.
- `redwood_soc.c` is in `bsd/conf/files`; the header is found via `<sys/redwood_soc.h>` from
  `bsd/sys/`, the same way `redwood_input.h` is.
- `xnu/redwood.patch` applies cleanly to `c54f35ca`, and patch+`files/` reproduces the tree exactly.

**Not verified:** a full kernel link, and anything at all on hardware.
