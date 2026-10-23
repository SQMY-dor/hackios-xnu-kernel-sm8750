/*
 * The per-SoC table behind sys/redwood_soc.h: the rows, and the one function that picks between
 * them. See that header for the mechanism and for why /arm-io "device_type" is the discriminator.
 */
#include <libkern/libkern.h>
#include <pexpert/device_tree.h>
#include <pexpert/pexpert.h>
#include <stdbool.h>
#include <sys/redwood_soc.h>

/*
 * Where the loader says what this machine is. The path and the property are the ones
 * osfmk/arm64/gic_v3_irq.c already relies on for the interrupt controller.
 */
#define REDWOOD_SOC_NODE        "/arm-io"
#define REDWOOD_SOC_PROPERTY    "device_type"

/*
 * POCO X5 Pro, SM7325 -- the phone this tree was written on. Every number here is the literal
 * the driver that uses it had before this table existed, so that running on redwood is
 * unchanged.
 */
static const struct redwood_soc redwood_soc_redwood = {
	.names = { "redwood" },
	.name = "redwood",

	.epss_base = 0x18591000ULL,             /* bsd/dev/redwood_cpufreq.c: EPSS_PHYS (sc7280) */
	.epss_domain_size = 0x1000,             /* EPSS_DOMAIN_SIZE */
	.epss_domains = 3,                      /* EPSS_DOMAINS */
	/* domain_of(): A55s (0-3) on domain 0, A78s (4-6) on 1, core 7 on 2. */
	.epss_domain_of = { 0, 0, 0, 0, 1, 1, 1, 2, REDWOOD_SOC_NO_DOMAIN, REDWOOD_SOC_NO_DOMAIN,
	    REDWOOD_SOC_NO_DOMAIN, REDWOOD_SOC_NO_DOMAIN, REDWOOD_SOC_NO_DOMAIN, REDWOOD_SOC_NO_DOMAIN,
	    REDWOOD_SOC_NO_DOMAIN, REDWOOD_SOC_NO_DOMAIN },

	.core_shift = 8,                        /* MPIDR's second affinity field; one cluster */
	.core_stride = 0,

	.ufshc_phys = 0x1d84000ULL,             /* bsd/dev/redwood_ufshc.c: UFSHC_PHYS */

	.rsc_phys = 0x18220000ULL,              /* bsd/dev/redwood_cpufreq.c: RSC_PHYS */
	.rsc_size = 0x10000,
	.cmd_db_phys = 0x80860000ULL,           /* CMD_DB_PHYS */
	.cmd_db_size = 0x20000,

	.spmi_core_phys = 0x0c440000ULL,        /* bsd/dev/redwood_buttons.c: ARB_CORE_PHYS */
	.spmi_core_size = 0x1100,
	.spmi_cnfg_phys = 0x0c40a000ULL,        /* ARB_CNFG_PHYS */
	.spmi_cnfg_size = 0x1000,
	.spmi_observer_phys = 0x0e600000ULL,    /* ARB_OBSERVER_PHYS */
	.spmi_observer_size = 0x10000,
	.spmi_pon_id = 0x013,                   /* slave 0, registers 0x1300: the PMK8350's PON */
	.spmi_pon_name = "the PMK8350's power-on block",
	.spmi_pin_id = 0x18d,                   /* slave 1, registers 0x8d00: GPIO6 of the PM7325 */
	.spmi_pin_name = "GPIO6 of the PM7325",

	.tlmm_phys = 0x0f100000ULL,             /* bsd/dev/redwood_goodix.c and five more */
	.tlmm_size = 0x100000,
	.gcc_phys = 0x00100000ULL,              /* redwood_goodix.c: GCC_PHYS */
	.gic_dist = 0x17A00000ULL,              /* xnuloader platform_redwood */
	.gic_redist = 0x17A60000ULL,
};

