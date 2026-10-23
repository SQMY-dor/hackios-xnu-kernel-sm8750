# Building the kernel here: what works, what does not, and what it cost

This is the record of standing the toolchain up and building `xnu-8796.121.2` for
`DEVELOPMENT_ARM64_BCM2837` on this machine (Debian 12, x86_64, 12 cores, clang 14.0.6).
It is written for the next person who has to do it, so every step says why it exists,
what it needs, and how long it took. Nothing here was measured on a phone: there is no
SM8750 hardware in this environment, so "works" always means "produced the artifact",
never "booted".

Working copy: `/root/xnu kernel/hackios`, 94 GB filesystem with **14-16 GB free**
throughout. The repository path contains a space -- see 3.7.

---

## 1. The short version

```sh
# 1. theos (cctools) + iPhoneOS16.5.sdk in ~/theos        ~830 MB on disk, ~15 s
mkdir -p ~/theos && git clone --depth 1 https://github.com/theos/theos.git ~/theos
curl -sL -o /tmp/iostc.tar.xz \
  https://github.com/L1ghtmann/llvm-project/releases/latest/download/iOSToolchain-x86_64.tar.xz
mkdir -p ~/theos/toolchain && tar -xJf /tmp/iostc.tar.xz -C ~/theos/toolchain
THEOS=~/theos ~/theos/bin/install-sdk iPhoneOS16.5

# 2. host packages this image did not have                    <1 MB
apt-get install -y autoconf automake libtool uuid-dev libssl-dev

# 3. Apple's sources + this repository's changes              ~100 MB, 3 s
xnu/apply.sh

# 4. dependency sources, host tools, the SDK overlay, and the two
#    static libraries built against the kernel's own headers  ~120 MB, 25 s
xnu-deps/setup.sh

# 5. the kernel                                               ~500 MB, 55 s at -j12
./xnu-build.sh -j12 -k

# 6. is it there, and is it this build's?
ls -l --time-style=full-iso \
  xnu-src/xnu-8796.121.2/BUILD/obj/DEVELOPMENT_ARM64_BCM2837/mach.development.bcm2837

# 7. does the port agree with itself?  (a device name, or --all)
tools/check-port.py redwood
```

**The build is judged by the artifact, not by make's exit status.** `./xnu-build.sh -k`
always exits 2: after the kernel is linked and stripped, the export check
(`config/Makefile:121 check_all_exports`) and three symbolsets fail on DriverKit RPC
names from the `iig` stubs. `xnu/README.md` documents this as pre-existing. Measured
here: **222** `exported name not in import list` lines, **0** compiler errors. The
decisive lines of the log:

```
             LD mach.development.bcm2837.unstripped
       DSYMUTIL mach.development.bcm2837.dSYM
        LIBTOOL mach.development.bcm2837.a
...
make[4]: *** [.../config/Makefile:121: check_all_exports] Error 1
```

## 2. Result on this machine (the baseline the port is judged against)

Unmodified repository at `git rev-parse HEAD` = `d82c64a`, before any SM8750 work:

| | |
|---|---|
| artifact | `xnu-src/xnu-8796.121.2/BUILD/obj/DEVELOPMENT_ARM64_BCM2837/mach.development.bcm2837` |
| size | **15,191,872 bytes** |
| mtime | 2026-10-24 05:59:55 +0800 (build started 05:59:00 -- 55 s, `-j12`) |
| kind | `Mach-O 64-bit arm64 executable` (`file`) |
| make exit | 2, from `check_all_exports` after the link; 0 compiler errors |
| unstripped | 18,972,784 bytes, same directory |
| `prebuilt/mach.development.bcm2837` | 15,623,056 bytes -- 431,184 bytes larger |

The size difference against `prebuilt/` is expected and is **not** a fault: `prebuilt/`
was made with Apple's clang 16, this machine has Debian clang 14.0.6, and the two emit
different code. What a port change must be judged against is the number above, produced
the same way on the same machine.

Cost measured here: theos 824 MB, `xnu-deps` 117 MB, `xnu-src` 493 MB (with
`BUILD/`), `out/` 156 KB. A clean rebuild (`rm -rf BUILD`) is 55 s; an incremental
one is seconds. `xnu-deps/setup.sh --stage1` is idempotent and re-runs in ~10 s.

---

## 3. What each step needs, and what this image was missing

