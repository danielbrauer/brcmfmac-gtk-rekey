# Upstream GTK recovery RFC

This is an **unsigned draft for human review**, not a submitted or accepted
kernel fix. The code is a standalone port of the scoped Pi recovery, without
the experimental tracing. It does not replace the Pi's deployed module or
change the existing distribution-kernel build/installation path.

Apply the two files listed in `series` in order with `git am`. The
`0000-cover-letter.patch` file is the introductory mail, not an input patch.
The source base is torvalds/linux commit
`893e11787f78e43b534e252249ac3fff4d1333f8` (mainline during 7.3-rc development).
This is a pinned preparation base, not a claim of testing wireless-next.
Before submission, refresh against the appropriate wireless maintainer tree
or a named mainline release and repeat the checks.

1. Expose a separate firmware status for one BSS configuration write. Existing
   callers retain their return convention and the existing protocol lock.
2. Recover only an eligible BCM43430/2, FWID `01-3b307371`, station-mode CCMP
   GTK replacement rejected with firmware `BCME_REPLAY`. Clear the selected
   occupied slot, then retry the exact requested key and receive sequence
   once. Exclude matching cached keys, pairwise/extended keys, other firmware
   and transport failures; propagate clear/retry failures.

The modified kernel files retain their existing `SPDX-License-Identifier:
ISC` headers; additions to those files follow that license. Supporting
scripts and documentation use this repository's GPL-2.0 license. No firmware
binary is included in the series.

## Evidence and checks

The host tests compile extracted kernel functions against recording stubs.
Thirty recovery cases and twelve firmware-status cases pass on this port.
The updated fixture also passes all thirty cases against the older Pi patch.
They test host decisions and error handling, not proprietary firmware internals.

The `Check upstream RFC` workflow builds a minimal complete kernel (`vmlinux`
and modules) from the pinned base, after patch 1, and after patch 2. It uses
separate output directories and covers arm64/module/debug off and
x86-64/built-in/debug on, with SDIO, USB and PCIe enabled. It also runs sparse
and strict compilation on both changed translation units, records stack
usage, compares diagnostics with the base, checks kernel-doc, applies the
mail patches with `git am`, and runs the 42 host cases. The resulting configs,
compiler versions and logs are downloadable workflow artifacts.