/*
 * OnePlus 13, SM8750 "Snapdragon 8 Elite" (Qualcomm "Pakala").
 *
 * The vendor device tree has 8 cores: cpu@0/cpu@100/.../cpu@500 (cluster 0, six cores) and
 * cpu@10000/cpu@10100 (cluster 1, the two fastest). So a core's number is its second affinity
 * field plus the third one times 6 -- redwood's single-field numbering would give the last two
 * cores the numbers 0 and 1 again.
 *
 * The PMIC side is the same arbiter version 5 and, from the vendor DT, the same kind of PON as
 * redwood's (qcom,pmk8350-pon at slave 0, registers 0x1300, pwrkey = KPDPWR, resin = volume
 * down), so the register layout of redwood_buttons.c is expected to hold; what is new is that
 * the PMICs are the pm8550/pm8550ve/pmih0108/pm8010 family, and that the only volume key in the
 * DT is volume-down on PM8550 GPIO6 (pinctrl state "volume-down-n-state"), which is what
 * spmi_pin_id says. Volume up is not in the DT at all -- see docs/port-sm8750/kernel.md.
 */
static const struct redwood_soc redwood_soc_sm8750 = {
	/* xnuloader's platform row for the OnePlus 13 says "dodge"; the SoC's own names are here too,
	 * so that a loader row named after the SoC (or named "pakala", Qualcomm's family name for it)
	 * is recognised as the same thing. */
	.names = { "dodge", "sm8750", "pakala" },
	.name = "dodge",

	/*
	 * UNVERIFIED, and the reason cpufreq stays off on this phone: SM8750 has no cpufreq/EPSS
	 * node in mainline (patches still on the list) and none in the vendor DT. These are its
	 * generation's siblings' addresses (eliza 0x17D91000, milos 0x17D92000, sar2130p
	 * 0x17D93000: three domains 0x1000 apart, qcom,cpufreq-epss), assumed to be what SM8750
	 * has. One read of these three blocks on hardware -- or one line of a Linux boot on the
	 * same phone -- settles it; until then nothing writes them: epss_domains = 0.
	 */
	.epss_base = 0x17D91000ULL,
	.epss_domain_size = 0x1000,
	.epss_domains = 0,
	/* The likely split if the addresses above are right: the six-core cluster, then the two
	 * prime cores. Kept beside the addresses it belongs with, harmless while epss_domains is 0. */
	.epss_domain_of = { 0, 0, 0, 0, 0, 0, 1, 1, REDWOOD_SOC_NO_DOMAIN, REDWOOD_SOC_NO_DOMAIN,
	    REDWOOD_SOC_NO_DOMAIN, REDWOOD_SOC_NO_DOMAIN, REDWOOD_SOC_NO_DOMAIN, REDWOOD_SOC_NO_DOMAIN,
	    REDWOOD_SOC_NO_DOMAIN, REDWOOD_SOC_NO_DOMAIN },

	.core_shift = 8,                        /* as redwood: the number is in the second field */
	.core_stride = 6,                       /* the third field (cluster) counts cores 0-5, 6-7 */

	.ufshc_phys = 0x1d84000ULL,             /* ufs@1d84000, qcom,sm8750-ufshc: same as redwood */

	/*
	 * UNKNOWN, so 0: neither the RSC's address nor where the command database is was verified for
	 * SM8750 (SM8750's rpmh is not in the vendor DT this tree could read, and cmd-db is placed by
	 * the firmware at run time). The memory-bandwidth vote (ddr=1/2) therefore does not happen on
	 * this phone -- which is also what the boot args ask for in milestone 1. See kernel.md.
	 */
	.rsc_phys = 0,
	.rsc_size = 0,
	.cmd_db_phys = 0,
	.cmd_db_size = 0,

	/*
	 * spmi@c400000, qcom,spmi-pmic-arb, reg-names core/chnls/obsrvr/intr/cnfg. The vendor DT
	 * gives the five windows in the order core 0xc400000+0x3000, chnls 0xc500000+0x400000,
	 * obsrvr 0xc440000+0x80000, intr 0xc4c0000+0x10000, cnfg 0xc42d000+0x4000. redwood_buttons.c
	 * reads "core" through the arbiter's version/channel registers and "cnfg" through the owner
	 * table, and both of those are in the 0x3000 before 0xc403000 and in the 0x4000 from
	 * 0xc42d000 -- the same two windows it uses today, at this SoC's addresses. The observer
	 * window here is per-system like redwood's (0x80000 / 8 systems = 0x10000 each), and
	 * qcom,ee = 0 in the DT, as ARB_SYSTEM = 0 assumes.
	 */
	.spmi_core_phys = 0x0c400000ULL,
	.spmi_core_size = 0x3000,
	.spmi_cnfg_phys = 0x0c42d000ULL,
	.spmi_cnfg_size = 0x4000,
	.spmi_observer_phys = 0x0c440000ULL,
	.spmi_observer_size = 0x10000,
	.spmi_pon_id = 0x013,                   /* pmic@0 (pm8550) pon@1300, qcom,pmk8350-pon */
	.spmi_pon_name = "the PM8550's power-on block",
	.spmi_pin_id = 0x18d,                   /* pmic@1 (pm8550) gpio@8800, GPIO6: volume down */
	.spmi_pin_name = "GPIO6 of the PM8550",

	.tlmm_phys = 0x0f100000ULL,             /* pinctrl@f100000, qcom,sm8750-tlmm: same as redwood */
	.tlmm_size = 0x102000,                  /* its reg (redwood's was 0x100000) */
	.gcc_phys = 0x00100000ULL,              /* clock-controller@100000, qcom,sm8750-gcc */
	.gic_dist = 0x16000000ULL,              /* arm,gic-v3: the kernel reads /arm-io/gic */
	.gic_redist = 0x16080000ULL,
};

