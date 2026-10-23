#!/usr/bin/env python3
"""Mechanical consistency check for a HackiOS device port.

A port describes the same hardware in four places that must agree:

  common/devices/<dev>.conf                            the profile common/build.sh and common/run.sh source
  xnuloader/loader.c  (struct platform platform_<dev>) what the loader tells the kernel about the SoC
  uefi/files/Resources/Configs/<uefi-target>.toml      where the boot shim puts the UEFI image
  the phone's device tree (DTB)                        the hardware itself

This script reads all four and reports every disagreement. It needs nothing but
python3 and dtc (Debian: apt install device-tree-compiler).

  tools/check-port.py redwood
  tools/check-port.py dodge --dtb /path/to/device.dtb
  tools/check-port.py --all

Exit status: 0 when every check passes, 1 when anything drifted, 2 on a usage or
environment problem (no dtc, unknown device, ...).

What it cannot check, and why, is at the bottom of this file.
"""

import argparse
import glob
import os
import re
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Boot arguments that only make sense on the phone the drivers were written for
# (redwood: Goodix GT9916 touch, Adreno 642L, WCN6750 Wi-Fi, SM7325 EPSS). A ported
# device that passes one of them has to say why in the profile.
REDWOOD_ONLY_ARGS = ("touchscreen", "gpu", "cpufreq", "adsp", "wifi")

# The profile the drivers were written against: its boot arguments are the reference
# they were chosen by, so they are not drift. Every other profile has to justify them.
NATIVE_PROFILE = "redwood"


class Report:
    def __init__(self, device):
        self.device = device
        self.failures = 0
        self.checks = 0

    def ok(self, what, detail=""):
        self.checks += 1
        print("  PASS  %s%s" % (what, (" -- " + detail) if detail else ""))

    def bad(self, what, detail):
        self.checks += 1
        self.failures += 1
        print("  FAIL  %s -- %s" % (what, detail))

    def skip(self, what, why):
        print("  skip  %s -- %s" % (what, why))


# ---------------------------------------------------------------- the profile ---

def parse_conf(path):
    """VAR=value lines of a device profile, plus its comments as (lineno, text)."""
    values, comments = {}, []
    with open(path, encoding="utf-8", errors="replace") as f:
        for lineno, raw in enumerate(f, 1):
            line = raw.rstrip("\n")
            stripped = line.lstrip()
            if stripped.startswith("#"):
                comments.append((lineno, stripped))
                continue
            m = re.match(r"\s*([A-Za-z_][A-Za-z0-9_]*)=(.*)$", line)
            if not m:
                continue
            name, value = m.group(1), m.group(2)
            if '"' in value:
                end = value.find('"', value.find('"') + 1)
                value = value[: end + 1].strip().strip('"')
            elif "'" in value:
                end = value.find("'", value.find("'") + 1)
                value = value[: end + 1].strip().strip("'")
            else:
                value = value.split("#", 1)[0].strip()
            values[name] = value
    return values, comments


def parse_number(text, default=None):
    if text is None:
        return default
    text = str(text).strip().strip('"').strip("'")
    if not text:
        return default
    try:
        return int(text, 0)
    except ValueError:
        m = re.match(r"0[xX][0-9a-fA-F]+|[0-9]+", text)
        return int(m.group(0), 0) if m else default


# ----------------------------------------------------------------- the loader ---

def parse_loader_platforms(path):
    """Every static const struct platform platform_X = { ... }; in loader.c."""
    src = open(path, encoding="utf-8", errors="replace").read()
    src_nc = re.sub(r"/\*.*?\*/", lambda m: re.sub(r"[^\n]", " ", m.group(0)), src, flags=re.S)
    src_nc = re.sub(r"//[^\n]*", "", src_nc)
    platforms = {}
    for m in re.finditer(r"struct\s+platform\s+platform_([A-Za-z0-9_]+)\s*=\s*\{(.*?)\n\};",
                         src_nc, re.S):
        name, body = m.group(1), m.group(2)
        fields = {}
        for fm in re.finditer(r"\.([A-Za-z_][A-Za-z0-9_]*)\s*=\s*([^,{}]+)", body):
            fields[fm.group(1)] = fm.group(2).strip()
        platforms[name] = fields
    default = None
    dm = re.search(r"PLAT\s*=\s*&platform_([A-Za-z0-9_]+)\s*;", src_nc)
    if dm:
        default = dm.group(1)
    registered = set()
    rm = re.search(r"struct\s+platform\s+\*?\s*const\s+platforms\s*\[\s*\]\s*=\s*\{(.*?)\};",
                   src_nc, re.S)
    if rm:
        registered = set(re.findall(r"&platform_([A-Za-z0-9_]+)", rm.group(1)))
    defines = {}
    for dm in re.finditer(r"^#define\s+([A-Z_][A-Z0-9_]*)\s+\(?\s*(0[xX][0-9a-fA-F]+|[0-9]+)[UuLl]*",
                          src_nc, re.M):
        defines[dm.group(1)] = int(dm.group(2), 0)
    return platforms, registered, defines, default