`xnu/README.md` lists the packages; this image had all of them except the autotools.
Six things then failed, in this order. They are fixed in the repository now, so a fresh
clone with the same prerequisites builds without them.

### 3.1 `autoconf`/`automake`/`libtool` (missing package)

`xnu-deps/setup.sh` builds mig from `mm_bootstrap_cmds` with `autoreconf --install`.
Without it: `setup: mig did not build`. `apt-get install autoconf automake libtool`.

### 3.2 `uuid-dev` (missing package)

XNU's SETUP host tools include `<uuid/uuid.h>` through
`xnu-deps/hostinc/hostcompat.h`. Without it the header export fails with
`fatal error: 'uuid/uuid.h' file not found` in `decomment`, `replacecontents`,
`setsegname`, `kextsymboltool` and `config`. `apt-get install uuid-dev`.

### 3.3 `strlcpy`/`strlcat` are not in glibc before 2.38 -- **change in `xnu-deps/hostinc/hostcompat.h`**

`SETUP/replacecontents/replacecontents.c` calls `strlcat` (lines 72-76), a BSD
function glibc only gained in 2.38; this image has 2.36, so linking that host tool fails
with `undefined reference to 'strlcat'` and the header export stops there.

**This is a local modification to a tracked file.** The header now carries a
`#if defined(__GLIBC__) && __GLIBC_MINOR__ < 38` block with `host_strlcpy`,
`host_strlcat` and `#define`s. It is the force-included host-tools-only header, so no
kernel source sees it, and on a glibc >= 2.38 machine the block compiles to nothing.

### 3.4 The clang wrapper dropped a flag this clang needs -- **change in `xnu-deps/host/bin/xnu-clang`**

XNU's makefiles pass `-ftrivial-auto-var-init=zero` **together with**
`-enable-trivial-auto-var-init-zero-knowing-it-will-be-removed-from-clang`. Only the
latter lets older clangs accept the former; clang >= 16 rejects that switch as unknown.
Apple's clang is >= 16, so the wrapper threw the switch away -- and on this machine
(Debian clang 14.0.6) every kernel object then failed with

```
clang: error: '-ftrivial-auto-var-init=zero' hasn't been enabled; enable it at your own
peril for benchmarking purpose only with '-enable-trivial-auto-var-init-zero-...'
```

**Local modification to a tracked file.** The wrapper now drops the switch from the
command line and re-adds it right after `-ftrivial-auto-var-init=zero` **only if** the
compiler accepts it (probed once with a one-line test translation unit, answer cached in
`/tmp/.xnu-clang-auxvar-clang*`). Both clang generations work.

### 3.5 Apple's `makesyscalls.sh` needs BSD awk -- **change in the kernel tree**

macOS's BSD awk and every Debian awk (mawk, gawk, original-awk/oawk) disagree about
unknown escapes: `printf("\t{ \(sy_call_t *\)...")` prints `(sy_call_t *)` on macOS
(the backslash is dropped) and `\(sy_call_t *\)` everywhere on Linux (the backslash is
kept), which does not compile:

```
init_sysent.c:48:4: error: expected expression
        { \(sy_call_t *\)(void (*)(void))nosys, NULL, _SYSCALL_RET_INT_T, 0, 0},
          ^
```

All three Debian awks were tested and all keep the backslash, so no
`update-alternatives` choice fixes it. The fix belongs in the generator, and is exactly
what the generated file is supposed to contain:

```diff
--- a/bsd/kern/makesyscalls.sh
+++ b/bsd/kern/makesyscalls.sh
@@ -671,14 +671,14 @@
-		printf("\t{ \(sy_call_t *\)(void (*)(void))%s, %s, %s, %s, %s},",
+		printf("\t{ (sy_call_t *)(void (*)(void))%s, %s, %s, %s, %s},",
 ...
-		printf("\t{ \(sy_call_t *\)(void (*)(void))%s, %s, %s, %s},\n",
+		printf("\t{ (sy_call_t *)(void (*)(void))%s, %s, %s, %s},\n",
```

Two lines. Proven by a full `rm -rf BUILD` rebuild with stock mawk, not by a
workaround awk. (For anyone bisecting: symlinking gawk into `xnu-deps/host/bin/awk`
also gets past the symptom, because gawk drops the escape too -- but that hides a real
portability bug and is not in the tree.)

### 3.6 `dsymutil` and `python` -- **changes in `xnu-deps/setup.sh`**

Two host tools the build expects and `setup.sh` did not provide:

* `dsymutil` -- `MakeInc.kernel:131` (with `BUILD_DSYM=1`) runs
  `dsymutil --minimize` on the linked kernel. Theos ships it next to `ld`;
  `setup.sh` linked `nm`, `otool`, `strip`, `lipo`, `libtool`, `ctf_insert`,
  `codesign_allocate` and `install_name_tool` -- not `dsymutil`. Symptom:
  `bash: --minimize: command not found` / `Error 127`, and no
  `mach.development.bcm2837` is installed (only the `.unstripped` file is linked).
  Added to the link loop.
* `python` -- XNU installs `tools/lldbmacros` into the kernel's dSYM; its scripts
  begin `#!/usr/bin/env python`, and Debian has only `python3`. About 200
  `/usr/bin/env: 'python': No such file or directory` failures at the very end of the
  build. `setup.sh` now creates `host/bin/python -> /usr/bin/python3`.

Both are additions to `xnu-deps/setup.sh`, a tracked file -- local modifications in the
same sense as 3.3 and 3.4.

### 3.7 The space in the path

```
/root/xnu kernel/hackios
```

XNU's makefiles do not survive a space in any path (`README.md` says so; the first
failure is `make install` of mig: `/bin/bash: line 24: /root/xnu: No such file or
directory`). The tree was **not** copied or moved: it is reached through a space-free
bind mount of the same inodes.

```sh
mkdir -p /mnt/hk
mount --bind "/root/xnu kernel/hackios" /mnt/hk   # needs root; the same files, not a copy
cd /mnt/hk && ./xnu-build.sh -j12 -k
```

`df` shows the same filesystem (`/dev/nvme0n1p2[/root/xnu kernel/hackios]`), and edits
made under `/mnt/hk` are the files in the repository. If a bind mount is not possible
(no root), clone to a space-free path instead -- do not try to quote the space.

---

## 4. What this environment cannot do

Said plainly, because the port's evidence has to be honest about it:

* **Nothing can be booted.** There is no OnePlus 13 / SM8750 hardware here and no way to
  flash one. Every claim about SM8750 behaviour in `docs/port-sm8750/` is sourced
  (mainline DT, the vendor DTB, Mu-Silicium) or marked as an open question; none of it is
  a measurement.
* **The UEFI port cannot be built** (`uefi/`): Mu-Silicium needs ~3 GB of submodules and
  EDK2, which are not fetched here. `uefi/README.md` says what to run elsewhere.
* **The loader builds, but its output cannot be run**: `xnuloader/build.sh` produces
  `loader.efi` with clang + lld-link; that is a build artifact, not a working loader.