static const struct redwood_soc *const redwood_socs[] = {
	&redwood_soc_redwood,
	&redwood_soc_sm8750,
};

/* REDWOOD_SOC_PROPERTY of REDWOOD_SOC_NODE, as a NUL-terminated string; false if it is not there. */
static bool
soc_name(char *name, unsigned int size)
{
	DTEntry entry;
	void const *prop;
	unsigned int prop_size;

	if (SecureDTLookupEntry(NULL, REDWOOD_SOC_NODE, &entry) != kSuccess ||
	    SecureDTGetProperty(entry, REDWOOD_SOC_PROPERTY, &prop, &prop_size) != kSuccess ||
	    prop_size == 0 || prop_size > size) {
		return false;
	}
	memcpy(name, prop, prop_size);
	name[size - 1] = 0;                     /* (the loader writes one, but do not trust a size) */
	return name[0] != 0;
}

/*
 * Looked up once, on the first call: a driver asks for this from wherever it happens to start,
 * and the answer cannot change under it. Before the device tree is available (nothing here runs
 * that early) the redwood row is the answer, as it is for a name no row has.
 */
const struct redwood_soc *
redwood_soc(void)
{
	static const struct redwood_soc *chosen;

	if (chosen == NULL) {
		char name[32] = { 0 };
		const struct redwood_soc *found = &redwood_soc_redwood;

		if (soc_name(name, sizeof(name))) {
			for (unsigned int i = 0; i < sizeof(redwood_socs) / sizeof(redwood_socs[0]) && found == &redwood_soc_redwood; i++) {
				for (unsigned int n = 0; n < sizeof(redwood_socs[i]->names) / sizeof(redwood_socs[i]->names[0]) &&
				    redwood_socs[i]->names[n] != NULL; n++) {
					if (strcmp(name, redwood_socs[i]->names[n]) == 0) {
						found = redwood_socs[i];
						break;
					}
				}
			}
		}
		chosen = found;
	}
	return chosen;
}