# -------------------------------------------------------------------- the DTB ---

def dtb_to_dts(path):
    if not shutil.which("dtc"):
        sys.exit("check-port: dtc is not installed (apt install device-tree-compiler)")
    done = subprocess.run(["dtc", "-I", "dtb", "-O", "dts", "-q", path],
                          capture_output=True, text=True)
    if done.returncode != 0 and not done.stdout:
        sys.exit("check-port: dtc cannot read %s: %s" % (path, done.stderr.strip()))
    return done.stdout


def node_body(dts, pos):
    """The body of the node whose "@pos" lies inside it, brace-balanced.

    The GIC node can have child nodes (arm,gic-v3-its on SM8750), so a lazy
    ".*?\};" would stop at the first child and miss the parent's own properties.
    """
    depth, start = 0, None
    for i in range(pos, -1, -1):
        c = dts[i]
        if c == "}":
            depth += 1
        elif c == "{":
            if depth == 0:
                start = i
                break
            depth -= 1
    if start is None:
        return ""
    depth = 0
    for i in range(start, len(dts)):
        if dts[i] == "{":
            depth += 1
        elif dts[i] == "}":
            depth -= 1
            if depth == 0:
                return dts[start + 1:i]
    return dts[start + 1:]


def own_properties(body):
    """body without its child nodes (so a child's reg does not shadow the parent's)."""
    previous = None
    while previous != body:
        previous = body
        body = re.sub(r"\{[^{}]*\}", "", body)
    return body


def cells_of(text):
    return [int(c, 16) for c in text.split()]


def combine_pairs(cells):
    """A DT <...> list of 32-bit cells as values: 1 cell as is, otherwise cells[0]<<32|cells[1]."""
    return cells[0] if len(cells) == 1 else (cells[0] << 32) | cells[1]


def parse_dtb(dts):
    gic = None
    m = re.search(r'compatible\s*=\s*"arm,gic-v3";', dts)
    if m:
        body = own_properties(node_body(dts, m.start()))
        rm = re.search(r"reg\s*=\s*<([^>]*)>", body)
        if rm:
            cells = cells_of(rm.group(1))
            if len(cells) == 4:
                gic = {"dist": cells[0], "dist_size": cells[1],
                       "redist": cells[2], "redist_size": cells[3]}
            elif len(cells) >= 8:
                gic = {"dist": (cells[0] << 32) | cells[1],
                       "dist_size": (cells[2] << 32) | cells[3],
                       "redist": (cells[4] << 32) | cells[5],
                       "redist_size": (cells[6] << 32) | cells[7]}
        if gic is not None:
            sm = re.search(r"redistributor-stride\s*=\s*<([^>]*)>", body)
            # the DT spec leaves the property optional; the hardware default is 128 KB per core
            gic["stride"] = combine_pairs(cells_of(sm.group(1))) if sm else 0x20000
            gic["stride_from_dt"] = bool(sm)
    cpus = []
    for m in re.finditer(r"\n[ \t]*cpu@([0-9a-fA-F]+)[ \t]*\{(.*?)\n[ \t]*\};", dts, re.S):
        body = m.group(2)
        if 'device_type = "cpu"' not in body:
            continue
        rm = re.search(r"reg\s*=\s*<([^>]*)>", body)
        reg = int(m.group(1), 16)
        if rm:
            cells = cells_of(rm.group(1))
            if len(cells) == 1:
                reg = cells[0]
            elif len(cells) >= 2:
                reg = cells[-1] if cells[0] < 0x10000 else (cells[0] << 32) | cells[1]
        cap = re.search(r"capacity-dmips-mhz\s*=\s*<([^>]*)>", body)
        cpus.append({"node": int(m.group(1), 16), "reg": reg,
                     "capacity": int(cap.group(1).split()[0], 16) if cap else None})
    return {"gic": gic, "cpus": cpus}


