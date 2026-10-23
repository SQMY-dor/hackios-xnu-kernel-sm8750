/*
 * Which SoC this kernel is running on, and the numbers that differ between them.
 *
 * The drivers in this tree are named after the first phone they ran on (the POCO X5 Pro,
 * "redwood", SM7325), and most of them are ordinary Qualcomm sub-system drivers with that
 * phone's addresses in them. A second phone (the OnePlus 13, "dodge", SM8750 = Snapdragon
 * 8 Elite, Qualcomm's "Pakala") needs some of those numbers changed and most of them the same.
 *
 * THE MECHANISM, and why this one
 * ------------------------------
 * One table, one discriminator, one fallback:
 *
 *   - The discriminator is the device tree's /arm-io "device_type". xnuloader writes it from
 *     the name of the row of its own platform table that it picked for the phone in front of
 *     it (xnuloader/loader.c:3232, dt_prop_str(&w, "device_type", plat->name)), so the kernel
 *     and the loader cannot disagree, no boot-arg has to be kept in step with the hardware,
 *     and a device the loader learns about later needs no kernel change to be identified.
 *     (The same node is already how this kernel finds its interrupt controller: "reg" of
 *     /arm-io/gic, osfmk/arm64/gic_v3_irq.c:428-434.)
 *   - redwood_socs[0] ("redwood") is also the fallback: an absent /arm-io, an absent property,
 *     an error from the device tree, or a name no row has all give the redwood row, which is
 *     what this kernel did before this file existed. Running on redwood is therefore unchanged
 *     -- the constants below are the same literals the drivers had.
 *   - A number that is the same on every SoC we know stays where it was, in the driver that
 *     uses it; only numbers that differ (or that must stay off until somebody confirms them)
 *     live here. That keeps the table small enough to be read in one go.
 *
 * What does NOT need to be here (checked, listed so nobody looks for it twice):
 *   - the interrupt controller: the kernel reads it from /arm-io/gic, and the loader fills that
 *     node from its own platform row (gic_dist/gic_redist), so it follows the SoC by itself;
 *   - the processor count and numbering: also from the device tree the loader writes (the
 *     "reg" of each /cpus/cpu@N) -- but see redwood_soc_core() below for how a core's number is
 *     taken out of it, which does differ;
 *   - MMIO windows the loader maps for us (its io_base/io_size), the payload and framebuffer
 *     addresses: the loader's business (xnuloader/loader.c).
 *
 * Sources for the SM8750 numbers: docs/port-sm8750/FACTS.md (from the phone's own vendor
 * device tree, Mu-Silicium Platforms/OnePlus/dodgePkg/FdtBlob/sm8750-oneplus-dodge.dtb) and
 * mainline arch/arm64/boot/dts/qcom/sm8750.dtsi. Each row says which.
 */
#ifndef _SYS_REDWOOD_SOC_H_
#define _SYS_REDWOOD_SOC_H_

#include <stdint.h>

/* Enough core numbers for both phones: 8 cores on redwood, 6 + 2 in two clusters on SM8750. */
#define REDWOOD_SOC_MAX_CORES   16
#define REDWOOD_SOC_MAX_DOMAINS 4      /* EPSS domains we would ever raise (redwood: 3) */
#define REDWOOD_SOC_NO_DOMAIN   0xff    /* epss_domain_of[]: this core does not belong to a domain we raise */

struct redwood_soc {
	/*
	 * The names this SoC may be called in /arm-io "device_type", the first being its own; a name
	 * later in the list is an alias the loader is free to use (the loader's name for a device is
	 * the loader's to choose, so this side accepts the spellings that would mean this SoC rather
	 * than insisting on one). NULL ends the list.
	 */
	const char *    names[4];
	const char *    name;                   /* names[0], for the log */

	/*
	 * EPSS: the hardware that holds a cluster's frequency/voltage table, one block per cluster
	 * (Linux drivers/cpufreq/qcom-cpufreq-hw.c). epss_base is domain 0's block; a domain's is
	 * epss_base + domain * epss_domain_size. epss_domains == 0: the addresses are not verified
	 * for this SoC, and nothing may be written there.
	 */
	uint64_t        epss_base;
	uint32_t        epss_domain_size;
	uint32_t        epss_domains;
	uint8_t         epss_domain_of[REDWOOD_SOC_MAX_CORES];  /* core number -> domain; 0xff: none */

	/*
	 * How a core's number comes out of its MPIDR (the device tree's "reg" is the MPIDR):
	 *   number = ((mpidr >> core_shift) & 0xff) + ((mpidr >> (core_shift + 8)) & 0xff) * core_stride
	 * core_stride == 0: the affinity level above the core's is not a cluster (every core has its
	 * own number in one field), which is how redwood is numbered.
	 */
	uint32_t        core_shift;
	uint32_t        core_stride;

	uint64_t        ufshc_phys;             /* the UFS host controller's registers */

	/*
	 * The application processor's RPMh block ("RSC": the command slots a vote goes through) and
	 * the command database in memory (cmd-db: the names of the resources votes name). 0: the
	 * addresses are not known for this SoC, and the memory-bandwidth vote must not be made.
	 */
	uint64_t        rsc_phys;
	uint32_t        rsc_size;
	uint64_t        cmd_db_phys;
	uint32_t        cmd_db_size;

	/*
	 * The PMIC arbiter (SPMI), version 5: three windows, plus which peripheral each key is on.
	 * A peripheral's id is (slave << 8 | its register base >> 8), as in the arbiter's channel
	 * table; registers within it are offsets from that base.
	 */
	uint64_t        spmi_core_phys;
	uint32_t        spmi_core_size;
	uint64_t        spmi_cnfg_phys;
	uint32_t        spmi_cnfg_size;
	uint64_t        spmi_observer_phys;
	uint32_t        spmi_observer_size;
	uint16_t        spmi_pon_id;            /* the power-on block: power, and volume down with it */
	const char *    spmi_pon_name;
	uint16_t        spmi_pin_id;            /* the PMIC GPIO the volume-up key pulls low */
	const char *    spmi_pin_name;

	/*
	 * Not used by a driver yet; here so the next one to need them does not have to re-derive
	 * them, and so that they are on record as checked for both phones.
	 */
	uint64_t        tlmm_phys;              /* the pin controller (GPIO) */
	uint32_t        tlmm_size;
	uint64_t        gcc_phys;               /* the clock controller */
	uint64_t        gic_dist;               /* for reference only: the kernel reads /arm-io/gic */
	uint64_t        gic_redist;
};

/* The row for this machine; never NULL (redwood's if the device tree does not say). */
const struct redwood_soc * redwood_soc(void);

/* A core's number, from its MPIDR / device tree "reg" (see core_shift/core_stride above). */
static inline uint32_t
redwood_soc_core(const struct redwood_soc *soc, uint32_t phys_id)
{
	return ((phys_id >> soc->core_shift) & 0xff) +
	       (((phys_id >> (soc->core_shift + 8)) & 0xff) * soc->core_stride);
}

/* Which of the SoC's EPSS domains that core is in, or REDWOOD_SOC_NO_DOMAIN. */
static inline uint32_t
redwood_soc_domain(const struct redwood_soc *soc, uint32_t phys_id)
{
	uint32_t core = redwood_soc_core(soc, phys_id);

	return core < REDWOOD_SOC_MAX_CORES ? soc->epss_domain_of[core] : REDWOOD_SOC_NO_DOMAIN;
}

#endif /* _SYS_REDWOOD_SOC_H_ */