[Validation run 34354808438](https://github.com/danielbrauer/brcmfmac-gtk-rekey/actions/runs/34354808438)
passed both configurations on the exact two patches in this directory. GCC
13.3.0 and sparse 0.6.4 built and checked the base and each patch separately.
The modified units compile with `W=1 KCFLAGS=-Werror` and have zero sparse
warnings. Neither patch introduces compiler warnings. The arm64 base's full
`W=1` build has 517 existing `-Woverride-init` warnings in `arch/arm64/kernel/`
(`sys.c` and `traps.c`); this is not a warning-free whole-kernel claim.

Stack checking found no new functions above 512 bytes or increases among
those already above that threshold. On x86-64, `send_key_to_dongle` is 528
bytes both before and after the patches; other reported functions are also
unchanged. Kernel-doc passes. Full checkpatch reports only the missing human
sign-off on each patch. A fresh local `git am` application reproduces the
prepared source exactly and passes `git diff --check`.

Reproduce on a disposable Linux checkout at the exact base with GCC, a matching cross
compiler where needed, make, bc, bison, flex, libelf/libssl development files,
sparse, Perl and Python installed:

```sh
ARCH=arm64 CROSS_COMPILE=aarch64-linux-gnu- DRIVER_MODE=m DRIVER_DEBUG=n \
  bash upstream/check-build.sh /absolute/path/to/disposable-linux
```

`check-build.sh` applies commits and creates a build directory in the supplied
checkout. It never installs modules, changes network state or boots a kernel.
Use a fresh checkout for a new run.

The equivalent scoped Pi backport was runtime tested on
`6.18.39+rpt-rpi-v8`: four rotations completed, including two clear/retry
recoveries, with group traffic after every rotation and no reassociation
before planned rollback. Stock-driver failure recurred after rollback.
2392/2400 ping replies were received; the eight losses cannot be localized to
the recovery events. The mainline port has **not** been run on hardware.
The main README contains the full sanitized findings and test limitations.

## Submission guidance audit

Preparation follows the [wireless submission guide](https://wireless.docs.kernel.org/en/latest/en/developers/documentation/submittingpatches.html),
its [email etiquette](https://www.infradead.org/~dwmw2/email.html), and the pinned
kernel's `Documentation/process/` development-process, coding-style,
submitting-patches, submit-checklist, coding-assistants, generated-content and
threat-model documents. These distinctions must survive revisions:

- Use imperative `wifi: brcmfmac:` titles, one logical change per patch, a
  numbered RFC series and a cover letter. Each commit describes the symptom,
  cause as far as established, behavior, scope and implications independently.
- Generate mail with `git format-patch --cover-letter --base=<base>
  --subject-prefix='RFC PATCH'`. Test application with `git am`. Deliver inline
  plain text through `git send-email`, without HTML, MIME attachment or PGP
  wrapping. Have the human submitter first round-trip mail to themselves and
  verify that the received patches apply intact.
- `scripts/get_maintainer.pl` on both patches identifies Arend van Spriel
  `<arend.vanspriel@broadcom.com>`, `linux-wireless@vger.kernel.org`,
  `brcm80211@lists.linux.dev`, `brcm80211-dev-list.pdl@broadcom.com`, and
  `linux-kernel@vger.kernel.org`. Put linux-wireless in To and the other
  relevant recipients in Cc. Refresh this selection against the submission
  base and recent file history; the preparation checkout has shallow history.
- Both patches pass checkpatch style checks with `--no-signoff`, run from
  the Linux checkout with the mail-patch paths as arguments. Do not run the
  checker from this artifact repository, where Git can identify the patch
  containers as tracked source files. Full
  checkpatch must still report the missing human `Signed-off-by` on each
  patch; that is deliberate, not a clean submission check. The workflow
  asserts that no other full-checkpatch errors or warnings remain.
- AI-assisted work is disclosed in prose and with `Assisted-by: LLM`. Do not
  invent authors, review/test acknowledgments or certification. The kernel's
  coding-assistants guidance says AI agents must not add Signed-off-by tags;
  only the human submitter may review and certify the DCO. These artifacts
  deliberately have no such tag. No mail has been sent by the assistant.
- The introducing Linux commit is unknown. A firmware-dependent symptom does
  not justify fabricating a `Fixes:` tag. Establish attribution if possible,
  or explicitly discuss its absence in the RFC. Do not claim compliance with
  that part of the coding-assistants checklist yet. No speculative stable Cc
  or private/unverified bug-tracker link is included.
- Preserve the existing ISC license headers. No new user ABI, boot/module
  parameter, Kconfig option or documentation-build target is introduced.
  The new driver-internal helper has kernel-doc.
- Publish only the sanitized findings and synthetic tests. No SSID, BSSID,
  LAN address, device hostname, credential, live key or raw packet capture is
  needed in the submission. Public author/maintainer email addresses are
  intentional attribution, not network topology.
- For revisions, increment the series version, resend the complete series and
  put revision notes after `---` or in the cover. Preserve thread references
  for replies, quote selectively, answer below quoted text and retain relevant
  recipients. Track review via wireless Patchwork and respond to feedback.

## Remaining review and validation

This draft is not yet ready for merging. Human code/DCO review, maintainer and
firmware-vendor feedback, final tree selection and refresh, and runtime
validation of the exact submitted series remain. The wider kernel checklist
also includes allmodconfig/allnoconfig builds, driver-disabled coverage,
additional word sizes/endianness, latest linux-next, runtime SMP/preemption and
lockdep configurations, and allocation fault injection. The focused workflow
above does not claim to complete those checks.

The current evidence supports an ordinary interoperability/reliability bug:
repeated disconnection during normal GTK rotation, without a demonstrated
security-boundary violation. That is an assessment for the human reporter to
review, not proof of the absence of vulnerabilities. Independently, the
workaround clears firmware key state, so replay-resistance testing and vendor
review matter. The host cache cannot rule out historical key reuse or prove
firmware replay-state correctness. Do not describe this as a general replay
bypass, a proven security fix, or guaranteed lossless recovery. Reassess the
reporting route if evidence of a security-boundary violation emerges.