# ------------------------------------------------------------------- the toml ---

def parse_toml(path):
    sections, current = {}, None
    with open(path, encoding="utf-8", errors="replace") as f:
        for raw in f:
            line = raw.split("#", 1)[0].strip()
            if not line:
                continue
            m = re.match(r"\[(.+)\]$", line)
            if m:
                current = m.group(1).strip()
                sections.setdefault(current, {})
                continue
            m = re.match(r"([A-Za-z0-9_]+)\s*=\s*(.+)$", line)
            if m and current:
                sections[current][m.group(1)] = m.group(2).strip().strip('"')
    return sections


# ---------------------------------------------------------------------- checks ---

def find_dtb(conf, uefi_target):
    """The profile's DTB=, else the copies that ship with the repository.

    mkxnuimg.py falls back to prebuilt/<device>.dtb when DTB= is empty and the UEFI port
    keeps its copy in uefi/files/Resources/DTBs/, so both are legitimate sources.
    """
    if conf.get("DTB"):
        return conf["DTB"]
    for candidate in (os.path.join("prebuilt", "uefi", os.path.basename(uefi_target) + ".dtb"),
                      os.path.join("uefi", "files", "Resources", "DTBs", uefi_target + ".dtb")):
        if os.path.isfile(os.path.join(ROOT, candidate)):
            return candidate
    return ""


