# UEFI for redwood

A port of [Project Silicium / Mu-Silicium](https://github.com/Project-Silicium/Mu-Silicium) to the POCO X5 Pro 5G
(redwood). The device is not upstream; the port follows `lisa` (the same SoC package, `KodiakPkg`).

You do not need to rebuild the UEFI to run HackiOS -- a ready image is in `prebuilt/uefi`, and `mkxnuimg.py`
takes it by itself.

What is here:

- `BASE` -- the Mu-Silicium commit the port is made on;
- `mu-silicium.patch` -- changes to existing files:
  `BootShim/BootShim.S` (copies our "XNUP" container, which follows the UEFI image, to 0xF0000000),
  `BootManagerLib` (starts the XNU loader from the container instead of the boot menu);
- `files/` -- new files: `Platforms/Xiaomi/redwoodPkg` (memory map, driver list),
  `Silicon/.../BootManagerLib/XnuLoader.[ch]`, `Resources/Configs/redwood.toml`, `Resources/DTBs/redwood.dtb`
  (the device tree from the phone's vendor_boot), `Binaries/redwood` (UEFI drivers from the firmware
  `OS1.0.3.0.UMSMIXM`, extracted with [UEFIReader](https://github.com/WOA-Project/UEFIReader) from `xbl.img`,
  with Silicium's five usual patches -- see `files/Binaries/redwood/README.md`).

## Building

Packages as in Mu-Silicium's `setup_env.sh` (on Arch: `git base-devel lld nasm clang llvm aarch64-linux-gnu-gcc
python python-pip python-virtualenv`).

```sh
uefi/apply.sh                                   # clones Mu-Silicium (with submodules, ~3 GB) and applies the port
python3 -m venv venv && venv/bin/pip install -r Mu-Silicium/pip-requirements.txt
cd Mu-Silicium
source ../venv/bin/activate
python3 build_uefi.py -d redwood -r RELEASE     # -> Build/redwoodPkg/RELEASE_CLANGPDB/FV/SILICIUM_UEFI.fd
```

**`BASE` is behind the tree the port was last checked against.** `BASE` says
`e51cd877e31c8fbb322032dc4cb6715e83d25ad3`; `mu-silicium.patch` `git apply --check` passes on
`42fe563791e51bf5500c2e470ed294ca0c94b97c` (the commit the SM8750/dodge port was read against, and the
one `files/` was copied from -- see `docs/port-sm8750/loader.md`, "Open questions" 8). Bumping `BASE` to
that commit is the intended fix; it has not been done here because `e51cd877` is not in the checkout
available, so whether redwood's own port files survive the move could not be checked. Until it is
bumped, a fresh `uefi/apply.sh` gives a tree the port was not made against -- compare
`Platforms/OnePlus/dodgePkg` (or `PakalaPkg`) between the two commits before trusting a build.

Another pitfall: `BootShim/Makefile` calls `llvm-objcopy` by bare name, and some distributions ship it
only as `/usr/lib/llvm-<n>/bin/llvm-objcopy`; in that case pass `OBJCOPY=/usr/lib/llvm-14/bin/llvm-objcopy`
(or the equivalent) to `make`. `mkxnuimg.py` builds the shim itself, so it would need the same.

A pitfall: the `mu_nasm` dependency is installed through NuGet and needs Mono. To do without Mono, put the
system nasm in its place:

```sh
D=Mu_Basecore/BaseTools/Bin/mu_nasm_extdep
mkdir -p $D/Linux-x86-64
echo 'version: 20016.1.1' > $D/extdep_state.yaml
ln -s /usr/bin/nasm /usr/bin/ndisasm $D/Linux-x86-64/
```

After a build, `mkxnuimg.py` (called by `./xl enter` and `common/build.sh`) takes the UEFI from `Mu-Silicium/`,
and `tools/update-prebuilt.sh` refreshes `prebuilt/uefi`.

`uefi/export.sh` is the reverse: save the changes made in `Mu-Silicium/` back here.

A build from scratch by these instructions has not been re-run since (the tree was built along the way while
the port was made). For a port to another phone, see `docs/PORTING.md`.