* **The iOS userland is out of scope**: `ios165/fetch.sh` is a 7.4 GB download and
  ~5.3 GB on disk, more than the free space here, so no system image,
  `userland/build.sh` or `mkxnuimg.py` run was attempted (they need Apple's files).
* **The ath11k Wi-Fi driver is not built** (`tools/mk-ath11k.sh`): redwood-only, and not
  needed for the SM8750 port's first milestone (`WIFI_ATH11K=0`).

## 5. Reproducing from scratch, and checking the result is the same

```sh
cd /mnt/hk                       # or any path without spaces
git clone <repo> && cd hackios
xnu/apply.sh                     # 3 s,   ~100 MB
xnu-deps/setup.sh                # 25 s,  ~120 MB  (stage 1 + stage 2)
rm -rf xnu-src/xnu-8796.121.2/BUILD
touch out/.start && ./xnu-build.sh -j"$(nproc)" -k
K=xnu-src/xnu-8796.121.2/BUILD/obj/DEVELOPMENT_ARM64_BCM2837/mach.development.bcm2837
[ "$K" -nt out/.start ] && stat -c '%s bytes, %y' "$K"   # trust this, not make's status
```

Judging a change: build before, build after, compare `stat -c %s` and the symbol set
(`nm -n ...unstripped`), never the exit status. Note that `prebuilt/mach.development.bcm2837`
is not a reference for this: it was built with Apple clang 16, so it differs from any build
made here by compiler version alone (measured: 15,623,056 vs 15,191,872 bytes). `tools/kernel-delta.sh`
is a different tool -- it prints the kernel tree's source delta since a `new-workspace.sh`
workspace was made, and says nothing about binaries.

## 6. What was run for this port, and what it showed

| step | state |
|---|---|
| theos + cctools + iPhoneOS16.5.sdk | installed in `~/theos`, 824 MB |
| `xnu/apply.sh` | OK -- at baseline 73 changed files + 104 new, 3 s; with the port 74 changed files, and `xnu/files/` 106 files |
| `xnu-deps/setup.sh` (stage 1 + 2) | OK after 3.1-3.3 and 3.6 -- `libfirehose_kernel.a` 5,728 B, `libpthread_kext.a` 46,504 B, `BUILD/obj/EXPORT_HDRS/{osfmk,bsd,iokit,...}` |
| `./xnu-build.sh -j12 -k` | artifact produced: 15,191,872 B (baseline), fresh, 0 compiler errors, 55 s -- and 15,192,080 B after the port, see 9.3 |
| `tools/check-port.py redwood` | 20 checks, 0 failed at baseline; 22 checks, 0 failed after the port (section 8.1 added two) |
| `tools/check-port.py dodge` | failed until the loader profile and `platform_dodge` landed; **22 checks, 0 failed, exit 0** as of section 9 |

## 7. Files changed under this task, and why

| file | change | tracked? |
|---|---|---|
| `xnu-deps/hostinc/hostcompat.h` | strlcpy/strlcat fallback for glibc < 2.38 | yes -- local modification |
| `xnu-deps/host/bin/xnu-clang` | pass `-enable-trivial-auto-var-init-zero-...` only if clang needs it | yes -- local modification |
| `xnu-deps/setup.sh` | link `dsymutil`; add `host/bin/python -> python3` | yes -- local modification |
| `bsd/kern/makesyscalls.sh` (in `xnu-src/`, travels in `xnu/redwood.patch`) | plain `(sy_call_t *)` in two printf formats | yes, through the patch (owner: kernel-soc, exported with `xnu/export.sh`) |
| `tools/check-port.py` | new | new file |
| `docs/port-sm8750/build.md` | this file | new file |
| `out/` | build logs (`apply.log`, `setup-*.log`, `kernel-build-baseline.log`) | ignored |

Nothing in `common/devices`, `xnuloader/`, `uefi/` or `xnu/files` was edited by
this task.

## 8. `tools/check-port.py`, and how it was proven to bite

A port says the same thing four times -- the profile, the loader's `struct platform`, the
boot shim toml and the phone's device tree -- and the four drift apart silently, because
nothing fails until a phone does not come up. The checker reads all four and exits
non-zero on any disagreement. Nothing but python3 and dtc is needed.

```sh
tools/check-port.py redwood          # the phone the drivers were written for
tools/check-port.py dodge            # the SM8750 port
tools/check-port.py redwood --dtb prebuilt/uefi/redwood.dtb
tools/check-port.py --all            # every profile in common/devices/
```

It checks: the profile has no `TODO`/`FIXME`/`XXX` left and a real `FB_BASE`; a
`struct platform` exists for the device and the loader can actually select it (it is in
`platforms[]`, or it is the default `PLAT`); `FB_BASE` equals `platform.fb_base`, and no two
platforms claim the same framebuffer base; `PAYLOAD_BASE` in the profile equals the
loader's `#define`; `FD_BASE`/`FD_SIZE` agree with `uefi/files/Resources/Configs/
<UEFI_TARGET>.toml [uefi_fd]` and the image does not reach into the payload;
`gic_dist`/`gic_redist` equal the device tree's `arm,gic-v3` `reg`; `cores` equals the
number of `cpu@` nodes and `core_shift` matches whether any `reg` reaches `0x100` (and the
core numbers are then unique); `io_base`/`io_size` are non-zero and cover the GIC;
`small_cores` names only existing cores and is consistent with `capacity-dmips-mhz`; and
every redwood-only boot argument (`touchscreen=`, `gpu=`, `cpufreq=`, `adsp=`, `wifi=`) in
`BOOTARGS` is either absent or justified by a comment in the profile. QEMU profiles are
held to the fields a computer has (SMP against `platform.cores`, `cpus=` in `BOOTARGS`)
instead of the phone ones.

Proven by breaking the redwood port on purpose, in a scratch copy, one field at a time --
each was caught and made the script exit 1:

| drift introduced | result |
|---|---|
| `.gic_redist` 0x17A60000 -> 0x17A70000 | FAIL: loader 0x17a70000 vs device tree 0x17a60000 |
| `.cores` 8 -> 7 | FAIL: loader 7 vs device tree 8 |
| `FB_BASE` 0xE1000000 -> 0xE2000000 (profile only) | FAIL: profile vs loader disagree |
| `FB_BASE` -> 0 | FAIL: 0 identifies nothing + mismatch |
| `.fb_base` ...0001 (loader only) | FAIL: mismatch |
| `PAYLOAD_BASE` changed (profile only) | FAIL: profile vs loader `#define` |
| `FD_SIZE` -> 0x0 in the profile | FAIL: FD_SIZE is not zero |
| toml `size` 0x200000 -> 0x400000 | FAIL: toml vs profile |
| `&platform_redwood` removed from `platforms[]` | FAIL: the loader never selects it |
| `.io_size` 0x3FC00000 -> 0x01000000 | FAIL: io window does not cover the GIC |
| `# TODO fill this in` appended to the profile | FAIL: TODO leftovers |
| `.small_cores` 0x0f -> 0x1ff | FAIL: names cores that do not exist |
| `.core_shift` 8 -> 0 | FAIL: loader 0, device tree wants 8; then the numbers collapse |
| `.core_stride` 0 -> 6 on one-cluster redwood | FAIL: the inverse invents 0x10000/0x10100 |
| `platform_redwood.name` -> "redwud" (kernel table has no such row) | FAIL: silent fallback to redwood |
| a test profile with `touchscreen=1` and no comment | FAIL: not justified |

A cleared copy passes again, so the failures are the drift and not the check. On the
current tree: redwood 22/0, dodge 22/0, qemu-virt 4/0, all exit 0.

The core-numbering check grew a second half when `struct platform` gained `core_stride`:
it now applies the same formula the loader and the kernel use
(`number = ((mpidr >> shift) & 0xff) + ((mpidr >> (shift+8)) & 0xff) * stride`), requires
the device tree's cores to map onto distinct numbers `0..cores-1`, **and** requires the
inverse (`core_mpidr()`, which the loader uses for PSCI CPU_ON and `bootcpu=N`) to land
back on a real MPIDR. Both directions matter: with `core_stride = 0` on a two-cluster
phone the eight cores collapse to six numbers, and with a bogus `core_stride = 6` on the
one-cluster redwood the numbers still look fine while `core_mpidr()` starts inventing
`0x10000`/`0x10100`. The checker was tested against both.

### 8.1 A bug the checker found, worth reading before touching the loader

Running the checker against a *simulated* dodge port (FACTS.md values in a scratch copy,
before loader-port wrote theirs) exposed a real structural limit, not a drift:
**`struct platform` could not describe a phone whose CPUs are numbered in two affinity
fields.** loader-port has since fixed it by adding `core_stride` (and `core_number()` /
`core_mpidr()` in loader.c); the reasoning below is kept because it is the reason the
field exists, and because the checker now guards it in both directions.

The dodge vendor DT has `cpu@0..cpu@500` (six Oryon performance cores, regs
`0x0,0x100,...,0x500`) and `cpu@10000,10100` (the two prime cores, `0x10000,0x10100`).
At the time, every core number the loader derived was `(mpidr >> core_shift) & 0xff` --
one field, no cluster term (the four sites are now `core_number()` / `core_mpidr()` in
loader.c: `boot_core` at `:3272`, the MPIDR for PSCI CPU_ON at `:3278`, `small_cores` at
`:3314`, and `bootcpu=N`). With `core_shift = 8` only, the eight MPIDRs collapse to six
numbers (`0x10000 -> 0`,
`0x10100 -> 1`), so:

* enumeration only ever produces `0x0..0x700`, so the real prime cores are never offered
  to the kernel, and the kernel is told about `0x600`/`0x700`, which no core on this SoC
  has; PSCI CPU_ON for them cannot work;
* `small_cores` bit 0 would mark both `cpu@0` and `cpu@10000`;
* `bootcpu=N` takes one digit 0-7 shifted by 8, so the prime cores cannot be named.

The fix, now in the tree, is a `core_stride` in `struct platform` using the same formula
the kernel side already has (`xnu/files/bsd/sys/redwood_soc.h:120`); an explicit per-phone
core table would work too. The checker fails the collapsed case with that explanation, so
it cannot be papered over by choosing a flattering `small_cores`.

## 9. Gate run for the SM8750 port (kernel-soc + loader-port landed)

Everything below was run in this order, on `2026-10-24 06:12`, from `/mnt/hk` (the same
tree; see 3.7). Commands are given so anyone can repeat them and get the same answers.

### 9.1 The patch reproduces the tree exactly (gate 1)

```sh
rm -rf /tmp/patchtest && mkdir -p /tmp/patchtest && cd /tmp/patchtest
git init -q .
git fetch -q --depth 1 "file://$REPO/xnu-src/xnu-8796.121.2" c54f35ca767986246321eb901baf8f5ff7923f6a
git checkout -q FETCH_HEAD
git apply --check xnu/redwood.patch && git apply xnu/redwood.patch
cp -a xnu/files/. .
diff -rq --exclude=.git --exclude=BUILD /tmp/patchtest xnu-src/xnu-8796.121.2
```

Result: `74` `diff --git` sections, `git apply --check` clean, **diff exit 0, zero lines** --
what `xnu/apply.sh` produces from a fresh clone is byte-identical to the working tree.
This is the check that caught the earlier regression (when the patch had 73 sections and
the `makesyscalls.sh` fix was missing, this diff printed one line). Worth running before
every build: 2 seconds, and it is the only thing that proves the patch is not stale.

### 9.2 The port is internally consistent (gate 2)

```sh
tools/check-port.py redwood    # 22 checks, 0 failed, exit 0
tools/check-port.py dodge      # 22 checks, 0 failed, exit 0
tools/check-port.py --all      # exit 0
```

### 9.3 A clean build, judged by the artifact (gate 3)

```sh
rm -rf xnu-src/xnu-8796.121.2/BUILD && touch out/.kernel-start-port
./xnu-build.sh -j12 -k              # 58 s
K=xnu-src/xnu-8796.121.2/BUILD/obj/DEVELOPMENT_ARM64_BCM2837/mach.development.bcm2837
stat -c '%s bytes, %y' $K           # 15,192,080 bytes, 2026-10-24 06:13:38 +0800
[ $K -nt out/.kernel-start-port ]   # yes
```

| | baseline (before the port) | after kernel-soc + loader-port | delta |
|---|---|---|---|
| `mach.development.bcm2837` | 15,191,872 B | **15,192,080 B** | **+208 B** |
| make exit | 2 (`check_all_exports`) | 2 (`check_all_exports`) | -- |
| compiler errors | 0 | **0** | -- |
| warnings | 8 | **8, byte-identical set** | **none new** |
| `exported name not in import list` | 222 | 222 | -- |
| symbols (`nm`) | 51,753 | 51,757 | +4 |

The 208 bytes are the new strings and the second SoC row -- exactly what was expected from
adding a table and one diagnostic message without touching redwood's numbers. The eight
warnings are the same eight as before the port (`SETUP/installfile`, `SETUP/config`, mawk's
escape notices, the `-j` submake note); a sorted diff of the two warning sets is empty.

### 9.4 Is `redwood_soc.c` really in the kernel? (gate 4a)

A file listed in `bsd/conf/files` that never gets linked would silently "pass". It is in:

```sh
NM=~/theos/toolchain/linux/iphone/bin/nm            # cctools; GNU nm cannot read Mach-O
$NM -n $K/mach.development.bcm2837.unstripped | grep redwood_soc
```

```
fffffff0071b91a0 s _redwood_soc_redwood
fffffff0071b9288 s _redwood_soc_sm8750
fffffff0074ad07c S _redwood_soc              <- the global the drivers call
fffffff007e2f988 b _redwood_soc.chosen       <- its function-local cache
```

The baseline has **0** symbols matching `redwood_soc`; this build has **4**, and they are
`_redwood_soc` (global, text) plus the two `static const` rows and the cached pointer.
`$NM $K/bsd/DEVELOPMENT/redwood_soc.o` confirms the object is built and that its `U`
references (`SecureDTLookupEntry`, `SecureDTGetProperty`, `strcmp`) are the ones the
kernel resolves. The complete symbol delta against the baseline is those four additions
plus some renumbered `__startup_LOCKS_*` locals (the link order shifted), nothing else.

### 9.5 The SoC names, and the cpufreq guarantee for SM8750 (gate 4b/4c)

```sh
strings -a $K/mach.development.bcm2837 | grep -xE 'redwood|dodge|sm8750|pakala'
```

```
dodge, pakala, redwood (x2), sm8750      <- this build
redwood (x2)                             <- the baseline: no dodge/sm8750 at all
```

`epss_domains == 0` for the SM8750 row is not just a comment -- it is in the linked image.
The two rows' first three words (`epss_base`, `epss_domain_size`, `epss_domains`) read out
of `redwood_soc.o` with `otool -s __DATA __const`:

```
redwood @0x180:  18591000 00000000 | 00001000 | 00000003     -> base 0x18591000, size 0x1000, 3 domains
dodge   @0x270:  17d91000 00000000 | 00001000 | 00000000     -> base 0x17D91000, size 0x1000, 0 domains
```

and the same byte patterns are in the linked kernel (searched with `struct.pack('<QII',
...)`): `(0x17D91000, 0x1000, 0)` once, `(0x18591000, 0x1000, 3)` once.

The reason a zero matters is the guard it feeds, `xnu/files/bsd/dev/redwood_cpufreq.c`
`cpufreq_wanted()`:

```c
if (soc->epss_domains == 0) {
        if (PE_parse_boot_argn("cpufreq", &on, sizeof(on)) && on != 0) {
                tell("cpufreq: not done: no EPSS address is known for this SoC (\"%s\")\n", soc->name);
        }
        return false;
}
```

so on SM8750 a `cpufreq=1` boot arg is refused and logged instead of writing the unverified
0x17D91000. That message string (`cpufreq: not done: no EPSS address is known for this
SoC`) is present in the built kernel, which proves the guard was compiled in and not
optimised away.

## 10. Final gate, after the GIC redistributor-stride change

Run on `2026-10-24 06:30`, same tree, same commands. The change under test:
`xnu/files/osfmk/arm64/gic_v3_irq.c` no longer hardcodes the redistributor frame
spacing (`GICR_FRAME_SIZE_DEFAULT` 0x20000) -- `gic_v3_irq_cpu_init()` reads
`redistributor-stride` from `/arm-io/gic` and `gic_find_redistributor()` steps by it.
That matters on SM8750, whose frames are 0x40000 apart: walking at 0x20000 lands inside
frames, matches no `GICR_TYPER` affinity, and panics `gic: no redistributor for MPIDR`.

### 10.1 Patch round-trip

```sh
# in /tmp/patchtest: clean c54f35ca + git apply xnu/redwood.patch + cp -a xnu/files/. .
diff -rq --exclude=.git --exclude=BUILD /tmp/patchtest xnu-src/xnu-8796.121.2
```

`0` lines, exit 0. `grep -c '^diff --git'` = **74** (unchanged, as expected:
`gic_v3_irq.c` is a *new* file, so it travels in `xnu/files/`, not in the patch);
`sy_call_t` = 4 lines, `makesyscalls` = 3 lines.

### 10.2 Checker

```
tools/check-port.py redwood    exit 0 -- 24 checks, 0 failed
tools/check-port.py dodge      exit 0 -- 24 checks, 0 failed
tools/check-port.py qemu-virt  exit 0 --  4 checks, 0 failed
tools/check-port.py --all      exit 0 -- OK: dodge, qemu-virt, redwood
```

Two checks were added in this pass, both derived from the device tree, so the stride bug
would have been caught from the DT alone before any hardware:

* `platform.gic_redist_stride == the device tree's redistributor-stride` (the two DT cells
  combined as `cells[0] << 32 | cells[1]`; the property is optional, default 0x20000);
* `the redistributor region holds every core's frame` -- `gic_redist_size` must be at
  least `stride * cores`, and must agree with the DT's `reg` size when both are given.

Both bite, verified in a scratch copy: stride 0x20000 on dodge -> exit 1 (*loader 0x20000
vs device tree 0x40000 ... cores past the first would find no redistributor*); removing
dodge's `gic_redist_size` so the 1 MB default applies -> exit 1 (*reserves 0x100000 ...
need 0x200000*); stride 0x40000 on redwood -> exit 1; redwood's `gic_redist_size` shrunk
to 0x40000 -> exit 1. Clearing them restores exit 0.

