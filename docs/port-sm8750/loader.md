# Loader, device profile and UEFI port for SM8750 (dodge)

OnePlus 13 (**dodge**), Qualcomm **SM8750** "Snapdragon 8 Elite" (Qualcomm family name *Pakala*;
Mu-Silicium's `PakalaPkg`. Not `KaanapaliPkg`, which is SM8850).

**What this document is, and is not.** There is no dodge hardware in this environment. Nothing here
was flashed, booted or read back from silicon. Everything below is either *sourced* (read out of a
file named at the point where it is used) or *inferred* (argued from those sources) -- each value
says which. What can be verified mechanically has been, and the command that re-runs each check is
given. The first session that will tell us more is on hardware.

Sources of the addresses, all already collected in `docs/port-sm8750/FACTS.md`:
the phone's own device tree (`/tmp/Mu-Silicium/Platforms/OnePlus/dodgePkg/FdtBlob/sm8750-oneplus-dodge.dtb`,
82245 bytes, decoded with `dtc`), Mu-Silicium at commit `42fe563`, and the mainline
`arch/arm64/boot/dts/qcom/sm8750.dtsi`.

## What changed

| File | What |
|---|---|
| `common/devices/dodge.conf` | the profile `common/build.sh`/`common/run.sh` read (was a `new-device.sh` stub) |
| `xnuloader/loader.c` | `platform_dodge` + `platforms[]`; `core_stride` + `core_number()`/`core_mpidr()`; `gic_redist_size` + `gic_redist_stride` (published as `/arm-io/gic`'s `redistributor-stride`); the "cores: number -> mpidr" line |
| `mkxnuimg.py` | device-aware output name, DTB and Android boot header version; `DEVICE` fallback; clear FD-size error |
| `uefi/files/Platforms/OnePlus/dodgePkg/` (12 files) | the UEFI port: upstream's package, reused verbatim (see "UEFI port") |
| `common/build.sh` | the boot step now honours `mkxnuimg.py`'s exit status (it used to announce an image it had not written) |
| `uefi/README.md` | `BASE` staleness note; `llvm-objcopy` note |
| `uefi/files/Resources/Configs/dodge.toml` | the boot shim's addresses / boot image, upstream's file verbatim |
| `uefi/files/Resources/DTBs/dodge.dtb` | the vendor DT (82245 bytes, md5 `961ef118acd28d9e9bdea9c7853128e3`), the copy `mkxnuimg.py` appends |
| `docs/port-sm8750/core-number-test.sh` | host test of the core numbering, extracted from `loader.c` itself |
| `common/devices/dodge.platform.c` | **removed**: `platform_dodge` now lives in `loader.c`, and two copies of the same platform description drift |

Redwood is untouched: `platform_redwood` and `platform_qemu_virt` only gained explicit
`.core_stride = 0`, and `.gic_redist_size` defaults to the 1 MB they always wrote.

## The loader's platform for dodge

`static const struct platform platform_dodge` in `xnuloader/loader.c` (`loader.c:562`), added to
`platforms[]` (`loader.c:606`) so the loader can actually select it by the framebuffer base the UEFI
reports.

| Field | Value | Where it comes from |
|---|---|---|
| `name` | `"dodge"` | the codename (Mu-Silicium `Resources/Configs/dodge.toml`); it reaches XNU as `arm-io`'s `device_type` |
| `io_base`, `io_size` | `0x00400000`, `0x3FC00000` | the same peripheral window redwood uses; see "The io window" |
| `gic_dist` | `0x16000000` | vendor DT `interrupt-controller@16000000` (`arm,gic-v3`); mainline `sm8750.dtsi` agrees; also `PakalaPkg.dsc.inc` `PcdGicDistributorBase` |
| `gic_redist` | `0x16080000` | same node, `reg = <0 0x16000000 0 0x10000  0 0x16080000 0 0x200000>`; `PakalaPkg.dsc.inc` `PcdGicRedistributorsBase` |
| `gic_redist_size` | `0x200000` | the redistributor region's size in that `reg`, with `redistributor-stride = 0x40000`. New field: the loader used to hardcode 1 MB, which covers only 4 frames at this stride |
| `uart` | `0` | phones have no PL011 |
| `psci_hvc` | `0` | vendor DT `psci { method = "smc" }` (only QEMU's virt calls PSCI with HVC) |
| `log_other_cpu` | `1` | as redwood: the loader stays on one core and keeps the log partition while the kernel runs on another |
| `cores` | `8` | vendor DT has 8 `cpu@` nodes; `PakalaPkg.dsc.inc` `PcdCoreCount = 8` (7 for SM8750-3-AB), `PcdClusterCount = 2` |
| `core_shift` | `8` | `reg` values 0x0,0x100,...,0x500,0x10000,0x10100 -> Qualcomm numbers cores in MPIDR's second affinity field |
| `core_stride` | `6` | six cores in the first cluster (see "Core numbering"), two in the second |
| `small_cores` | `0x3F` | **judgement, not a DT fact**: numbers 0-5 are the six Oryon *performance* cores, 6-7 the two *prime* ones. The vendor DT has **no** `capacity-dmips-mhz`, so nothing in it says which is faster; the split follows the DT's cluster layout and the product description (prime up to 4.32 GHz, performance ~3.5 GHz). Needs one look at `sysctl hw` / a benchmark on hardware |
| `fb_base` | `0xFC800000` | **INFERRED**: `Display_Reserved 0xFC800000/0x02B00000` in `Platforms/OnePlus/dodgePkg/Library/MemoryMapLib/MemoryMapLib.c` is where `SimpleFbDxe` puts the GOP framebuffer. Not observed: the firmware only prints it at boot |
| `timeout_scale` | `0` (unset) | as redwood; nothing suggests these cores need QEMU's extra patience |

`dodge.conf` carries the same numbers in the variables `common/build.sh` reads, and
`tools/check-port.py dodge` asserts that the two agree.

**The one number to change after the first session:** `fb_base`. If the loader's own
`display 1440 x 3168 at <fb>` line reports something other than `0xFC800000`, the device is not
recognised at all (no match in `platforms[]` means the loader falls back to `platform_qemu_virt` and
pretends to be QEMU), so it is the first thing to look at, and then the same value goes into
`platform_dodge.fb_base` **and** `dodge.conf`'s `FB_BASE`.

## Core numbering: why `struct platform` grew a field

This is the port's one structural finding, found by build-verify's checker and confirmed by reading
the code.

**The problem.** Every place in `loader.c` that turned an MPIDR into a core number, or a number back
into an MPIDR, used only the second affinity field:

```
boot_core = kernel_mpidr >> plat->core_shift;              (was loader.c:3182)
mpidr     = (uint64_t)core << plat->core_shift;            (was loader.c:3188, and the bootcpu= parse)
small_cores & (1u << ((mpidr >> plat->core_shift) & 31))   (was loader.c:3224)
```

SM8750's eight cores do not fit that: the vendor DT numbers them `cpu@0/100/200/300/400/500` (six
Qualcomm Oryon *performance*) and `cpu@10000/10100` (two Oryon *prime*) -- two affinity fields, each
cluster starting at 0. With `core_shift = 8` those eight MPIDRs collapse onto six numbers:

```
0x0->0  0x100->1  0x200->2  0x300->3  0x400->4  0x500->5  0x10000->0  0x10100->1
```

Consequences, all silent:

1. enumeration starts from the loader's own MPIDR and only ever builds `core << 8`, i.e. 0x0..0x700:
   the two real prime cores are **never offered to the kernel**, and the kernel's device tree instead
   lists two cores at 0x600 and 0x700 that do not exist. `PSCI CPU_ON` for them cannot work, so the
   two fastest cores are lost and two of the "8" are fiction;
2. `small_cores` cannot express the truth: bit 0 would mark both `cpu@0` (performance) and
   `cpu@10000` (prime). `0x3F` *looks* right only because the collapse is invisible in hex;
3. `bootcpu=` could not name a prime core at all.

The values that FACTS.md had pencilled in (cores 8 / core_shift 8 / small_cores 0x3F) are therefore not
a choice that can be made correct: the struct had no room for the answer.

**The fix.** `struct platform` gained

```c
uint32_t core_stride;   /* 0: the number is that field alone, one cluster (redwood).
                         * N: a cluster holds N cores and restarts numbering at 0 in the field
                         * above it (SM8750: 6 Oryon performance + 2 Oryon prime, N = 6). */
```

and one pair of helpers (`loader.c:626`, `loader.c:637`) is now the only place the conversion happens:

```
number = ((mpidr >> shift) & 0xff) + ((mpidr >> (shift + 8)) & 0xff) * stride     [stride != 0]
mpidr  = ((number / stride) << (shift + 8)) | ((number % stride) << shift)        [stride != 0]
mpidr  = number << shift                                                          [stride == 0]
```

which is the mapping the kernel side already has (`xnu/files/bsd/sys/redwood_soc.h`), so the device
tree's `reg` can stay the MPIDR and the kernel reads back the same number the loader wrote. Cluster 0 =
numbers 0-5 (performance), cluster 1 = 6,7 (prime); `small_cores = 0x3F` is then meaningful.

Used at all four sites: the `bootcpu=` parse (`loader.c:2957`, which now also accepts a two-digit
number for a SoC with more than ten cores), the boot core (`loader.c:3278`), the MPIDR built for
`PSCI AFFINITY_INFO`/`CPU_ON` during enumeration (`loader.c:3290`), and the `small-core` property
(`loader.c:3324`). The "nearest numbers first" ordering is unchanged; it now simply runs over these
numbers.

**Redwood cannot move.** `core_stride = 0` on `platform_redwood` and `platform_qemu_virt` reduces both
formulas to the old ones term for term (`number = mpidr >> shift`, `mpidr = number << shift`), and
`core_stride` was added as the last-but-three member of a struct that is only ever initialised by
designators, so no other field shifted. The one added print line is inert. Verified mechanically, not
by eye: `docs/port-sm8750/core-number-test.sh` extracts `struct platform` and the two helpers *out of
`loader.c` itself* and asserts, on the host,

* redwood/qemu-virt: `core_mpidr(n) == n << shift` and `core_number(m) == n` for n = 0..7 (the old
  behaviour, bit for bit),
* dodge: 0..7 -> `0x0,0x100,0x200,0x300,0x400,0x500,0x10000,0x10100` and back, eight distinct numbers,
  and `small_cores = 0x3F` marking exactly the six performance cores.

```
$ docs/port-sm8750/core-number-test.sh
core numbering: redwood/qemu unchanged; dodge 0..5 -> 0x0..0x500, 6,7 -> 0x10000,0x10100
```

**Confirming it needs the phone.** Whether the *firmware* really reports those MPIDRs, and whether the
prime cores are off (so the kernel may take them) is not something a host test can say. The loader now
prints it at startup, so the next hardware session reads the answer out of the log instead of guessing:

```
cores: number -> mpidr (core_shift 8, core_stride 6, small_cores 3f): 0 -> 0* 1 -> 100* ... 6 -> 10000 7 -> 10100
```

(`*` marks a small core.) If `PSCI AFFINITY_INFO` says a core is not off, the loader already says so and
leaves it out -- `core 10000 is not off (the firmware says 0): not the kernel's to take`.

## The GIC redistributor region

The loader writes `/arm-io/gic`'s `reg = <dist-io_base 0x10000 redist-io_base redist_size>` and the
kernel (`xnu/files/osfmk/arm64/gic_v3_irq.c`, `gic_find_redistributor()`) walks frames of
`GICR_FRAME_SIZE` = `0x20000` inside `redist_size` and looks up each frame's `GICR_TYPER` by
affinity. The value was hardcoded `0x100000` -- four frames. SM8750's cores are `0x40000` apart
(vendor DT `redistributor-stride`), so its eight frames span `0x200000`: with `0x100000` the kernel
could only ever find cores 0-3 and would `panic("gic: no redistributor for MPIDR ...")` on the rest.

Hence the new `gic_redist_size` field, `0x200000` for dodge, and `0` (meaning 1 MB) for redwood,
whose DT redistributor region is `0x17A60000/0x100000` with `redistributor-stride = 0x20000` -- eight
frames in 1 MB, which is exactly why the hardcoded value worked there. **Inferred**, not observed: it
follows from the two device trees and the kernel's walk; nobody has run it on SM8750.

**The stride is now published to the kernel.** The kernel's walk in `gic_find_redistributor()`
(`xnu/files/osfmk/arm64/gic_v3_irq.c`) stepped by a hardcoded `GICR_FRAME_SIZE` of `0x20000`, which is
fine on redwood (`redistributor-stride = 0x20000`) and wrong on SM8750 (`0x40000`): it would step
through the middle of every frame, never match `GICR_TYPER`'s affinity and `panic("gic: no
redistributor for MPIDR ...")`. Rather than have the kernel guess, the loader now writes the value into
`/arm-io/gic` beside `reg`:

```
/arm-io/gic
    compatible            "arm,gic-v3"
    reg                   <dist-io_base 0x10000  redist-io_base  redist_size>   (4 native u64 cells)
    redistributor-stride  <0x0 0x40000>                                        (2 native u32 cells)
```

`struct platform` gained `uint32_t gic_redist_stride`: `0x20000` on `platform_redwood` and
`platform_qemu_virt` (the value the kernel has always assumed, so redwood's tree gains a property that
restates the default and nothing else changes), `0x40000` on `platform_dodge` (vendor DT
`interrupt-controller@16000000`, `redistributor-stride = <0x00 0x40000>`). Emission is at
`loader.c:3371`; the property is two cells, high word first, exactly like the FDT's `<0x0 0x40000>`,
but **native-endian** (this is Apple's device-tree format, not FDT -- `reg` above is written as native
u64s too), so a reader combines them as `cells[0] << 32 | cells[1]` from a `uint32_t const *`.
**Who reads it: kernel-soc**, in `gic_find_redistributor()` -- replacing the `GICR_FRAME_SIZE` step with
this property (falling back to `0x20000` if it is absent, so an older loader tree still boots). Nothing
in this repository reads it yet; a loader-only tree writes the property and the current kernel ignores
it, which is why the two changes are independent.

## The io window

`io_base 0x00400000`, `io_size 0x3FC00000` -- the window `0x00400000..0x40000000`, identical to
redwood's. `io_base` must be non-zero (XNU reads a zero SoC base as "no SoC" and skips clock setup),
and the window becomes the `/arm-io` `ranges` property; the GIC's `reg` is emitted relative to it.

Everything the loader and the kernel address through `/arm-io` on SM8750 is inside it:

| Block | Address | Source |
|---|---|---|
| GIC distributor / redistributor | 0x16000000 / 0x16080000 | vendor DT `interrupt-controller@16000000` |
| GCC (clocks) | 0x00100000 (+0x1f4200) | vendor DT `clock-controller@100000` (`qcom,sm8750-gcc`) |
| TLMM (GPIO) | 0x0F100000 | vendor DT `pinctrl@f100000`; `MemoryMapLib` "TLMM 0x0F000000/0x1000000" contains it |
| QUP / SE (I2C, SPI, ...) | 0x00800000..0x00B00000 | `MemoryMapLib` "QUP 0x00800000/0x300000"; touch is SE 0xA90000, UART SE 0x98C000 |
| UFS HC + PHY | 0x01D84000 / 0x01D80000 | vendor DT `ufs@1d84000` (`qcom,sm8750-ufshc`), `phy@1d80000`; the loader's `HC_PA` (`loader.c:1722`) is already the same address as redwood's |
| IMEM / IMEM cookie | 0x14680000 | vendor DT reserved-memory, `MemoryMapLib` "IMEM 0x14680000" |
| IPC router / mailbox (IPCC) | 0x00400000 / 0x00406000 | `MemoryMapLib` "IPC_ROUTER_TOP 0x00400000/0x100000"; vendor DT `qcom,sm8750-ipcc` |
| USB | 0x0A600000 | `MemoryMapLib` "USB 0x0A600000/0x200000" |
| SPMI (PMIC arbiter, power key) | 0x0C400000 | vendor DT `spmi@c400000` |
| tcsr mutex | 0x01F40000 | vendor DT `tcsr-mutex`; inside "CLK_TCSR 0x01F00000/0x100000" |
| security control, PRNG, crypto | 0x00780000, 0x010C0000, 0x01DC0000 | `MemoryMapLib` |

Outside it, by design -- these are reached by their own drivers through addresses the kernel learns
from somewhere other than `/arm-io`'s `ranges`, so the window does not need to grow:

* **AOSS** `0x0B000000/0x4000000` (`MemoryMapLib`) -- no milestone-1 driver uses it, and it abuts the
  window's top end;
* the **GOP framebuffer** at `0xFC800000` -- handed to the kernel as `boot_args.video.v_baseAddr`,
  not mapped through `/arm-io`;
* **SMEM** `0x81D00000`, **PIL/TZ** `0x89E00000..`, and the rest of the DDR reservations -- the
  subsystems (GPU, Wi-Fi, ADSP) that own them are out of scope for milestone 1;
* **PCIe** `0x1C000000`/`0x40000000` -- SM8750's PCIe is not used.

`tools/check-port.py dodge` asserts that io_base/io_size are non-zero and that the window covers the
DT's GIC and redistributor ranges; the table above is the manual half of that check.

## How FD_BASE / FD_SIZE / PAYLOAD_BASE reach the two places that need them

Two different consumers, two different mechanisms -- worth writing down because they are easy to
confuse.

**1. The boot shim (`BootShim.S`) and the UEFI image.** `mkxnuimg.py` builds the shim itself
(`mkxnuimg.py:76-86`):

```python
subprocess.check_call(['make', 'REQUIRES_KERNEL_HEADER=1', f'FD_BASE={FD_BASE:#x}', f'FD_SIZE={FD_SIZE:#x}',
                       f'CFLAGS=--target=aarch64-linux-gnu -DPAYLOAD_BASE={PAYLOAD_BASE:#x}'], cwd=shim_dir)
```

so `FD_BASE`/`FD_SIZE` arrive as make variables (`BootShim/Makefile` passes them as `-DFD_BASE`/
`-DFD_SIZE`), and `PAYLOAD_BASE` is smuggled through `CFLAGS` as a preprocessor define. Our
`uefi/mu-silicium.patch` adds the `#ifdef PAYLOAD_BASE` block to `BootShim.S` that copies an
"XNUP" container found just past the FD to that address. For the UEFI's own build the same two
addresses come from `Resources/Configs/<device>.toml` `[uefi_fd]` -> `build_uefi.py:476`
(`blocks = size // 4096`) -> `DeviceBuild.py:160-162` (`BLD_*_FD_BASE/SIZE/BLOCKS`) ->
`<device>.fdf` `BaseAddress = $(FD_BASE)`. dodge's `toml` already says `base = 0xA7100000`,
`size = 0x300000`, and its `fdf` already uses `$(FD_BASE)`, so **nothing in the UEFI build needed
changing for dodge**.

Verified statically on this machine: I built the shim from `BootShim.S` + `uefi/mu-silicium.patch`
for dodge's addresses (`-DFD_BASE=0xa7100000 -DFD_SIZE=0x300000 -DPAYLOAD_BASE=0xf0000000`); the
176-byte result contains the `movz w3,#0x4E58 / movk w3,#0x5055` "XNUP" comparison and the
`movz x5,#0xf000,lsl#16` destination, and its header carries `FD_BASE=0xa7100000` /
`FD_SIZE=0x300000`. Without the patch the same source builds to 112 bytes and has neither. That is
the shim for dodge; it has not run.

**2. The XNU loader's view of the payload.** `XnuLoader.h` in
`uefi/files/Silicon/Silicium/SiliciumPkg/Library/BootManagerLib/` hardcodes

```c
#define XNU_PAYLOAD_BASE      0xF0000000ULL
#define XNU_PAYLOAD_MAX_SIZE  0x04000000ULL
```

and `xnuloader/loader.c:18` defines the same two independently. Nothing connects them at build time,
so **`PAYLOAD_BASE` is a three-way agreement**: `dodge.conf`, `loader.c`, `XnuLoader.h` (plus
`mkxnuimg.py`'s `PAYLOAD_MAX`). Keeping `0xF0000000` is also what the free-RAM analysis below
wants, so nothing has to move:

* `0xF0000000..0xF4000000` is free on dodge: above the end of `DXE_Heap` (`0xB90C0000 + 0x1D500000 =
  0xD65C0000`), below `Display_Reserved` (`0xFC800000`);
* the vendor DT reserves nothing there (`trust-ui-vm@f3800000` and `oem-vm@f7c00000` -- both with
  `no-map` -- start *above* `0xF4000000`; the second one begins at `0xF7C00000`);
* the UEFI image ends at `0xA7400000`, far below.

Still, if `PAYLOAD_BASE` ever moves, three files move with it, and `tools/check-port.py` only knows
about two of them (`loader.c` and the profile) -- `XnuLoader.h` is the one it cannot see.

## The UEFI port

**Layout.** `uefi/files/Platforms/OnePlus/dodgePkg/` mirrors the redwood port
(`uefi/files/Platforms/Xiaomi/redwoodPkg/`), and `uefi/files/Resources/Configs/dodge.toml` +
`uefi/files/Resources/DTBs/dodge.dtb` sit beside redwood's.

**Reused verbatim, not invented.** upstream Mu-Silicium already supports dodge
(`Platforms/OnePlus/dodgePkg`, 12 files, including its `DeviceBuild.py`, `dodge.dsc`, `dodge.fdf`,
`Include/*.inc`, both libraries and `FdtBlob/sm8750-oneplus-dodge.dtb`). I copied that directory and
`Resources/Configs/dodge.toml` into `uefi/files/` unchanged and checked it:

```
$ diff -r uefi/files/Platforms/OnePlus/dodgePkg /tmp/Mu-Silicium/Platforms/OnePlus/dodgePkg   # no output
$ diff -u uefi/files/Resources/Configs/dodge.toml /tmp/Mu-Silicium/Resources/Configs/dodge.toml  # no output
```

So the sm8750 memory map (above) is upstream's, not mine. **No `DeviceBuild.py` was written**:
dodgePkg's own works as it stands (its `PackagesPath` already lists `Platforms/OnePlus` and
`Silicium-ACPI/Platforms/OnePlus`; its `Scopes` are `('dodge', ...)`).

**What is still missing, and what must change -- honestly:**

1. `Binaries/dodge` -- the UEFI drivers extracted from the phone's own `xbl.img` with UEFIReader
   (Silicium's five usual patches; see `uefi/files/Binaries/redwood/README.md` for the recipe).
   `dodgePkg/Include/APRIORI.inc` and `DXE.inc` already reference `Binaries/dodge/...`, and Mu-Silicium's
   `Binaries` submodule was empty in this checkout, so this **cannot be produced here**: vendor firmware
   never goes into the repository and we have no phone to pull it from. Until it exists the UEFI
   cannot be built for dodge.
2. `uefi/export.sh` only copies `Platforms/Xiaomi/redwoodPkg`. Adding dodge means extending its
   `cp` lines (`Platforms/OnePlus/dodgePkg`, `Binaries/dodge`) -- deliberately not done here, because
   `export.sh` is the reverse direction and build-verify/lead own the tree-wide consistency; it is a
   one-line change when there is something to export.
3. `uefi/mu-silicium.patch` applies unchanged: `git apply --check` passes on `42fe563` (lead's check)
   and the patch touches only `BootShim/BootShim.S` and `Silicium/SiliciumPkg/Library/BootManagerLib/`,
   neither of which is device-specific.
4. `uefi/BASE` still pins `e51cd877...`; the dodge port was made on `42fe563`. The patch applies to
   both, but the port's files here are from `42fe563`, so `BASE` should be updated when the tree is
   next refreshed -- a lead/export decision, not a loader one.

**Build command** (not run here: submodules are ~3 GB and `Binaries` is missing):

```sh
uefi/apply.sh                                   # clone Mu-Silicium at uefi/BASE + the port
python3 -m venv venv && venv/bin/pip install -r Mu-Silicium/pip-requirements.txt
cd Mu-Silicium && source ../venv/bin/activate
python3 build_uefi.py -d dodge -r RELEASE       # -> Build/dodgePkg/RELEASE_CLANGPDB/FV/SILICIUM_UEFI.fd
```

**Mono/nasm workaround** (from `uefi/README.md`; `mu_nasm` is installed through NuGet and wants Mono):

```sh
D=Mu_Basecore/BaseTools/Bin/mu_nasm_extdep
mkdir -p $D/Linux-x86-64
echo 'version: 20016.1.1' > $D/extdep_state.yaml
ln -s /usr/bin/nasm /usr/bin/ndisasm $D/Linux-x86-64/
```

Two toolchain notes from this machine, both relevant to that build: `nasm` is **not** installed here
(needed for the workaround above), and `llvm-objcopy` is only present as
`/usr/lib/llvm-14/bin/llvm-objcopy` (`BootShim/Makefile` calls it by bare name, so
`OBJCOPY=/usr/lib/llvm-14/bin/llvm-objcopy` is required to build even the shim -- that is how the
176-byte shim above was produced).

## The memory map: the port's real blocker

**The finding.** `Platforms/OnePlus/dodgePkg/Library/MemoryMapLib/MemoryMapLib.c` declares exactly one
large, free DDR region:

```
{"DXE_Heap", 0xB90C0000, 0x1D500000, AddMem, SYS_MEM, SYS_MEM_CAP, Conv, WRITE_BACK_XN}
```

469 MiB, from 0xB90C0000 to 0xD65C0000. Everything else from 0x80000000 up is reserved
(`FD_Reserved`/`UEFI_FD`/`UEFI_FD_Reserved`, `Sched_Heap`, `FV_Region`, `UEFI_RESV`, the 256 MiB
`Kernel` reservation at 0xA8000000, `XBL_Ramdump`, `DBI_Dump`, `Display_Reserved`) or is one of the
`BsData`/`RtData` blocks UEFI itself uses. The free DDR above 0xD65C0000 is `Display_Reserved`
0xFC800000/0x2B00000 and then nothing until 4 GiB. There is no `EfiConventionalMemory` above
0x100000000 at all: the memory map stops at `Display_Reserved`'s end (`0xFF300000`), so 10-14 GiB of
the phone's RAM (SM8750 devices ship 12 or 16 GiB) is simply not described.

**Why that is not enough.** `xnuloader/loader.c`'s `choose_window()` takes the largest
`EfiConventionalMemory` block, aligns it to `BASE_ALIGN` (32 MiB) and claims it, then requires

```
win_size >= top - phys_base + 0x4000000        (loader.c:2902)
```

where `top` is past the kernel, the ramdisk and the boot args. Measured from the kernel we ship
(`prebuilt/mach.development.bcm2837`): the segments span `0xfffffff007004000..0xfffffff0082e2390`,
i.e. `vm_hi - KERNEL_VIRT_BASE = 0x42E2390` (66.9 MiB), so

* a run with a ramdisk **inside** the payload area needs `~0xC2F6390` (195 MiB) -- that fits in 469 MiB;
* `./xl ramdisk` (and QEMU's `--rdres`) instead keep the root image **resident** at
  `win_base + RESIDENT_RD_OFFSET` (`0x08000000`) and demand
  `win_size > RESIDENT_RD_OFFSET + RESIDENT_RD_RESERVE` (`0x38000000`) before accepting an upload
  (`loader.c:3754`), i.e. **>= 896 MiB even before the kernel's own need is counted**, and
  `0x08000000 + 2.5 GiB + 0x10000 + 0x4000 + 0x4000000 = 0xAC014000` (**2.69 GiB**) for the 2.5 GiB
  iOS system image the platform actually runs from. Aligned down to 32 MiB inside the 469 MiB block,
  the usable window is `0x1C000000` (448 MiB) -- **off by a factor of ~6**.

Without a fix, dodge gets the loader's own screen and log, and the kernel stops at
`not enough contiguous RAM` (or, before that, `no memory window` when an image is uploaded). This is
milestone 1's gate.

**The proposal.** Three changes, in increasing order of risk. (b) is the one to ship first;
(a) is what the full workflow needs; (c) is the fallback that needs no firmware change at all.

*(b) Extend `DXE_Heap` to `Display_Reserved`.* One line in
`uefi/files/Platforms/OnePlus/dodgePkg/Library/MemoryMapLib/MemoryMapLib.c`, entirely inside RAM the map
already describes, so it assumes nothing new about the phone:

```c
-  {"DXE_Heap",          0xB90C0000, 0x1D500000, AddMem, SYS_MEM, SYS_MEM_CAP, Conv,   WRITE_BACK_XN},
+  // DXE_Heap is the only large free block for DXE and, after hand-off, for XNU: give it everything up
+  // to Display_Reserved (0xFC800000). Nothing lies in 0xD65C0000..0xFC800000 (the map above ends
+  // DXE_Heap there and Display_Reserved starts at 0xFC800000), so nothing is lost.
+  {"DXE_Heap",          0xB90C0000, 0x43740000, AddMem, SYS_MEM, SYS_MEM_CAP, Conv,   WRITE_BACK_XN},
```

That is a 1079 MiB block, 1056 MiB after `BASE_ALIGN` (32 MiB) alignment
(`0xBA000000..0xFC000000`). Enough for:

* the kernel plus a ramdisk carried in the payload: needs ~195 MiB -- **yes**;
* the loader's own upload gate (`win_size > RESIDENT_RD_OFFSET + RESIDENT_RD_RESERVE` = 896 MiB) --
  **yes**, which today's 448 MiB window fails, so `./xl ramdisk` currently answers
  `FAIL no memory window`;
* a resident root image: the ceiling becomes
  `win_size - 0x08000000 - 0x30000000` = **160 MiB** -- a first "does the kernel come up" session, not
  the 2.5 GiB iOS system image.

*(a) Describe the RAM above 4 GiB.* The real fix, and what a 12/16 GiB phone expects: the map simply
stops at `Display_Reserved`'s end (`0xFF300000`), so 10-14 GiB are not described at all. Append one
descriptor after `Display_Reserved` (the array must stay sorted: `ValidateMemoryMap()` sorts it and
`CpuDeadLoop()`s on an overlap above `PcdSystemMemoryBase`):

```c
+  // The map above stops at 4 GiB; the phone's DDR does not. 12 GiB SKU: RAM runs to 0x380000000
+  // (16 GiB SKU: 0x480000000). Start at 4 GiB so the block is 1 GiB-aligned and inside the 40-bit
+  // physical range the MMU setup covers.
+  {"High_DDR",          0x100000000, 0x280000000, AddMem, SYS_MEM, SYS_MEM_CAP, Conv,   WRITE_BACK_XN},
```

= 10 GiB of `EfiConventionalMemory` at `0x100000000..0x380000000`, from which `choose_window()` takes
a 32 MiB-aligned window and then caps it at `MAX_MEM_SIZE` (6 GiB) -- enough for the 2.69 GiB the
resident-image workflow needs, with room to spare, and it also finally gives the kernel the same
`window` shape it gets on redwood (a multi-GiB contiguous block).

Why this is a follow-up and not switched on blind: it needs two things checked on hardware, and both
are cheap. (i) The DRAM size the phone actually trains. The vendor DT is not usable for this: its
`memory` node's `reg` is a list of small reserved fragments plus `0x08 0x80000000 / 0x00 0x2f700000`
and `0x0a 0x00 / 0x02 0x00` (i.e. 0x1000000000, a Linux-side mapping) -- that `ddr-regions`-`region2`
entry is bogus, so the real top must be read off a booting phone, not out of the DT. (ii) That PEI
maps what we describe: `MemoryInitPei.c` passes every descriptor through `ArmConfigureMmu`, whose
tables are sized from what PEI knows; a range beyond that would fault the first time the loader
touches it. The loader's own `memory map (type 7 = free ...)` print is the cheapest way to get both
numbers.

*(c) If neither can be done before the first session: shrink the resident image.* No firmware change.
The loader needs only `resident_rd_size <= win_size - 0x08000000 - 0x30000000`, i.e. **160 MiB** with
(b)'s window (and 0 with today's 448 MiB one). A hand-built milestone-1 image (launchd, backboardd,
SpringBoard) is a userland question, not a loader one; what matters here is that the loader's
constants are `RESIDENT_RD_OFFSET 0x08000000` and `RESIDENT_RD_RESERVE 0x30000000` (`loader.c:33-34`)
and that they define the trade-off.

Recommended order: ship (b) -- one line, no new assumption -- start a session, read the firmware's
real memory map and DRAM size out of the loader's log, then decide (a) with numbers instead of a
guess.

## Verification: what was run, and what it proves

| Check | Command | Result |
|---|---|---|
| the loader still builds | `xnuloader/build.sh` | `69120` bytes (baseline before this work: `68096`; the difference is `platform_dodge`, two helpers and two print blocks) |
| redwood + qemu-virt + dodge port consistency | `tools/check-port.py --all` | `OK: dodge, qemu-virt, redwood` (22/22 dodge checks pass, exit 0) |
| core numbering arithmetic | `docs/port-sm8750/core-number-test.sh` | exit 0; redwood/qemu unchanged, dodge 0..7 <-> 0x0..0x500,0x10000,0x10100 |
| the dodge profile is loadable end to end | `SKIP="kernel images" common/build.sh dodge` | the profile is sourced, the loader builds, and the run stops at the UEFI image, as it must: no dodge `SILICIUM_UEFI.fd` exists yet (`mkxnuimg.py` now says why, in words, instead of tripping an assert) |
| redwood is unchanged end to end | `SKIP="kernel images" common/build.sh redwood` | `out/redwood-boot.img`, 1472512 bytes, header v1 -- the same pipeline, still working |
| boot image packing for dodge (with a stand-in FD) | `UEFI_TARGET=dodge FD_BASE=0xA7100000 FD_SIZE=0x300000 UEFI_FD=/tmp/fake-dodge.fd python3 mkxnuimg.py -o /tmp/x.img` | writes a header_version 4 image (redwood's stays 1, from its own toml) |
| the shim carries dodge's addresses | built `BootShim.S` + `mu-silicium.patch` with dodge's defines | 176 bytes, `XNUP` compare + `movz x5,#0xf000,lsl#16` present; unpatched source is 112 bytes without them |

**One bug fixed on the way through.** `common/build.sh`'s boot step did not look at
`mkxnuimg.py`'s exit status, so `common/build.sh dodge` used to print its UEFI error *and* then the
cheerful `build: out/dodge-boot.img` line, although no image was written -- the first person to try a
dodge build would have gone looking for a file that never existed. Both commands in that step now
honour their status:

```sh
python3 xnuloader/mkpayload.py -o out/usb-payload.bin loader.efi=$L --usb > /dev/null || die "payload not made"
FD_BASE=$FD_BASE ... python3 mkxnuimg.py -p out/usb-payload.bin -o out/$DEVICE-boot.img || die "no boot image: see above"
```

and the result is honest: `common/build.sh dodge` exits 1 with `build.sh: no boot image: see above`
after `mkxnuimg.py`'s three-line explanation, while `common/build.sh redwood` still writes
`out/redwood-boot.img` (1472512 bytes) and exits 0.

**Not verified, and cannot be here:** that the GOP reports `0xFC800000`; that the firmware's core
MPIDRs are the DT's; that the prime cores are off at handover; that `PSCI` answers on dodge; that the
kernel finds all eight redistributors; anything about the memory map as the *firmware* builds it (the
table above is the source, not a `GetMemoryMap` dump); and the UEFI build itself, which needs the
`Binaries/dodge` submodule and ~3 GB of submodules that are not fetched here.

## Open questions, in the order they will bite

1. **The 469 MiB window** (above). Gate for milestone 1: without a memory-map change the kernel will
   not get its RAM.
2. **`fb_base`** -- `0xFC800000` is inferred from the reservation, not read from the firmware. If it
   is wrong the loader does not even recognise the phone.
3. **`Binaries/dodge`** -- no UEFI build for dodge until the phone's own drivers are extracted.
4. **Core numbering on silicon** -- now printed by the loader; confirm from the log.
5. **`small_cores = 0x3F`** -- a judgement (the vendor DT has no `capacity-dmips-mhz`).
6. **`bootcpu=`** -- which core to start on is a hardware question; `cpus=8` alone is what the
   profile asks for.
7. **`epss`/`cpufreq`** -- SM8750 has no EPSS node anywhere yet; `cpufreq=1` stays out of the profile
   (see `docs/port-sm8750/kernel.md`).
8. **`uefi/BASE` is stale -- one decision needed.** `uefi/BASE` says `e51cd877e31c...`;
   `uefi/mu-silicium.patch` `git apply --check` passes on `42fe563791e5...` (the lead checked), and the
   files in `uefi/files/` here were copied from `42fe563`. Nothing in `uefi/apply.sh` notices, so a fresh
   clone gets a tree that the port was not made against -- the Mu-Silicium drift to watch is any
   `PakalaPkg`/`dodgePkg` change between the two commits. Two ways out, both one line: **bump**
   `uefi/BASE` to `42fe563791e51bf5500c2e470ed294ca0c94b97c` (what was actually verified), or leave it and
   annotate it. Taken here: annotate, because I cannot check out `e51cd877` in this environment (no such
   object in the checkout at `/tmp/Mu-Silicium`) and so cannot say whether bumping would break redwood's
   port files; the note is in `uefi/README.md`, next to the build instructions, and `BASE` stays a bare
   commit hash because `apply.sh` reads it with `$(cat BASE)`.