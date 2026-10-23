# SM8750 (Snapdragon 8 Elite) port — facts gathered by the Lead

Everything below was read from source in this session; each line says where it came from.
Do not re-research these; extend them where marked TODO/UNVERIFIED.

## Target

- **SoC**: Qualcomm SM8750 = "Snapdragon 8 Elite" (Qualcomm family name **Pakala**;
  `PakalaPkg` in Mu-Silicium. Note `KaanapaliPkg` is SM8850, a different SoC — do not mix them).
- **Device**: OnePlus 13, codename **dodge** — the only SM8750 device Mu-Silicium supports today
  (`Platforms/OnePlus/dodgePkg`, with `FdtBlob/sm8750-oneplus-dodge.dtb` = the phone's vendor DT).
  Mu-Silicium `Status.md` says for dodge: Display ✅, Internal Storage ✅, Side Buttons ✅,
  USB Device Mode ✅, Linux Boot ✅. That is the best available boot-chain starting point.
- Second SM8750 Mu-Silicium device: OnePlus 13s **pagani** (same PakalaPkg, 1216x2640 panel).
- Mu-Silicium checkout used for all checks: commit `42fe563791e51bf5500c2e470ed294ca0c94b97c`
  at `/tmp/Mu-Silicium`. `uefi/BASE` in the HackiOS repo pins `e51cd877e31c8fbb322032dc4cb6715e83d25ad3`;
  `git apply --check uefi/mu-silicium.patch` **passes** on 42fe563 (verified by the Lead).

## Boot chain numbers (from Mu-Silicium dodgePkg / Resources/Configs/dodge.toml)

- UEFI FD: `base = 0xA7100000`, `size = 0x300000`; boot_image `header_version = 4`.
- `gArmTokenSpaceGuid.PcdSystemMemoryBase = 0x80000000`.
- `PcdCPUCoresStackBase = 0xA760D000`; `PcdCPUCorePrimaryStackSize = 0x40000`.
- Panel: 1440 x 3168 x 32 bpp.

## Mu-Silicium dodge memory map (Platforms/OnePlus/dodgePkg/Library/MemoryMapLib/MemoryMapLib.c)

Reserved DDR regions (name, base, size): RSRV0 0x81960000/0xA0000, XBL_DT 0x81A00000/0x40000,
AOP 0x81C00000/0xA0000, UEFI_Log 0x81CE4000/0x10000, SMEM 0x81D00000/0x200000,
PDP_NS 0x81F00000/0x100000, PvmFw 0x824A0000/0x100000, PIL_Reserved 0x89E00000/0x19700000,
Display_Demura 0xA3500000/0x02C80000, FD_Reserved 0xA7000000/0x100000, UEFI_FD 0xA7100000/0x300000,
UEFI_FD_Reserved 0xA7400000/0x200000, Info_Blk 0xA7601000/0x1000, MMU_PageTables 0xA7602000/0x3000,
Log_Buffer 0xA7605000/0x8000, UEFI_Stack 0xA760D000/0x40000, SEC_Heap 0xA764D000/0x8C000,
Sched_Heap 0xA76D9000/0x400000, FV_Region 0xA7AD9000/0x400000, UEFI_RESV 0xA7ED9000/0x127000,
**Kernel 0xA8000000/0x10000000**, XBL_Ramdump 0xB8000000/0x1C0000, DBI_Dump 0xB81C0000/0xF00000,
**DXE_Heap 0xB90C0000/0x1D500000** (= the only big EfiConventionalMemory block, 469 MB),
**Display_Reserved 0xFC800000/0x02B00000** (the GOP framebuffer lives here).

Device MMIO windows declared by that map: IPC_ROUTER_TOP 0x00400000/0x100000,
SECURITY_CONTROL 0x00780000/0x7000, QUP 0x00800000/0x300000, PRNG 0x010C0000/0xC000,
CRYPTO 0x01DC0000/0x40000, CLK_TCSR 0x01F00000/0x100000, PERIPH_SS 0x08800000/0x100000,
USB 0x0A600000/0x200000, AOSS 0x0B000000/0x4000000, TLMM 0x0F000000/0x1000000,
SMMU 0x15000000/0x200000, APSS_HM 0x16000000/0x6000000, IMEM 0x14680000/0x2A000.

**Open problem for the port (teammate A):** the largest free block (469 MB at 0xB90C0000) is far
smaller than what a HackiOS run needs (the resident iOS system image alone is 2.5 GB, and
`xnuloader` places it at `win_base + RESIDENT_RD_OFFSET (0x08000000)` and demands
`win_size >= top - phys_base + 0x4000000`). So the port must either hand XNU a much larger
conventional region (e.g. above 4 GB — SM8750 has 12/16 GB, DDR base 0x80000000) or shrink the
resident image. Produce a concrete, justified memory-map change.

## SoC addresses (from the phone's own DT, /tmp/Mu-Silicium/Platforms/OnePlus/dodgePkg/FdtBlob/sm8750-oneplus-dodge.dtb decoded with dtc)

- **GIC**: `arm,gic-v3` at `0x16000000` (size 0x10000), redistributor `0x16080000`
  (size 0x200000), `redistributor-stride = 0x40000`, ITS at 0x16040000. Mainline
  `arch/arm64/boot/dts/qcom/sm8750.dtsi` agrees exactly.
- **CPUs**: 8, `reg`/`MPIDR` = 0x0, 0x100, 0x200, 0x300, 0x400, 0x500, 0x10000, 0x10100
  => Qualcomm numbering in affinity level 1 => `core_shift = 8`; 8 cores. All cores are
  **Qualcomm Oryon** (2 prime + 6 performance); there is no A5xx little cluster.
  The vendor DT has **no** `capacity-dmips-mhz`, so `common/new-device.sh` computes
  `small_cores = 0x0`; the right value is a judgement call (likely 0x3f: cores 0-5 slower).
- **Timer**: ARM generic timer, CNTFRQ from firmware (24 MHz XO). The vendor
  `timer@17810000` (`arm,armv7-timer-mem`) is not used by XNU.
- **TLMM (GPIO)**: `pinctrl@f100000` (`qcom,kaanapali-tlmm`, 218 gpios), 0x1000 per gpio.
- **GCC**: `clock-controller@100000`, `qcom,sm8750-gcc`, size 0x1f4200.
- **IPC / mailbox**: `qcom,sm8750-ipcc` at 0x00406000; IMEM 0x14680000; `tcsr-mutex` 0x1F40000.
- **SPMI (PMIC arbiter)**: `spmi@c400000`. PMIC is pm8550 family; power key is
  `pmic@0/pon@1300/pwrkey` (`qcom,pmk8350-pwrkey`) => XNU's button driver needs SPMI, not GPIO.
- **UFS**: `ufs@1d84000` (`qcom,sm8750-ufshc`) + `phy@1d80000`. **Same HC address redwood's
  loader already has (`HC_PA 0x1d84000`)** — promising.
- **Display**: `display-subsystem@ae00000` (`qcom,sm8750-mdss`); the GOP framebuffer is in
  `Display_Reserved 0xFC800000`. => expected `fb_base = 0xFC800000` (confirm from the loader's
  own "display W x H at ..." line on hardware).
- **Touch**: `synaptics_tcm_hbp@0` on `spi@a90000` (`qcom,geni-spi`, SE in QUP2),
  chip-name **S3910**, IRQ gpio 0xA2, reset gpio 0xA1, avdd via PMIC gpio 3.
  => HackiOS's `redwood_goodix.c` (Goodix GT9916 / FocalTech FT3680 at SE 0x00A94000) does **not**
  apply. Touch is out of scope for milestone 1.
- **GPU**: Adreno 830 (SM8750). `redwood_adreno.c` targets Adreno 642L (a660 firmware names) =>
  out of scope for milestone 1.
- **Wi-Fi / BT**: SM8750 uses **WCN7850 (ath12k)**, not WCN6750/ath11k => `WIFI_ATH11K=0`.
- **Audio**: ADSP at `remoteproc@6800000` — out of scope.
- **cpufreq / EPSS**: SM8750 has no `cpufreq` node in mainline yet (patches still on LKML) and
  none in the vendor DT. Sibling SoCs of the same generation (eliza, milos, sar2130p) use
  `0x17D91000`, `0x17D92000`, `0x17D93000` (3 domains, 0x1000 apart) with
  `qcom,cpufreq-epss`. **UNVERIFIED for SM8750** => keep `cpufreq` off in the milestone-1
  boot args and record it as a follow-up that needs one on-hardware read.

## What the kernel side currently is (HackiOS)

- Driver sources live in `xnu/files/bsd/dev/redwood_*.c` (33 files) and are wired into Apple's
  build by `xnu/redwood.patch` (`bsd/conf/files`, `bsd/kern/bsd_init.c`, ...). New files are
  plain copies from `xnu/files/`; `xnu/export.sh` regenerates `redwood.patch` from a built tree.
- `redwood_cpufreq.c`: `EPSS_PHYS 0x18591000`, 3 domains, table at +0x100, perf state +0x320.
- `redwood_goodix.c`: SE_PHYS 0xA94000, GCC 0x100000, TLMM (from `redwood_input.h`),
  RSC/CMD_DB for RPMh, GPIO96/68 chip ID.
- `redwood_ufshc.c` / loader `HC_PA 0x1d84000`.
- Device identity in the DT the loader synthesises is deliberately an iPhone X
  (`D22AP`, iBoot-8422...): iOS user space looks the device up by these. The *hardware*
  description is below in the same tree (`arm-io` `device_type = plat->name`).

## Loader (`xnuloader/loader.c`)

- `struct platform` fields: name, io_base/io_size (one window over SoC peripherals, **must be
  non-zero**), gic_dist/gic_redist, uart (0 on phones), psci_hvc (0 on phones), log_other_cpu,
  cores, core_shift, timeout_scale, small_cores, fb_base.
- `platform_redwood`: io_base 0x00400000 size 0x3FC00000, gic 0x17A00000/0x17A60000,
  cores 8, core_shift 8, small_cores 0x0F, fb_base 0xE1000000.
- Device is picked by matching GOP `fb_base` against `platforms[]`.
- `PAYLOAD_BASE 0xF0000000` (`PAYLOAD_MAX_SIZE 0x04000000`), `RESIDENT_RD_OFFSET 0x08000000`,
  `RESIDENT_RD_RESERVE 0x30000000`, `MAX_MEM_SIZE 0x180000000`, `BASE_ALIGN 0x02000000`.
- On dodge, 0xF0000000..0xF4000000 is free in the UEFI map (between DXE_Heap and
  Display_Reserved) — so **keep PAYLOAD_BASE at 0xF0000000** unless you prove otherwise.
- Note the io window 0x00400000/0x3FC00000 (= 0x00400000..0x40000000) already covers GCC,
  TLMM, QUP/SE, UFS, IMEM, USB and the GIC on SM8750 — same as on redwood.

## Hard constraints of this environment

- No phone, no OnePlus 13 hardware: **nothing can be flashed or booted on device here.**
  Verification is limited to: builds, static/consistency checks, patch application, and
  documented evidence. Say so plainly in every report.
- Toolchain present: clang/lld/lld-link/ld.lld (Debian 14), gcc, python3 3.11, dtc, 7z, 12 CPUs,
  ~16 GB free disk. **No theos / no iPhoneOS16.5.sdk** (kernels can only be built after
  installing theos; that is teammate C's job).
- `xnuloader/build.sh` builds cleanly at baseline (68 KB `loader.efi`, verified).
- The iOS system image (`ios165/fetch.sh`) needs a 7.4 GB download + ~5.3 GB on disk from
  Apple's CDN; treat it as out of scope unless disk allows.