While adding them I had to fix the checker's own DT parsing: the dodge GIC node contains
an `arm,gic-v3-its` child, and the old lazy `.*?};` regex stopped at the first child, so
`redistributor-stride` was read from a truncated body. It now scans the node
brace-balanced and strips child nodes before reading the parent's own properties.

### 10.3 Clean build

```sh
rm -rf xnu-src/xnu-8796.121.2/BUILD && ./xnu-build.sh -j12 -k     # 54 s
```

| | baseline | after SoC table | after GIC stride |
|---|---|---|---|
| size | 15,191,872 B | 15,192,080 B | **15,192,104 B** |
| delta vs previous | -- | +208 B | **+24 B** |
| delta vs baseline | -- | +208 B | **+232 B** |
| compiler errors | 0 | 0 | **0** |
| warnings | 8 | 8 | **8, identical set** |
| symbols | 51,753 | 51,757 | **51,758** |

mtime `2026-10-24 06:31:04 +0800`, newer than the build start; 222 export complaints,
make exit 2 from `check_all_exports` only. The +24 B is the new panic format string and
the DT property name -- the walk itself costs no size because it already loaded
`gicr_stride` from memory.

`redwood_soc` is still linked, four symbols, unchanged from 9.4:

```
fffffff0071b91a0 s _redwood_soc_redwood
fffffff0071b9288 s _redwood_soc_sm8750
fffffff0074ad158 S _redwood_soc
```

