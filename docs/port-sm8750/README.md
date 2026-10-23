# HackiOS on the Snapdragon 8 Elite (SM8750): what was ported, and what is not proven

Target: **OnePlus 13 (codename `dodge`)**, Qualcomm **SM8750** "Snapdragon 8 Elite" (Qualcomm
family *Pakala*; Mu-Silicium's `PakalaPkg` — **not** `KaanapaliPkg`, which is SM8850).

**Read this first.** There is no SM8750 phone in this environment and nothing can be flashed or
booted from here. So nothing below claims a boot, a driver probe, or a measurement on silicon.
Every number is either **sourced** (read from a named file at the point of use, cited with
`file:line`) or **inferred** (argued from those sources, labelled as such). What could be checked
mechanically — builds, patch round-trips, symbol tables, consistency between the profile, the
loader and the device tree — has been, and the command that re-runs each check is given.

Where this sits in the HackiOS project's own ladder (`docs/PORTING.md`): the work here is steps
1–4 — UEFI port, loader platform, kernel SoC adaptation, firmware notes. Step 5 (run it) is the
first thing that needs the phone.

## The documents

| file | what it covers |
|---|---|
| `FACTS.md` | every address and topology fact, with its source, collected before any code was written |
| `loader.md` | the device profile, `platform_dodge`, the core-numbering fix, the io window, the UEFI port, and the memory-map blocker |
| `kernel.md` | the SoC parameter table, the three wired call sites, and a constant-by-constant confidence table |
| `build.md` | the toolchain as stood up here, six environment gaps and their fixes, and the four-gate evidence |
| `core-number-test.sh` | host test that extracts the numbering helpers out of `loader.c` and checks them |

## What actually changed in the repository

**Boot chain (loader + profile + UEFI)**
- `common/devices/dodge.conf` — a real profile (was `new-device.sh` output): `UEFI_TARGET=dodge`,
  `FD_BASE=0xA7100000`/`FD_SIZE=0x300000`, `PAYLOAD_BASE=0xF0000000`, `FB_BASE=0xFC800000`,
  `WIFI_ATH11K=0`, `BOOTARGS="cpus=8"`.
- `xnuloader/loader.c` — `platform_dodge` + registration in `platforms[]`; `struct platform` grew
  `core_stride`, `gic_redist_size` and `gic_redist_stride`; `core_number()`/`core_mpidr()` used at
  every MPIDR-to-number site.
- `uefi/files/Platforms/OnePlus/dodgePkg` (12 files), `Resources/Configs/dodge.toml`,
  `Resources/DTBs/dodge.dtb` — Mu-Silicium's own SM8750 package, reused verbatim; our two
  boot-chain changes from `uefi/mu-silicium.patch` apply cleanly.
- `mkxnuimg.py` — device-aware output name, DTB and Android boot header version (dodge needs
  `header_version = 4`, redwood keeps 1); an FD-size mismatch is now explained, not asserted.
- `common/build.sh` — the boot step no longer announces an image it failed to write.

**Kernel side (XNU)**
- New `xnu/files/bsd/sys/redwood_soc.h` + `xnu/files/bsd/dev/redwood_soc.c`: one table, one
  discriminator (`/arm-io` `device_type`, which the loader writes from its own platform row),
  one fallback (redwood). Wired into `redwood_cpufreq.c`, `redwood_buttons.c`, `redwood_ufshc.c`
  and `gic_v3_irq.c`.
- `xnu/redwood.patch` regenerated (74 sections) and **verified by round-trip**: a clean
  `c54f35ca` tree + the patch + `xnu/files/` diffs to nothing against the live tree.

## The three findings that mattered

**1. `struct platform` could not express SM8750's core numbering.** SM8750 numbers its eight Oryon
cores in two affinity fields: `0x0…0x500` (six *performance*) and `0x10000`/`0x10100` (two
*prime*), each cluster restarting at 0. The loader derived every core number from one field, so
the eight MPIDRs collapsed onto six numbers — the two prime cores were never offered to the kernel,
two cores that do not exist were, and `small_cores`/`bootcpu=` became ambiguous. Fixed with
`core_stride` (0 on redwood, 6 on dodge), redwood unchanged.

**2. The GIC redistributor stride was hardcoded.** The kernel walked redistributor frames at
`0x20000`; SM8750's stride is `0x40000` across an `0x200000` region, so the walk would step into
the middle of frames, never match `GICR_TYPER`'s affinity, and panic `gic: no redistributor for
MPIDR` before the kernel got anywhere. The stride is now read from the device tree (with
`0x20000` as the fallback, so an older loader still boots), and `_gicr_stride` is present in the
linked kernel. Note the trap that nearly shipped: the property is two 32-bit cells in Apple's
native-endian DT, unlike the `reg` above it which really is native 64-bit words.

**3. The memory map is the milestone-1 gate.** The dodge UEFI map declares exactly one large free
region: 469 MiB at `0xB90C0000` (448 MiB after the loader's 32 MiB alignment). A run that keeps
the iOS root image resident wants `0x08000000 + 2.5 GiB + 0x30000000 + slack = 2.69 GiB`, and the
loader refuses an upload below `0x38000000` (896 MiB) before that. So today dodge would get the
loader's screen and log, and then `not enough contiguous RAM`. `loader.md` gives three options
with the arithmetic: extend `DXE_Heap` to `0xFC800000` (one line, 1056 MiB window — enough for the
kernel and a 160 MiB resident image, no new assumption); describe the RAM above 4 GiB (the real
fix for 12/16 GiB SKUs, but it needs the DRAM size and PEI's mapping confirmed on hardware first);
or shrink the resident image. Recommended: ship the one-liner, read the firmware's real memory map
out of the loader's log on the first session, then decide the second with numbers.

## What is verified, and how

Commands re-run by the Lead, independently of the teammates that produced the work:

| check | command | result |
|---|---|---|
| loader builds | `xnuloader/build.sh` | `loader.efi` 69120 B (baseline 68096; the growth is `platform_dodge` + helpers) |
| port consistency, all devices | `tools/check-port.py --all` | `OK: dodge, qemu-virt, redwood` (24 checks for each phone, 4 for qemu-virt, exit 0) |
| core numbering arithmetic | `docs/port-sm8750/core-number-test.sh` | exit 0; redwood/qemu unchanged, dodge 0..5 to `0x0..0x500`, 6,7 to `0x10000,0x10100` |
| kernel builds | `./xnu-build.sh -j12 -k` | **15,192,104 B**, 2026-10-24 06:31, 0 compiler errors (baseline 15,191,872 B; +232 B) |
| the SoC table is really in the link | `llvm-nm-14 -n ...unstripped` | `_redwood_soc`, `_redwood_soc_redwood`, `_redwood_soc_sm8750`, `_gicr_stride` all present |
| the SM8750 row cannot touch the unverified EPSS | `otool -s __DATA __const redwood_soc.o` | dodge row = `(0x17D91000, 0x1000, 0 domains)`, redwood = `(0x18591000, 0x1000, 3)`; guard at `redwood_cpufreq.c:345` refuses and logs |
| patch reproduces the tree | clean `c54f35ca` + `git apply` + `cp -a xnu/files/.` then `diff -rq` | identical, 0 differences (74 `diff --git` sections) |
| the checker actually bites | 17 injected drifts (redistributor stride both ways, redistributor region too small, cores, core_shift, core_stride, fb_base, payload, io window, TODO marker, unjustified boot arg, kernel-side name fallback) | each exits 1; clearing returns exit 0 |
| the redistributor step is no longer an immediate | `otool -tv gic_v3_irq.o` | **zero** `0x20000` in any instruction; the walk loads `_gicr_stride` (`0x6d8 ldr x10,[x10]`, reloc `PAGOF12 _gicr_stride`), the store from the DT parse sits behind the validity guard, and the default word read out of the linked image at offset `0xa95270` is `0x20000` |

`make` exits 2 on a good build and always will: after the link, `check_all_exports` and three
symbolsets fail on DriverKit RPC names. `xnu/README.md` documents it; judge by the artifact.

## What is inferred, and must be confirmed on hardware

1. **`fb_base = 0xFC800000`** — from `Display_Reserved` in the UEFI memory map, not from a GOP read.
   If it is wrong the loader does not even recognise the phone (it falls back to `qemu-virt`), so it
   is the first line to check: the loader prints `display 1440 x 3168 at <fb>`.
2. **`small_cores = 0x3F`** — a judgement (numbers 0–5 = the six performance cores; the vendor DT has
   no `capacity-dmips-mhz` to say so).
3. **The SM8750 EPSS address** — `0x17D91000` is the sibling-generation pattern (eliza/milos/
   sar2130p); SM8750 has no cpufreq node in mainline or in its vendor DT. Therefore
   `epss_domains = 0` for dodge and `cpufreq=1` is refused with a log line. Nothing writes it.
4. **Everything about the firmware's own memory map** — the table in `loader.md` is the source code,
   not a `GetMemoryMap` dump.
5. **Core MPIDRs, the prime cores' off-state, and PSCI on dodge** — the loader now prints its
   `number -> mpidr` table so the first session settles all three from the log.

## What is not done, and why

- **No boot, no flash, no probe.** No SM8750 hardware exists here.
- **The UEFI port is not built** — Mu-Silicium needs ~3 GB of submodules (including the
  `Binaries/dodge` vendor firmware extracted from the phone's own `xbl.img`) that are not present.
  `loader.md` gives the exact commands and the Mono/nasm workaround.
- **No iOS system image** — `ios165/fetch.sh` is a 7.4 GB download and ~5.3 GB on disk.
- **ath11k is not built** (`WIFI_ATH11K=0`); SM8750 uses WCN7850/ath12k anyway, so the WCN6750
  driver would not apply.
- **Out of scope for this milestone, recorded as gaps:** the touch panel is a Synaptics S3910 on
  `spi@a90000` (not the Goodix GT9916 that `redwood_goodix.c` drives — a different chip with a
  different protocol), the GPU is an Adreno 830 (the driver targets the 642L), audio is ADSP, the
  camera and the volume-up key (which has no input at all in the vendor DT — a hardware question,
  not a constant).

## The honest milestone ladder

1. **Loader on screen and a log over USB** — needs the UEFI built (`Binaries/dodge`), the memory-map
   one-liner, and `fb_base` confirmed from the loader's own line. This is where the next session
   starts.
2. **Kernel verbose boot text** — needs the framebuffer, the GIC stride (fixed), PSCI SMP, and the
   memory window.
3. **SpringBoard** — needs the iOS userland image, which is the `hackios-xnu-userland` side plus a
   resident-image decision from the memory-map section above.

## Reproducing the checks

```sh
cd "/root/xnu kernel/hackios"          # the build itself wants a space-free path: /mnt/hk
xnuloader/build.sh
tools/check-port.py --all
docs/port-sm8750/core-number-test.sh
./xnu-build.sh -j12 -k ; stat -c '%s %y' \
  xnu-src/xnu-8796.121.2/BUILD/obj/DEVELOPMENT_ARM64_BCM2837/mach.development.bcm2837
```

## Working notes, for whoever picks this up

- `xnu/redwood.patch` is regenerated by `xnu/export.sh` **from the tree as it stands**. Exporting
  from a tree that lacks a change silently rolls it back — this actually happened during this port
  (a Linux build fix in `bsd/kern/makesyscalls.sh` was dropped) and is now caught by the
  round-trip diff, which is the gate to run before trusting the patch.
- Apple's `makesyscalls.sh` relies on BSD awk dropping the backslash of an unknown escape; every
  Debian awk keeps it, so `init_sysent.c` fails to compile. Fixed in the patch with plain parens.
- Five local modifications to tracked files were needed to make this tree build on Debian 12 with
  clang 14; all are in `build.md` section 7 with the reason for each.
