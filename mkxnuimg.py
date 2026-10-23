#!/usr/bin/env python3
"""
Pack the redwood UEFI (with the hook that starts the XNU loader) and an optional payload
into an Android boot image for `fastboot boot`.

  kernel = gzip(BootShim + UEFI FD + ["XNUP" container]) + DTB

The boot shim copies the FD to its base and the payload to PAYLOAD_BASE.

The UEFI pieces are taken from a Mu-Silicium tree built here (Mu-Silicium/, see uefi/README.md)
or, when there is none, from prebuilt/uefi/.

usage: mkxnuimg.py [-p payload.bin] [-o out.img]

Another device (common/devices/<name>.conf, read by common/build.sh) sets these in the environment:
  UEFI_TARGET   Mu-Silicium device name (default redwood)    UEFI_FD, DTB   files to use instead
  FD_BASE, FD_SIZE, PAYLOAD_BASE                              addresses from its UEFI port's memory map
  DEVICE        the profile's name, used when UEFI_TARGET is not set

What is device-specific here follows TARGET: the boot image's name, the DTB and the Android boot
header version. The last two are read from our own UEFI port copy of the device's config,
uefi/files/Resources/Configs/<target>.toml (the same file Mu-Silicium's build_uefi.py reads), so
there is one place that says which header version a phone needs.
"""
import argparse, gzip, os, re, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))
MU = os.path.join(HERE, 'Mu-Silicium')
PREBUILT = os.path.join(HERE, 'prebuilt', 'uefi')
def env_int(name, default):
    v = os.environ.get(name, '')
    return int(v, 0) if v else default
# Everything that depends on the device follows UEFI_TARGET/DEVICE; the defaults below are
# redwood's, the phone this repository was built for, and only apply when neither is set.
TARGET = os.environ.get('UEFI_TARGET') or os.environ.get('DEVICE') or 'redwood'
FD_BASE, FD_SIZE = env_int('FD_BASE', 0x9FD00000), env_int('FD_SIZE', 0x200000)
PAYLOAD_BASE, PAYLOAD_MAX = env_int('PAYLOAD_BASE', 0xF0000000), 0x04000000

ap = argparse.ArgumentParser()
ap.add_argument('-p', '--payload')
ap.add_argument('-o', '--output')          # default: xnu-<target>.img, below
ap.add_argument('--mode', default='RELEASE')
args = ap.parse_args()
if args.output is None:
    args.output = os.path.join(HERE, f'xnu-{TARGET}.img')


def device_config():
    """[uefi_fd] and [boot_image] of uefi/files/Resources/Configs/<target>.toml, if we have it."""
    path = os.path.join(HERE, 'uefi', 'files', 'Resources', 'Configs', f'{TARGET}.toml')
    sections, current = {}, None
    if not os.path.isfile(path):
        return sections
    for raw in open(path, encoding='utf-8', errors='replace'):
        line = raw.split('#', 1)[0].strip()
        if not line:
            continue
        m = re.match(r'\[(.+)\]$', line)
        if m:
            current = m.group(1).strip()
            sections.setdefault(current, {})
            continue
        m = re.match(r'([A-Za-z0-9_]+)\s*=\s*(.+)$', line)
        if m and current:
            sections[current][m.group(1)] = m.group(2).strip().strip('"')
    return sections


CONFIG = device_config()
# The boot header version the phone's bootloader wants (Mu-Silicium's <target>.toml
# [boot_image] header_version: 1 for redwood, 4 for dodge). 1 is what this packer has always
# written, so a device without a config here keeps the old behaviour.
HEADER_VERSION = int(CONFIG.get('boot_image', {}).get('header_version') or 1, 0)

fd_path = os.environ.get('UEFI_FD') or os.path.join(MU, f'Build/{TARGET}Pkg/{args.mode}_CLANGPDB/FV/SILICIUM_UEFI.fd')
if os.path.isfile(fd_path) and os.path.isdir(os.path.join(MU, 'BootShim')):
    shim_dir = os.path.join(MU, 'BootShim')
    for f in ('BootShim.elf', 'BootShim.bin'):
        try: os.unlink(os.path.join(shim_dir, f))
        except FileNotFoundError: pass
    subprocess.check_call(['make', 'REQUIRES_KERNEL_HEADER=1', f'FD_BASE={FD_BASE:#x}', f'FD_SIZE={FD_SIZE:#x}',
                           f'CFLAGS=--target=aarch64-linux-gnu -DPAYLOAD_BASE={PAYLOAD_BASE:#x}'],
                          cwd=shim_dir, stdout=subprocess.DEVNULL)
    parts = {'shim': os.path.join(shim_dir, 'BootShim.bin'), 'fd': fd_path,
             'dtb': os.path.join(MU, f'Resources/DTBs/{TARGET}.dtb'), 'ramdisk': os.path.join(MU, 'Resources/ramdisk'),
             'mkbootimg': os.path.join(MU, 'Resources/Scripts/mkbootimg.py')}
else:
    # prebuilt/uefi holds redwood's build; another device's pieces come from its UEFI port copy.
    our_port = os.path.join(HERE, 'uefi', 'files', 'Resources', 'DTBs', f'{TARGET}.dtb')
    parts = {'shim': os.path.join(PREBUILT, 'BootShim.bin'),
             'fd': os.path.join(PREBUILT, 'SILICIUM_UEFI.fd'),
             'dtb': our_port if os.path.isfile(our_port) else os.path.join(PREBUILT, 'redwood.dtb'),
             'ramdisk': os.path.join(PREBUILT, 'ramdisk'),
             'mkbootimg': os.path.join(PREBUILT, 'mkbootimg.py')}
    if os.environ.get('UEFI_FD'): parts['fd'] = os.environ['UEFI_FD']
shim = open(parts['shim'], 'rb').read()
fd = open(parts['fd'], 'rb').read()
if len(fd) != FD_SIZE:
    sys.exit(f"mkxnuimg: {parts['fd']} is {len(fd):#x} bytes but {TARGET}'s FD_SIZE is {FD_SIZE:#x}.\n"
             f"  The UEFI image must be the one built for {TARGET} (its own <target>.toml [uefi_fd] size):\n"
             f"  build Mu-Silicium (uefi/README.md) or point UEFI_FD at {TARGET}'s SILICIUM_UEFI.fd.\n"
             f"  prebuilt/uefi holds redwood's build and can only be used for redwood.")

blob = shim + fd
if args.payload:
    data = open(args.payload, 'rb').read()
    # the payload file is a complete "XNUP" container (see xnuloader/mkpayload.py)
    assert data[:4] == b'XNUP' and len(data) <= PAYLOAD_MAX - 0x1000, 'bad or oversized payload'
    blob += data
    blob += b'\0' * (-len(blob) % 16)
    print(f'payload: {len(data)} bytes, bytesum={sum(data) & 0xffffffff:08x}')

if os.environ.get('DTB'): parts['dtb'] = os.environ['DTB']
dtb = open(parts['dtb'], 'rb').read()
kernel = args.output + '.kernel~'
open(kernel, 'wb').write(gzip.compress(blob, 6) + dtb)
try:
    subprocess.check_call([sys.executable, parts['mkbootimg'], '--kernel', kernel, '--ramdisk', parts['ramdisk'],
                           '--header_version', str(HEADER_VERSION), '-o', args.output])
finally:
    os.unlink(kernel)
print(f'{args.output}: {os.path.getsize(args.output)} bytes (shim {len(shim)}, uncompressed {len(blob)})')