### 10.4 Proof from the binary that the hardcoded 0x20000 is no longer the only path

This is the part that makes 10.3 mean anything. Four independent facts:

**a) The walk step is a variable, not an immediate.** Disassembling the object
(`otool -tv gic_v3_irq.o`) and grepping the code for the constant finds **zero**
occurrences of `0x20000` in any instruction. Instead the loop reads globals:

```
00000000000006cc  adrp x10, _gicr_base
00000000000006d0  ldr  x11, [x10]         ; frame = gicr_base
00000000000006d4  adrp x10, _gicr_stride
00000000000006d8  ldr  x10, [x10]         ; stride = gicr_stride      <- was the constant
00000000000006dc  adrp x12, _gicr_size
00000000000006e0  ldr  x12, [x12]         ; end = gicr_base + gicr_size
00000000000006e4  add  x12, x12, x11
00000000000006e8  add  x13, x11, x10      ; frame + stride
00000000000006ec  cmp  x13, x12
```

The relocations confirm those loads name three different globals, and nothing else:

```
000006d0  PAGOF12  _gicr_base
000006d8  PAGOF12  _gicr_stride
000006e0  PAGOF12  _gicr_size
```

**b) The value is written from the device tree.** `gic_v3_irq_cpu_init()` stores the
parsed stride into that same global (`0x65c adrp x8, _gicr_stride` / `0x660 str x24, [x8]`,
relocation `00000660 PAGOF12 _gicr_stride`), after the validation branch at 0x618-0x658
(compare against `0x10 << 12` = 0x10000 minimum, the power-of-two `cnt`/`uaddlv` test, the
`reg[3]` bound, then `udiv` by the core count).