def check_device(device, dtb_override=None):
    rep = Report(device)
    conf_path = os.path.join(ROOT, "common", "devices", device + ".conf")
    loader_path = os.path.join(ROOT, "xnuloader", "loader.c")
    print("check-port: %s" % device)
    if not os.path.isfile(conf_path):
        rep.bad("profile exists", "no %s (common/new-device.sh %s writes one)"
                % (os.path.relpath(conf_path, ROOT), device))
        return rep
    conf, comments = parse_conf(conf_path)

    fb_base = parse_number(conf.get("FB_BASE"))
    fd_base = parse_number(conf.get("FD_BASE"))
    fd_size = parse_number(conf.get("FD_SIZE"))
    payload_base = parse_number(conf.get("PAYLOAD_BASE"))
    uefi_target = conf.get("UEFI_TARGET") or device
    dtb_path = dtb_override or find_dtb(conf, uefi_target) or ""

    is_phone = (conf.get("KIND") or "phone").strip().lower() != "qemu"

    # --- the profile itself: leftovers of the porting template -------------------
    todo = []
    for lineno, raw in enumerate(open(conf_path, encoding="utf-8", errors="replace"), 1):
        if re.search(r"\bTODO\b|\bFIXME\b|\bXXX\b", raw):
            todo.append("line %d: %s" % (lineno, raw.strip()))
    if todo:
        rep.bad("profile has no TODO leftovers",
                "; ".join(todo[:4]) + (" ..." if len(todo) > 4 else ""))
    else:
        rep.ok("profile has no TODO leftovers")

    if not is_phone:
        rep.skip("FB_BASE",
                 "KIND=qemu: no phone firmware reports a framebuffer base; the loader"
                 " falls back to platform_qemu_virt")
    elif not fb_base:
        rep.bad("FB_BASE is a real address",
                "FB_BASE=%s -- the loader picks the device by the framebuffer base the UEFI "
                "reports, so 0 identifies nothing" % conf.get("FB_BASE"))
    else:
        rep.ok("FB_BASE is a real address", conf.get("FB_BASE"))

    # --- the platform that describes this device --------------------------------
    platforms, registered, defines, default = parse_loader_platforms(loader_path)
    plat_name, plat = None, {}
    if device in platforms:
        plat_name = device
    elif device.replace("-", "_") in platforms:   # qemu-virt -> platform_qemu_virt
        plat_name = device.replace("-", "_")
    else:
        by_fb = [n for n, f in platforms.items()
                 if fb_base and parse_number(f.get("fb_base")) == fb_base]
        if len(by_fb) == 1:
            plat_name = by_fb[0]
    if plat_name is None:
        rep.bad("xnuloader/loader.c describes this device",
                "no platform_%s and no platform whose fb_base is %s; loader.c has %s"
                % (device, conf.get("FB_BASE"), ", ".join(sorted(platforms)) or "none"))
    else:
        plat = platforms[plat_name]
        rep.ok("xnuloader/loader.c describes this device", "platform_" + plat_name)
        if plat_name in registered:
            rep.ok("the loader can select this platform",
                   "platforms[] -> &platform_" + plat_name)
        elif plat_name == default:
            rep.ok("the loader can select this platform",
                   "it is the default (PLAT = &platform_%s, chosen when no framebuffer base "
                   "matches)" % plat_name)
        else:
            rep.bad("the loader can select this platform",
                    "platform_%s is neither in platforms[] nor the default PLAT, so the "
                    "loader never selects it" % plat_name)

    # --- the kernel side of the same name ----------------------------------------
    # The loader writes its platform name into /arm-io device_type, and the kernel picks its
    # SoC row by that name (redwood_soc(), xnu/files/bsd/dev/redwood_soc.c) from each row's
    # names[] list. A name the kernel does not know falls back to the redwood row silently,
    # so the phone would run with redwood's EPSS/TLMM/SPMI/UFS addresses.
    soc_table = os.path.join(ROOT, "xnu", "files", "bsd", "dev", "redwood_soc.c")
    if plat_name and is_phone and os.path.isfile(soc_table):
        source = open(soc_table, encoding="utf-8", errors="replace").read()
        source = re.sub(r"/\*.*?\*/", " ", source, flags=re.S)
        known = set()
        for row in re.finditer(r"\.names\s*=\s*\{([^}]*)\}", source):
            known.update(re.findall(r'"([^"]+)"', row.group(1)))
        for row in re.finditer(r'^\s*\.name\s*=\s*"([^"]+)"', source, re.M):
            known.add(row.group(1))
        loader_name = re.search(r'"([^"]*)"', plat.get("name") or "")
        label = "the kernel has an SoC row for the name the loader writes"
        if not loader_name:
            rep.skip(label, "platform_%s has no literal .name" % plat_name)
        elif not known:
            rep.skip(label, "no .name/.names rows found in xnu/files/bsd/dev/redwood_soc.c")
        elif loader_name.group(1) in known:
            rep.ok(label,
                   '"%s" is one of the names redwood_soc.c knows (%s)'
                   % (loader_name.group(1), ", ".join(sorted(known))))
        else:
            rep.bad(label,
                   'the loader writes device_type="%s" into /arm-io, but redwood_soc.c knows only %s. '
                   'redwood_soc() falls back to the redwood row for an unknown name, so the phone '
                   'would silently run with redwood\'s EPSS/TLMM/SPMI/UFS addresses'
                   % (loader_name.group(1), ", ".join(sorted(known))))

    # --- 1. fb_base / FD_BASE / FD_SIZE / PAYLOAD_BASE --------------------------
    if plat and is_phone:
        loader_fb = parse_number(plat.get("fb_base"))
        if loader_fb is None:
            rep.bad("FB_BASE == platform.fb_base", "platform_%s has no .fb_base" % plat_name)
        elif loader_fb != fb_base:
            rep.bad("FB_BASE == platform.fb_base",
                    "profile %s vs loader %s -- the device is picked by this value, so the two "
                    "disagree about which phone this is"
                    % (conf.get("FB_BASE"), plat.get("fb_base")))
        else:
            rep.ok("FB_BASE == platform.fb_base", conf.get("FB_BASE"))
        if loader_fb:
            same = [n for n, f in platforms.items() if parse_number(f.get("fb_base")) == loader_fb]
            if len(same) > 1:
                rep.bad("the framebuffer base identifies one device only",
                        "platforms %s all claim fb_base %s"
                        % (", ".join(same), plat.get("fb_base")))
            else:
                rep.ok("the framebuffer base identifies one device only", plat.get("fb_base"))

    if not is_phone:
        rep.skip("PAYLOAD_BASE", "KIND=qemu: there is no UEFI payload container")
    elif "PAYLOAD_BASE" not in defines:
        rep.bad("loader.c defines PAYLOAD_BASE", "no #define PAYLOAD_BASE found")
    elif payload_base is None:
        rep.bad("profile has PAYLOAD_BASE", "PAYLOAD_BASE missing in the profile")
    elif payload_base != defines["PAYLOAD_BASE"]:
        rep.bad("profile PAYLOAD_BASE == loader.c PAYLOAD_BASE",
                "profile %s vs loader %#x" % (conf.get("PAYLOAD_BASE"), defines["PAYLOAD_BASE"]))
    else:
        rep.ok("profile PAYLOAD_BASE == loader.c PAYLOAD_BASE", conf.get("PAYLOAD_BASE"))

    if not is_phone:
        rep.skip("FD_BASE/FD_SIZE and the UEFI boot shim",
                 "KIND=qemu: a computer boots the kernel through QEMU, not fastboot")
    elif fd_base is None or fd_size is None:
        rep.bad("profile has FD_BASE and FD_SIZE",
                "FD_BASE=%s FD_SIZE=%s" % (conf.get("FD_BASE"), conf.get("FD_SIZE")))
    elif fd_size == 0:
        rep.bad("FD_SIZE is not zero", conf.get("FD_SIZE"))
    else:
        rep.ok("profile has FD_BASE and FD_SIZE",
               "%s/%s" % (conf.get("FD_BASE"), conf.get("FD_SIZE")))
        if payload_base is not None and fd_base + fd_size > payload_base:
            rep.bad("the UEFI image does not overlap the payload",
                    "FD %#x..%#x reaches into PAYLOAD_BASE %#x"
                    % (fd_base, fd_base + fd_size, payload_base))
        else:
            rep.ok("the UEFI image does not overlap the payload")
        toml_path = os.path.join(ROOT, "uefi", "files", "Resources", "Configs",
                                 uefi_target + ".toml")
        if not os.path.isfile(toml_path):
            rep.bad("UEFI config for UEFI_TARGET=%s" % uefi_target,
                    "no %s" % os.path.relpath(toml_path, ROOT))
        else:
            t = parse_toml(toml_path).get("uefi_fd", {})
            t_base, t_size = parse_number(t.get("base")), parse_number(t.get("size"))
            if (t_base, t_size) != (fd_base, fd_size):
                rep.bad("profile FD_BASE/FD_SIZE == %s [uefi_fd]"
                        % os.path.basename(toml_path),
                        "toml base=%s size=%s vs profile FD_BASE=%s FD_SIZE=%s"
                        % (t.get("base"), t.get("size"), conf.get("FD_BASE"),
                           conf.get("FD_SIZE")))
            else:
                rep.ok("profile FD_BASE/FD_SIZE == %s [uefi_fd]"
                       % os.path.basename(toml_path),
                       "%s/%s" % (t.get("base"), t.get("size")))

    # --- the device tree: GIC, cores, the io window -----------------------------
    if not is_phone:
        rep.skip("device tree checks", "KIND=qemu: QEMU generates the tree it hands over")
        return finish(rep, device, conf, comments, fb_base)
    if not dtb_path:
        rep.skip("device tree checks", "no DTB= in the profile (and none given with --dtb)")
        return finish(rep, device, conf, comments, fb_base)
    dtb_abs = dtb_path if os.path.isabs(dtb_path) else os.path.join(ROOT, dtb_path)
    if not os.path.isfile(dtb_abs):
        rep.bad("the device tree exists", "%s is not there" % dtb_path)
        return finish(rep, device, conf, comments, fb_base)
    dtb = parse_dtb(dtb_to_dts(dtb_abs))
    dtb_cpus = dtb["cpus"]
    rep.ok("the device tree exists",
           "%s (%d bytes)" % (dtb_path, os.path.getsize(dtb_abs)))

    gic = dtb["gic"]
    if not gic:
        rep.bad("the device tree has an arm,gic-v3 node", "none found in %s" % dtb_path)
    elif not plat:
        rep.skip("the GIC addresses", "no platform to compare with")
    else:
        for field, key in (("gic_dist", "dist"), ("gic_redist", "redist")):
            want, got = gic[key], parse_number(plat.get(field))
            label = "platform.%s == the device tree's arm,gic-v3 %s" % (field, key)
            if got is None:
                rep.bad(label, "platform_%s has no .%s" % (plat_name, field))
            elif got != want:
                rep.bad(label, "loader %#x vs device tree %#x" % (got, want))
            else:
                rep.ok(label, "%#x" % got)

        io_base = parse_number(plat.get("io_base"))
        io_size = parse_number(plat.get("io_size"))
        if not io_base or not io_size:
            rep.bad("io_base/io_size are non-zero",
                    "loader io_base=%s io_size=%s -- XNU reads a zero SoC base as 'no SoC' and "
                    "skips the clock setup" % (plat.get("io_base"), plat.get("io_size")))
        else:
            rep.ok("io_base/io_size are non-zero", "%#x/%#x" % (io_base, io_size))
            lo, hi = io_base, io_base + io_size
            span = [(gic["dist"], gic["dist_size"]), (gic["redist"], gic["redist_size"])]
            outside = ["%#x..%#x" % (a, a + s) for a, s in span if not (lo <= a and a + s <= hi)]
            if outside:
                rep.bad("the io window covers the GIC",
                        "io %#x..%#x does not cover %s" % (lo, hi, ", ".join(outside)))
            else:
                rep.ok("the io window covers the GIC", "%#x..%#x" % (lo, hi))

        # The redistributor frames are a fixed distance apart ("redistributor-stride"); on
        # SM8750 that distance is 0x40000, twice the 0x20000 every earlier SoC used. The
        # loader writes it into /arm-io/gic and gic_v3_irq.c reads it there, so both the
        # loader field and the DT must agree or the kernel walks the wrong frames.
        stride = gic.get("stride")
        stride_label = "platform.gic_redist_stride == the device tree redistributor-stride"
        loader_stride = parse_number(plat.get("gic_redist_stride"))
        how = "from the device tree" if gic.get("stride_from_dt") else "assumed (property absent)"
        if loader_stride is None:
            rep.bad(stride_label,
                    "platform_%s has no .gic_redist_stride; the device tree says %#x (%s)"
                    % (plat_name, stride, how))
        elif loader_stride != stride:
            rep.bad(stride_label,
                    "loader %#x vs device tree %#x (%s). The frames would be walked at the "
                    "wrong distance, so cores past the first would find no redistributor."
                    % (loader_stride, stride, how))
        else:
            rep.ok(stride_label, "%#x (%s)" % (stride, how))

        # ... and the space the loader reserves for the frames has to be big enough for all
        # of them, which is cores * stride and is 2 MB rather than 1 MB on SM8750.
        size_label = "the redistributor region holds every core's frame"
        loader_size = parse_number(plat.get("gic_redist_size"))
        needed = stride * len(dtb_cpus)
        effective = loader_size if loader_size else 0x100000    # the loader default when 0
        if stride and gic["redist_size"] < needed:
            rep.bad(size_label,
                    "the device tree gives the redistributors %#x, but %d cores at %#x apart "
                    "need %#x" % (gic["redist_size"], len(dtb_cpus), stride, needed))
        elif effective < needed:
            rep.bad(size_label,
                    "the loader reserves %#x (gic_redist_size=%s) for %d cores at %#x apart, "
                    "which needs %#x"
                    % (effective, plat.get("gic_redist_size") or "default 0x100000",
                       len(dtb_cpus), stride, needed))
        elif loader_size and loader_size != gic["redist_size"]:
            rep.bad(size_label,
                    "loader gic_redist_size %#x vs the device tree's %#x"
                    % (loader_size, gic["redist_size"]))
        else:
            rep.ok(size_label, "%#x for %d cores at %#x apart" % (gic["redist_size"], len(dtb_cpus), stride))

    cpus = dtb["cpus"]
    if not cpus:
        rep.bad("the device tree has cpu nodes", "none found in %s" % dtb_path)
    elif not plat:
        rep.skip("cores/core_shift", "no platform to compare with")
    else:
        cores = parse_number(plat.get("cores"))
        shift = parse_number(plat.get("core_shift"))
        if cores != len(cpus):
            rep.bad("platform.cores == the number of cpu nodes",
                    "loader %s vs device tree %d (%s)"
                    % (plat.get("cores"), len(cpus),
                       ", ".join(hex(c["node"]) for c in cpus)))
        else:
            rep.ok("platform.cores == the number of cpu nodes", "%d" % cores)
        want_shift = 8 if any((c["reg"] or 0) >= 0x100 for c in cpus) else 0
        if shift != want_shift:
            rep.bad("platform.core_shift matches how MPIDR numbers the cores",
                    "loader %s, device tree wants %d (regs %s)"
                    % (plat.get("core_shift"), want_shift,
                       ", ".join(hex(c["reg"] or 0) for c in cpus)))
        else:
            rep.ok("platform.core_shift matches how MPIDR numbers the cores", "%d" % shift)
        if shift is not None and cores:
            stride = parse_number(plat.get("core_stride"), 0) or 0
            seen = {}
            for c in cpus:
                phys = c["reg"] if c["reg"] is not None else c["node"]
                number = (phys >> shift) & 0xFF
                if stride:
                    number += ((phys >> (shift + 8)) & 0xFF) * stride
                seen.setdefault(number, []).append(phys)
            wanted = set(range(cores)) if cores else set()
            collapsed = {n: v for n, v in seen.items() if len(v) > 1}
            label = "the loader can number every core"
            how = ("core_shift=%d, core_stride=%d" % (shift, stride))
            if collapsed:
                pairs = "; ".join("%d <- %s" % (n, ", ".join(hex(p) for p in v))
                                  for n, v in sorted(collapsed.items()))
                rep.bad(label,
                        "%d device-tree cores collapse to %d core numbers with %s (%s). Two "
                        "clusters whose numbers restart at 0 need core_stride set to the size of "
                        "the lower cluster; with it unset the loader cannot tell them apart, so "
                        "small_cores, and the MPIDRs it builds for PSCI CPU_ON, would both be wrong."
                        % (len(cpus), len(seen), how, pairs))
            elif seen and set(seen) != wanted:
                rep.bad(label,
                        "with %s the device-tree cores get numbers %s, not 0..%d. The kernel "
                        "indexes its topology by these numbers, so a gap or an out-of-range one "
                        "leaves a processor undescribed."
                        % (how, ", ".join(str(n) for n in sorted(seen)), (cores or 1) - 1))
            else:
                rep.ok(label, "%s -> 0..%d" % (how, max(seen) if seen else 0))
            # The other direction: the loader also has to turn a core number back into an MPIDR
            # (core_mpidr(), for PSCI CPU_ON and bootcpu=N). If that inverse lands on an address
            # the device tree does not have, the core is started on nothing.
            if seen and cores and not collapsed:
                phys_of = {}
                for c in cpus:
                    phys = c["reg"] if c["reg"] is not None else c["node"]
                    number = (phys >> shift) & 0xFF
                    if stride:
                        number += ((phys >> (shift + 8)) & 0xFF) * stride
                    phys_of[number] = phys
                wrong = []
                for number in range(cores):
                    if stride:
                        mpidr = ((number // stride) << (shift + 8)) | ((number % stride) << shift)
                    else:
                        mpidr = number << shift
                    if phys_of.get(number) != mpidr:
                        wrong.append("%d -> %#x (device tree has %s)"
                                     % (number, mpidr,
                                        hex(phys_of[number]) if number in phys_of else "no such core"))
                if wrong:
                    rep.bad("every core number turns back into a real MPIDR",
                            "the loader builds MPIDRs from core numbers for PSCI CPU_ON (and for "
                            "bootcpu=N) as number -> (number/stride)<<(shift+8) | (number%%stride)<<shift, "
                            "with %s; that does not invert what the device tree says: %s"
                            % (how, "; ".join(wrong[:6]) + (" ..." if len(wrong) > 6 else "")))
                else:
                    rep.ok("every core number turns back into a real MPIDR",
                           "0..%d round-trip through %s" % (cores - 1, how))
        small = parse_number(plat.get("small_cores"), 0) or 0
        if cores and small & ~((1 << cores) - 1):
            rep.bad("small_cores only names cores that exist", "%#x with cores=%d" % (small, cores))
        else:
            rep.ok("small_cores only names cores that exist", "%#x" % small)
        caps = [c["capacity"] for c in cpus if c["capacity"]]
        if caps and len(set(caps)) > 1 and not small:
            rep.bad("small_cores is set where the device tree has two kinds of core",
                    "capacity-dmips-mhz %s, but small_cores=0"
                    % ", ".join(str(x) for x in sorted(set(caps))))
        elif not caps:
            rep.skip("small_cores against the device tree",
                     "no capacity-dmips-mhz in the DTB (a judgement call)")
        else:
            rep.ok("small_cores is consistent with the device tree's capacities",
                   "capacities %s, small_cores %#x"
                   % (", ".join(str(x) for x in sorted(set(caps))), small))
    return finish(rep, device, conf, comments, fb_base)


def finish_qemu(rep, device, conf):
    """What a QEMU profile has to get right instead of the phone fields."""
    platforms = parse_loader_platforms(
        os.path.join(ROOT, "xnuloader", "loader.c"))[0]
    name = device.replace("-", "_")
    plat = platforms.get(name, {})
    cores = parse_number(plat.get("cores"))
    smp = parse_number(conf.get("SMP"))
    if cores is None:
        rep.skip("SMP == platform.cores", "no platform_%s.cores to compare with" % name)
    elif smp is None:
        rep.skip("SMP == platform.cores", "no SMP= in the profile")
    elif smp != cores:
        rep.bad("SMP == platform.cores",
                "profile SMP=%s vs platform_%s.cores=%s"
                % (conf.get("SMP"), name, plat.get("cores")))
    else:
        rep.ok("SMP == platform.cores", "%d" % smp)
    bootargs = conf.get("BOOTARGS", "")
    m = re.search(r"(?:^|[ \t])cpus=([0-9]+)", bootargs)
    if not m:
        rep.bad("BOOTARGS says how many CPUs the kernel takes", "BOOTARGS=%r" % bootargs)
    elif smp is not None and int(m.group(1)) > smp:
        rep.bad("BOOTARGS cpus= does not exceed SMP",
                "cpus=%s vs SMP=%s" % (m.group(1), smp))
    else:
        rep.ok("BOOTARGS says how many CPUs the kernel takes", "cpus=%s" % m.group(1))
    return rep


def finish(rep, device, conf, comments, fb_base):
    # --- 6. redwood-only boot arguments ----------------------------------------
    bootargs = conf.get("BOOTARGS", "")
    present = [a for a in REDWOOD_ONLY_ARGS
               if re.search(r"(^|\s)%s\s*=" % re.escape(a), bootargs)]
    if not present:
        rep.ok("no redwood-only boot arguments", "BOOTARGS=%r" % bootargs)
    elif device == NATIVE_PROFILE:
        rep.skip("redwood-only boot arguments",
                 "%s is the phone the drivers were written for; %s are its own hardware"
                 % (device, ", ".join(present)))
    else:
        unjustified = [a for a in present
                       if not any(re.search(r"\b%s\b" % re.escape(a), text)
                                  for _, text in comments)]
        if unjustified:
            rep.bad("every redwood-only boot argument is justified in the profile",
                    "%s in BOOTARGS=%r has no comment saying why a %s device may use it"
                    % (", ".join(unjustified), bootargs, device))
        else:
            rep.ok("every redwood-only boot argument is justified in the profile",
                   ", ".join(present))
    return rep


def main(argv):
    ap = argparse.ArgumentParser(
        description="Check a HackiOS device port for internal drift.")
    ap.add_argument("device", nargs="?", help="profile in common/devices/ (e.g. redwood, dodge)")
    ap.add_argument("--dtb", help="use this device tree instead of the profile's DTB=")
    ap.add_argument("--all", action="store_true", help="every profile in common/devices/")
    args = ap.parse_args(argv)

    if args.all:
        devices = sorted(os.path.basename(p)[:-5]
                         for p in glob.glob(os.path.join(ROOT, "common", "devices", "*.conf"))
                         if not os.path.basename(p).startswith("_"))
        if not devices:
            return 2
    elif args.device:
        devices = [args.device]
    else:
        ap.print_usage()
        return 2

    failed = []
    for device in devices:
        rep = check_device(device, args.dtb if len(devices) == 1 else None)
        print("  ----  %d checks, %d failed" % (rep.checks, rep.failures))
        if rep.failures:
            failed.append(device)
        print()
    if failed:
        print("check-port: FAILED: %s" % ", ".join(failed))
        return 1
    print("check-port: OK: %s" % ", ".join(devices))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

# -----------------------------------------------------------------------------
# What this script does not check
#
# * whether the hardware behaves as described. There is no phone here: nothing is
#   flashed, booted or read back. Every number is compared between sources, never
#   against the silicon.
# * the UEFI port itself (uefi/files/Platforms/<vendor>/<target>Pkg): its memory map,
#   its DXE heap, and whether PAYLOAD_BASE is really free inside it. Only the two
#   values the loader and the profile share (FD_BASE/FD_SIZE) are compared, against
#   the boot shim's toml.
# * whether the framebuffer base the *firmware* reports equals FB_BASE: the firmware
#   only prints it at boot ("display W x H at ..."). The profile and the loader
#   agreeing proves they agree with each other, not with the phone.
# * the kernel side (xnu/files/bsd/dev/*.c addresses and boot arguments): not device
#   tree facts, which is why docs/port-sm8750/kernel.md exists.