**c) The default is still 0x20000 and it is stored data, not dead code.** `_gicr_stride`
is a real global in `__DATA,__data` (`nm`: `0000000000000c20 d _gicr_stride` in the
object, `fffffff007a99270 d _gicr_stride` in the linked kernel). Reading its initial word
out of the linked image (segment `__DATA` fileoff 11059200 for vmaddr
0xfffffff007a90000, so offset 0xa95270) gives `0x20000` -- so a loader that writes no such
property still walks exactly as today.

**d) Both the property name and the new failure mode are in the image.**

```
$ strings -a mach.development.bcm2837 | grep -E 'redistributor-stride|/arm-io/gic'
/arm-io/gic
redistributor-stride
gic: unusable redistributor-stride 0x%llx (region 0x%llx) in the device tree @%s:%d
gic: no redistributor for MPIDR 0x%llx @%s:%d
```

and the arm64 slice is intact and fully resolved: `file` says *Mach-O 64-bit arm64
executable, flags:<NOUNDEFS|PIE>*, `otool -h` shows `cputype 16777228` (arm64), 25 load
commands -- the kernel linked with no undefined symbols, which it could not do if
`_gicr_stride` were missing.

### 10.5 The line in this change most likely to be re-broken

The property is written by the loader as **two 32-bit cells** and must be read the same
way. `xnuloader/loader.c` writes `uint32_t gic_stride[2] = { 0, stride }` through
`dt_prop()`, which copies bytes verbatim -- so the property is `<0x0 0x40000>`, exactly
like the vendor DT. `gic_v3_irq.c` therefore reads it as `uint32_t const *` and combines
`cells[0] << 32 | cells[1]`. Reading it as `uint64_t const *` (as `reg`, which really is
four native u64s, must be) would yield `0x400000000`, and the validation below it would
panic -- which is what that guard exists for.