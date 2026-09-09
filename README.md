# brcmfmac GTK rekey experiments

Experimental Linux `brcmfmac` instrumentation and a narrowly scoped recovery
for repeated CCMP group-key installation on a Raspberry Pi Zero 2 W.

The observed failure is a successful first group rekey followed by rejection
when a previously used GTK index is reused. This repository tests whether the
open-source host driver can diagnose or recover that condition. It does not
modify the proprietary Wi-Fi firmware.

## Targets

- Kernel ABI: `6.18.39+rpt-rpi-v8`
- Raspberry Pi package version: `6.18.39-1+rpt1`
- Driver: `brcmfmac`, SDIO station mode

CI downloads the archived Raspberry Pi source and headers for that exact
package, verifies their SHA-256 digests, and produces two modules:

- `trace`: records key index, cipher, group/pairwise classification, sequence
  length, whether the driver's key slot was already occupied, whether a CCMP
  GTK matches the cached key, and whether the supplied receive sequence is
  zero. Only boolean comparisons are logged, never key or sequence bytes.
- `retry`: includes the trace and recovers only an exact `BCME_REPLAY`
  rejection of an eligible changed CCMP group key on BCM43430 revision 2,
  firmware build `01-3b307371` (9.88.4.77), in station mode. It clears the
  selected slot using the existing deletion representation and retries once.

Neither variant logs key bytes, credentials, SSIDs, BSSIDs, MAC addresses, IP
addresses, or other network configuration.

## Status

Research prototype. A live `trace` test reproduced failure when an occupied
GTK slot was reused. A subsequent stock-driver probe identified the firmware
rejection as **`BCME_REPLAY` (-51)**. An expanded trace then reproduced it with
a changed key and an advancing EAPOL-Key Replay Counter, strongly suggesting
a false replay rejection during replacement.

The current scoped patch from `573d3dd` completed **four group rotations
without reassociation**, recovering two `BCME_REPLAY` rejections while group
traffic continued. It matches the exact firmware error, chip/revision/build
and interface type, and excludes matches across all cached CCMP keys. The
earlier, broader prototype separately completed five rotations. Artifacts
and results for both runs are identified below.

These tests demonstrate a workaround on the tested configuration, not a
general fix or complete replay-security validation. Each local timer restored
stock afterward, and normal rekey failures resumed. No permanent installation
was made; temporary loaders and probes were removed, and observers finished.

The bounded test loaders restore the distribution driver. The explicit
persistent installer below can instead retain the exact tested artifact
across reboots, while preserving the distribution module for removal.

## Investigation and mitigation

### Problem and scope

The investigation began with unreliable connectivity on a Raspberry Pi Zero
2 W used for local device control. Wi-Fi interruptions can make application
services appear unresponsive; recovery reboots can also interrupt a separate
Ethernet link. These are distinct failure layers, so a Wi-Fi finding alone
does not explain every application or Ethernet symptom.

The specific failure studied here is a WPA2 CCMP group-key refresh (GTK
rekey). Initial connection succeeds, but a later key installation fails and
the host supplicant disconnects locally. Access-point-dependent behavior
motivated testing key installation directly rather than inferring the cause
from signal strength or connection quality.

The tested target uses BCM43430/2 firmware version `9.88.4.77`, dated
2022-03-31. The firmware is proprietary and remains unchanged. This project
modifies only the open-source Linux host-driver module, built against the
exact installed kernel ABI; it does not require replacing the whole kernel.

### What the trace established

With the normal module options preserved, the live trace recorded this
sequence during one association:

| Event | Key index | Driver slot already occupied | Result |
| --- | --- | --- | --- |
| Initial pairwise key | 0 | No | Installed |
| Initial group key | 2 | No | Installed |
| First group rekey | 1 | No | Installed |
| Second group rekey | 2 | Yes | Key addition failed, followed immediately by a local disconnect |

Reconnection subsequently installed keys again. The trace changes logging
only, so it reproduced the original behavior without applying the proposed
recovery.

This is evidence that failure coincides with reuse of an occupied group-key
slot. Occupancy here is the **driver's bookkeeping**, not a direct inspection
of the firmware's internal key table. This first experiment did not establish
why the firmware rejects the request, whether key contents or sequence state
matter, or whether clearing the slot will recover it.

The expanded trace adds `same_ccmp_key` (comparison with the old host-cached
slot before overwriting it) and `seq_zero` (true only for a supplied six-byte
all-zero sequence). Those fields were absent from the first trace above;
their live results appear below. The latter does not inspect the firmware's
live receive counter.

### Stock-driver result: firmware replay rejection

On 2026-09-08, targeted kprobes captured the following sequence on the
distribution driver, with debug mask zero and no module reload or Wi-Fi
configuration change. Times are local (UTC+02:00):

| Event | Time | Key index | Result |
| --- | --- | --- | --- |
| First observed group rekey | 16:29:19 | 2 | Key operation returned 0; supplicant reported success |
| Next group rekey | 16:39:19 | 1 | Firmware returned -51; host key operation returned -52 |
| Reconnection | About 0.76 seconds later | Pairwise 0, group 1 | Both key operations returned 0 |

The same supplicant task entered group-key installation, received the firmware
error about one millisecond later, and returned -52. The exact kernel source's
[`fwil.c` error table](https://github.com/torvalds/linux/blob/master/drivers/net/wireless/broadcom/brcm80211/brcmfmac/fwil.c)
maps -51 to `BCME_REPLAY`; `brcmf_fil_cmd_data` translates
negative firmware status to `-EBADE` (-52). This is a firmware replay rejection
during key installation, not evidence of an operation timing out. Routine
NetworkManager requests separately returned -23 (`BCME_UNSUPPORTED`); those
were distinguishable by task and were not the failing GTK installation.

A simultaneous one-ping-per-second gateway check received 329 of 330 replies,
with one missing reply around the rekey interruption. This checks unicast
reachability, not group-key decryption. The bounded probe finished and removed
its events and trace instance; the stock driver, debug mask zero, and existing
control/watchdog services were verified afterward.

The baseline used firmware `9.88.4.77`, kernel `6.18.39+rpt-rpi-v8`,
`wpa_supplicant` package `2:2.10-24`, WPA2-PSK with CCMP pairwise and group
ciphers, power saving off, and a sampled signal of -30 dBm. Earlier in this
same stock boot the failing group index was 2; after a new association it was
1. A defect unique to numeric slot 2 therefore does not explain the logs.

`BCME_REPLAY` narrows the firmware's reason but does not prove that an incoming
EAPOL frame was replayed, that the access point reused key bytes, or that the
firmware's decision was correct. The stock probe fetched neither key bytes
nor sequence values. The expanded trace below addresses key identity and
handshake freshness; retained firmware state remains unobservable.

An earlier hot-swap run accidentally omitted the normal `roamoff=1` and
`feature_disable=0x282000` options. It associated, then roamed and suffered a
firmware crash; the watchdog rebooted it into stock. That run changed more
than the instrumentation and cannot isolate the trace patch's effect. Both
loading paths now preserve the installed module options, and CI checks that
forwarding remains in place.

### Changed-key result: no observed handshake replay

The expanded trace-only module from commit `778755c` reproduced the failure
on 2026-09-08 with the normal module options preserved. A passive EAPOL prefix
observer and firmware-return probes ran alongside it. Times are UTC+02:00:

| Event | Time | GTK index | Occupied | Matches old cached key | Supplied receive sequence | Result |
| --- | --- | --- | --- | --- | --- | --- |
| Initial installation | 16:50:44 | 2 | No | N/A | Nonzero | Installed |
| First group rekey | 16:59:19 | 1 | No | N/A | Zero | Installed |
| Second group rekey | 17:09:19 | 2 | Yes | **No** | Zero | **BCME_REPLAY (-51)** |
| Reconnection | 17:09:27 | 2 | No | N/A | Zero | Installed |

The second group's EAPOL-Key Replay Counter was **greater** than the first
group's, within the same observed association. Both group messages carried
zero Key RSC; equality of those receive-sequence fields does not mean equality
of handshake replay counters or key bytes. The failing driver call reported
`replacing=1 same_ccmp_key=0 seq_len=6 seq_zero=1`. In the same supplicant task,
the firmware returned -51 about 1.1 ms after entry; the host returned -52.
The supplicant reported failure to install the GTK and disconnected. Key
installation succeeded again about eight seconds later during reconnection.

This rules out repetition of the old slot's cached key and an unchanged or
decreasing handshake counter between the two observed group requests. The
observer started after association and does not authenticate frames itself;
the request reaching the driver's installation path also matters, because
[wpa_supplicant 2.10](https://w1.fi/releases/wpa_supplicant-2.10.tar.gz)
checks handshake freshness and MIC before that path (`src/rsn_supp/wpa.c`).
The comparison is against the host cache, not all historical keys or the
firmware's private table. It does not prove every access-point field correct.

The strongest current explanation is a false replay rejection when a new
GTK replaces an old slot whose earlier receive sequence was nonzero. Whether
the firmware retains stale per-slot state, or the host's replacement command
fails to express the required transition, remains unproven. Reusing a Key ID
and supplying zero receive state for a fresh unused key are permitted; see
the specification discussion below. No clear-and-retry recovery was active.

### Bounded retry result

The retry artifact built from `55d1ffa` was loaded with the serialized loader
from `8d8a68b`, unchanged firmware, and normal module options. Its SHA-256 is
`6a7dca0c02c2e15c6373b950a8cd6fe6588949b27430785e77f3c4a16145d8c6`.
The candidate associated at 23:33:24 on 2026-09-08; all times below are
UTC+02:00, with the last two rotations on 2026-09-09.

| Group rotation | Time | Index | Occupied | Result |
| --- | --- | --- | --- | --- |
| First | 23:34:37 | 2 | No | Direct install succeeded |
| Second | 23:44:37 | 1 | Yes | BCME_REPLAY; clear succeeded; retry succeeded |
| Third | 23:54:37 | 2 | Yes | Direct replacement succeeded |
| Fourth | 00:04:37 | 1 | Yes | BCME_REPLAY; clear succeeded; retry succeeded |
| Fifth | 00:14:37 | 2 | Yes | Direct replacement succeeded |

Both recovered requests contained a changed CCMP key and a supplied zero
receive sequence. Firmware returned -51 and the host -52 before each clear;
clear and retry each returned 0. Each complete add/clear/retry sequence took
about 3.1 ms. The supplicant reported all five rekeys complete. No reconnect
or firmware crash occurred during the test; the only disconnect was the
planned stock-restoration shutdown at 00:18:26.

The EAPOL observer began after the first rotation. Its next observed group
request established the baseline, and all three subsequent replay counters
increased in that same observed session. All four observed requests carried
zero Key RSC. The observer recorded no new pairwise handshake during the run.

A local-gateway check received **2,100 of 2,100 replies (0% loss)**, spanning
both recovery events and the intervening direct replacement. It finished at
00:13:56, so it does not cover the fifth rotation. The passive Ethernet-header
observer continued until 00:16:39 and confirmed group delivery after that
rotation too. Counts below exclude windows that straddle a rotation; reporting intervals
are about 30 seconds, with a shorter final interval at observer shutdown:

| After rotation | Measurement windows | Broadcast frames | Multicast frames |
| --- | --- | --- | --- |
| Second, recovered | 19 | 578 | 674 |
| Third, direct | 19 | 586 | 471 |
| Fourth, recovered | 19 | 582 | 421 |
| Fifth, direct | 4 | 117 | 148 |

These results demonstrate sustained delivered group traffic, not an over-the-
air replay-resistance test. The host-function harness separately verifies the
retry exclusions and receive-state preservation using synthetic keys and a
recording firmware stub. Neither establishes the proprietary firmware's
complete security behavior.

The rejection stayed with the association's initial GTK slot, which initially
received a nonzero sequence. It recurred in that slot even after clear/retry
had successfully installed a zero-sequence key. The other occupied slot
accepted replacements directly. Thus occupancy alone is insufficient, and
clearing did not permanently normalize the initially affected slot. The
firmware state responsible remains unknown; numeric slot 1 is not inherently
special, because earlier associations failed on slot 2.

The local timer cleaned up and rebooted at 00:18. Stock-driver rekey failures
resumed at 00:34:37 and repeated every twenty minutes. Verification the next
morning found stock loaded, normal options, power saving off, services active,
and no test loader, probes or running observers. Loss of the remote observer's
SSH access overnight was not a Pi disconnect: the Pi's local logs preserve the
uninterrupted candidate association and full test results.

### Scoped-patch live result

The narrowed patch from `573d3dd` was tested on 2026-09-09 with the same
BCM43430/2 firmware build `01-3b307371`, exact kernel ABI, normal module
options and power saving off. The candidate's SHA-256 is
`13421cc55747df027a15a5d373d3ca1bce6a45179a682952f2db3a80cefdbf3c`.
It associated at 11:08:00, initially installing GTK index 1 with a nonzero
receive sequence. Times are UTC+02:00.

| Group rotation | Time | Index | Occupied | Result |
| --- | --- | --- | --- | --- |
| First | 11:16:09 | 2 | No | Direct install succeeded |
| Second | 11:26:09 | 1 | Yes | BCME_REPLAY; clear succeeded; retry succeeded |
| Third | 11:36:09 | 2 | Yes | Direct replacement succeeded |
| Fourth | 11:46:09 | 1 | Yes | BCME_REPLAY; clear succeeded; retry succeeded |

Both recovered requests contained a changed key and supplied zero receive
sequence. In the same supplicant task, the firmware returned -51 and the first
key operation returned -52; clear and retry each returned 0. The complete
sequences took about 3.5 ms and 3.1 ms respectively. The supplicant reported
all four rekeys complete. No reassociation or firmware crash occurred during
the candidate connection; its only disconnect was the planned rollback
shutdown at 11:52:55.

The passive EAPOL observer recorded four group requests in one observed
session. The first established its replay-counter baseline, and all three
subsequent counters increased. All four carried zero Key RSC, and no new
pairwise handshake was observed. The firmware trace retained all 412 written
events through its scheduled finish at 11:48:52.

A gateway check spanning all four rotations received **2,392 of 2,400 replies
(0.33% loss)** and finished at 11:48:55. Its aggregate-only output does not
locate the eight missing replies relative to rekeys, so it cannot establish
that recovery was lossless or caused those losses. The passive group observer
continued through 11:48 and recorded delivered traffic after every rotation:

| After rotation | Measurement windows | Broadcast frames | Multicast frames |
| --- | --- | --- | --- |
| First, direct | 19 | 570 | 346 |
| Second, recovered | 19 | 585 | 784 |
| Third, direct | 19 | 580 | 281 |
| Fourth, recovered | 5 | 148 | 68 |

Counts exclude windows straddling a rotation. Intervals are approximately
30 seconds, with a shorter final interval when the observer finished. These
results confirm that the scoped eligibility checks match the target and
permit repeated recovery while group delivery continues. They do not establish
the proprietary firmware's complete replay-security behavior.

The local cleanup timer ran at 11:52:47 and initiated stock restoration.
Subsequent verification found stock loaded, normal options, debug mask zero,
power saving off, control/watchdog services active, no test loader or timer,
no remaining probes, and all observers finished. Only the inert loader lock
file remains. Stock rekey failures resumed at 12:06:09 and repeated every
twenty minutes. SSH key-signing stalls on the observing Mac delayed collection;
the Pi retained the complete test independently.

### Guidance from other implementations and public history

- **OpenBSD `bwfm`:** the 100 microsecond delay immediately before setting
  `wsec_key` was added by `jcs` on **2020-12-17**, in
  [commit 18460ee](https://github.com/openbsd/src/commit/18460ee74fd5a6fb609988236980c83d3e605e14).
  Its stated purpose was to avoid an authentication timing problem on
  **BCM43602**, producing “unexpected pairwise key update” errors. It is not
  evidence for a required delay between deleting and replacing a GTK on
  BCM43430. An earlier
  [2018-07-17 ordering fix](https://github.com/openbsd/src/commit/2802c1786dcf2dffd4d14c32296bd81bfcdaf95e)
  serialized SDIO control and data packets so key installation could not
  overtake EAPOL transmission.
  Inspection of the current
  [upper-layer RSN group-key handler](https://github.com/openbsd/src/blob/master/sys/net80211/ieee80211_pae_input.c)
  confirms that it calls `ic_set_key` directly for a changed GTK, without an
  intervening driver deletion. In the current
  [`bwfm_set_key_cb`](https://github.com/openbsd/src/blob/master/sys/dev/ic/bwfm.c),
  the zero-initialized firmware key structure receives neither `rxiv` nor
  `iv_initialized`, and the `wsec_key` call's return value is not checked.
  These differences limit comparisons: an absence of immediate disconnects
  would not by itself establish successful key installation or correct replay
  protection. They are not reasons to omit replay state or ignore errors in
  the Linux candidate.
- **NetBSD `bwfm`:**
  [PR 57308](https://gnats.netbsd.org/57308) describes a Raspberry Pi 3 B+
  losing connectivity after hours, with replay-counter rejection and
  handshake timeouts. Its logs also show many successful GTK refreshes.
  This is related Wi-Fi recovery history, but does not establish the
  occupied-slot failure observed here.
- **Broadcom Android `bcmdhd`:** the
  [public key-management implementation](https://android.googlesource.com/kernel/common.git/+/bcmdhd-3.10/drivers/net/wireless/bcmdhd/wl_cfg80211.c)
  installs keys directly and deletes them with a zeroed key structure,
  the selected index, and `CRYPTO_ALGO_OFF`. Its
  [transmit-ordering code](https://android.googlesource.com/kernel/common/+/c4651bd65550ab73d9027935acec7a25515263ff/drivers/net/wireless/bcmdhd/dhd_linux.c)
  waits for pending EAPOL frames before key operations. No matching
  clear-before-replacement fix was found in the public material searched;
  Android's history endpoint required authentication, limiting that review.
- **Infineon Wi-Fi Host Driver:** searches of the
  [public repository](https://github.com/Infineon/wifi-host-driver) history
  and issue listings found no matching occupied-GTK-slot fix. Public release
  imports provide limited detail about individual internal fixes. Its usual
  firmware-supplicant path is also a less direct comparison with this host
  key-installation path.
- **Close Linux symptom match:**
  [DietPi issue 5207](https://github.com/MichaIng/DietPi/issues/5207), reported
  on **2022-01-25**, describes a **Pi Zero 2 W** failing every two hours with
  CCMP GTK index 2, `wsec_key error (-52)`, and an immediate local disconnect.
  Disabling power saving did not help. It was closed during issue cleanup,
  without a fix. Its logs lack slot-occupancy tracing, so a shared underlying
  cause remains an inference.
- **Earlier access-point comparison:** a
  [January 2022 firsthand Raspberry Pi forum report](https://forums.raspberrypi.com/viewtopic.php?t=327169)
  describes Zero 2 W failures every 20 minutes; another participant reports
  two-hour failures with an hourly rekey interval. Participants saw different
  behavior on a compatibility network or older access point. A proposed
  PMF/rekey-settings explanation changed multiple settings, so it does not
  isolate PMF or prove this target's cause. Turning off rekeying would also
  remove the event being tested.

A [May 2026 downstream workaround](https://github.com/lollonet/snapMULTI/pull/354)
also reports periodic GTK failures on BCM43430/2 and changes module options.
Its causal explanation needs caution: in this project's kernel, `0x80000`
disables SAE, while FWSUP is `0x2000`; `-52` is `EBADE`, not a timeout.
The cited [firmware issue 23](https://github.com/RPi-Distro/firmware-nonfree/issues/23)
reports missing handshake-offload support, rather than proving the claimed
GTK replacement defect. A short successful observation with several settings
changed is insufficient to validate that workaround for this target.

### Specification checks for the replay investigation

There are three distinct objects; the numeric key slot is not a replay
counter:

| Object | What the receiver checks |
| --- | --- |
| EAPOL-Key Replay Counter | The group-handshake request must advance beyond previously accepted EAPOL-Key requests in the session. |
| GTK key material and Key ID | Reusing a Key ID for a new GTK is normal key rotation; equal IDs do not imply equal keys. |
| GTK receive sequence / packet-number state | Initialize state for a new key from the supplied receive sequence. Repeating an existing key must preserve its established replay state. |

The [IEEE working-group discussion of 802.11-2016 section 12.7.7.2](https://www.ieee802.org/11/email/stds-802-11-tgm/msg01251.html)
identifies the strict group-handshake counter requirement. The official
[nonce-reuse clarification for SetKeys section 6.3.19.1.4](https://mentor.ieee.org/802.11/dcn/17/11-17-1602-03-000m-nonce-reuse-prevention.docx)
distinguishes a new key from an existing key using the key value together
with its address/type/ID, and requires existing-key counters to be preserved.
The [2018 KRACK follow-up paper, section 2.5](https://papers.mathyvanhoef.com/ccs2018.pdf)
documents that standard change. These references concern the specific WPA2
rules being tested, not a full certification/compliance assessment.

A zero receive sequence for a genuinely new, not-yet-used GTK is not by itself
a replay. A retransmitted key announcement is also not automatically an
invalid protocol operation: authenticated handshake freshness and retention
of existing-key replay state must be considered separately. Clearing an
existing identical key to force acceptance would undermine that retention.

`observe-eapol-metadata.py` receives only the fixed Ethernet/EAPOL-Key prefix
through Key RSC, stopping before the MIC and encrypted key data. It records
counter progression comparisons and zero/equality flags, not counter values,
addresses, nonces or key material. It is passive and does not authenticate
the packet itself; correlate its observations with the supplicant's accepted
key-install path and the driver trace. An observation begun after association
has no initial-handshake counter baseline. It can still compare consecutive
group requests; a new observed pairwise handshake starts a new baseline.

### Scoped recovery patch and remaining work

The `retry` patch leaves successful installations alone and attempts recovery
only when all of the following conditions hold:

| Condition | Required value |
| --- | --- |
| Chip and silicon revision | BCM43430, revision 2 |
| Firmware build | Exact FWID `01-3b307371`, the tested 9.88.4.77 build |
| Interface | Station; AP and P2P modes excluded |
| Request | Non-pairwise, non-extended CCMP GTK, 16 bytes, supplied six-byte receive sequence |
| Existing target slot | Cached 16-byte CCMP key with the group/default-key flag |
| Incoming key identity | Different from every cached CCMP key of that length |
| Failure | Linux `-EBADE` accompanied by the actual firmware status `BCME_REPLAY` (-51) |

This kernel stores the final token of the firmware version response in
`drvr->fwver`, which for the tested firmware is the FWID, not the dotted
version number. Exact matching also excludes suffixes or unknown builds.

The firmware interface now optionally returns a separate per-call status
alongside the Linux errno, while holding its existing protocol mutex. Bus,
transport and request-construction failures clear that output to zero, so
an unrelated host `-EBADE` cannot masquerade as firmware replay. Existing
callers retain their previous return convention. The recovery path does not
toggle the shared `fwil_fwerr` mode or keep a global last-error field.

When eligible, recovery clears only the selected slot and retries the exact
requested key and receive sequence once. It stops if clearing fails and
propagates retry failures. Successful recovery logs only the key index.
There is no added delay, firmware replacement or router configuration change.
Requests matching a cached key still follow the normal installation path;
they can never enter this clear-and-retry path. Cache comparison is deliberately
conservative and includes CCMP keys in other group or pairwise slots.

The build compiles the actual patched `add_key` and eligibility functions
against a recording firmware stub. Thirty cases cover eligibility, other
firmware/transport errors, cross-slot key equality, malformed requests,
clear/retry failures and exact receive-sequence preservation. Twelve further
cases compile the actual firmware-interface functions against a transport
stub to verify status separation, early errors, lock release and compatibility
of existing return modes. The build also checks kernel patch style. These
checks test host behavior, not the proprietary firmware's internal replay
state or over-the-air rejection of captured frames.

Both the earlier prototype and the current scoped revision demonstrated
repeated recovery and group traffic delivery in bounded live tests. Explicit
replay-resistance validation remains separate from connectivity success. No
permanent installation is made by the build or temporary test scripts. The distribution module stays available for rollback.
A working-access-point comparison is optional for understanding the trigger.
Keep all logs free of key material and network identifiers.

### Recovery constraints

Tests must work with Wi-Fi as the only management connection. The stock
module remains on disk, one-boot activation consumes its marker before
loading the candidate, and a local timer bounds the experiment. The existing
watchdog provides recovery for detected firmware failures. A reboot following
the experimental boot therefore selects stock, even if SSH was lost.
These mechanisms reduce lockout risk; they cannot guarantee recovery from
every hard hang or power/storage fault. No router security settings need to
be weakened for the experiment.

### Comparing another access point

Start with the distribution driver and the same firmware, kernel, module
options, and power-save setting. Record the active access point using private
local notes, and give it an anonymous label in any shared results. Also record
signal, channel, negotiated security/cipher, and association/reboot times.
Moving the device changes radio conditions as well as the access point, so
distinguish improved reachability from successful key replacement.

Observe at least two actual group rekeys in one association, preferably
several complete alternations of the GTK indices. A hotspot that does not
rotate its GTK is useful as a connectivity comparison but does not exercise
the reproduced replacement failure. Twenty minutes alone is not a universal
test duration: the other access point may use a different rekey interval.
Check sustained traffic across rotations as well as successful return codes;
ordinary unicast ping alone does not demonstrate that group-key decryption
works. Keep stock-driver access-point comparison separate from a later retry
candidate comparison on the original access point.

### Bounded recovery validation

Keep the failing access point and normal module options constant. Use the
one-boot loader with a finite rollback timer; retain the unchanged stock
module. Observe at least four group rotations in one association, including
replacement of both initially used slots, and correlate any recovery with
the firmware rejection and subsequent supplicant result.

`scripts/observe-group-traffic.py` passively counts incoming broadcast,
multicast and unicast Ethernet frames in 30-second windows. It receives only
14-byte headers, stores no addresses, excludes outgoing frames and EAPOL,
and prints only counts and timing. Run it alongside the EAPOL metadata
observer and key-operation probes. Positive group counts after each rotation
provide evidence of delivered group traffic. Silence is inconclusive when
there is no controlled sender. These Ethernet observations do not expose the
over-the-air key ID or packet number, and do not independently validate replay
rejection, multicast-to-unicast behavior, or all security properties.

### Reading firmware errors on the stock driver

`scripts/trace-stock-firmware-errors.sh` uses a private tracefs instance and
temporary kprobes on the verified ARM64 kernel ABI. It captures key index and
pairwise/group classification, key-operation return codes, and only the
specific numeric firmware-error message from `brcmf_fil_cmd_data`. It does not
enable the driver's FIL debug mask: that mask also enables data hexdumps that
can expose key material. No key buffers or sequence counters are fetched by
this script. Static function and format strings identify the filtered error.

Run it as a bounded, detached diagnostic when SSH itself uses Wi-Fi:

```sh
sudo systemd-run --unit=gtk-stock-fwerr --collect \
  --property=RuntimeMaxSec=1560 \
  /bin/bash /absolute/path/to/scripts/trace-stock-firmware-errors.sh 1500
journalctl -u gtk-stock-fwerr --no-pager
```

The script prints its buffer when the requested duration ends and removes its
own probes and trace instance on exit or termination. It does not unload the
driver or change Wi-Fi settings. Trace timestamps are monotonic; compare them
with `journalctl -k -b -o short-monotonic`. Routine unrelated operations can
also return firmware errors, so correlate the same task's key-add event,
firmware error, and key return value before attributing a code to a GTK.

## Building

Run in a Debian or Ubuntu Linux environment with an ARM64 cross compiler:

```sh
./scripts/build.sh trace
./scripts/build.sh retry
```

Artifacts are written beneath `dist/`.

## Temporary test loading

The loading scripts require root and must run from a persistent absolute path
on the target. They never overwrite the distribution module.

```sh
sudo ./scripts/start-temporary-test.sh /absolute/path/to/brcmfmac-trace.ko 45
```

The command first verifies that the candidate's kernel release exactly matches
the running kernel. It then arms a detached stock-driver rollback timer before
launching a second detached unit that swaps the module. This is necessary when
the management connection itself uses `wlan0`: SSH will disappear during the
swap, but both jobs continue under systemd.

If the temporary module fails to load or Wi-Fi does not reconnect within two
minutes, the activation job restores the stock module immediately. Otherwise,
the timer restores it after the requested test duration. Because the stock
module on disk is never replaced, a reboot also restores stock.

The swap unloads and reloads the Raspberry Pi kernel's `brcmfmac_cyw`
Cypress/Infineon companion plugin around the core `brcmfmac` module. This keeps
the temporary and restored stacks equivalent to the normal boot-time stack.
It also carries the installed `modprobe.d` options into the temporary module;
these settings can materially alter firmware behavior.

Inspect the detached jobs with:

```sh
systemctl status brcmfmac-test-activate.service
systemctl status brcmfmac-test-rollback.timer
journalctl -u brcmfmac-test-activate -u brcmfmac-test-rollback
```

### One-boot loading

Some SDIO firmware does not tolerate unloading and reloading the live driver.
For that case, arm the candidate for exactly the next boot:

```sh
sudo ./scripts/arm-one-boot-test.sh /absolute/path/to/brcmfmac-trace.ko 45
sudo systemctl reboot
```

The loader serializes concurrent udev requests with a file lock and checks
whether the module is already loaded before consuming the marker. A live
attempt exposed why this matters: consuming the marker alone allowed another
worker to load stock while the first inserted the candidate, which failed
with `File exists`. That attempt booted stock and did not test the retry
patch. The isolated loader tests cover concurrent requests, option forwarding,
failed insertion, and return to stock on the following boot.

The generated `modprobe` rule atomically consumes a one-shot marker before it
inserts the candidate. Any later boot therefore loads the distribution module,
even if the candidate causes an immediate crash. A boot timer removes the rule
and reboots after the requested duration when the candidate remains running.
If a crash already caused a second, stock-driver boot, the timer only cleans up
the test files and does not reboot again. Kernel options appended by `modprobe`
are forwarded unchanged to the candidate through modprobe's `CMDLINE_OPTS`
substitution.

## Persistent installation of the tested artifact

`scripts/manage-persistent-module.sh` installs only the exact module from the
scoped live test above: kernel `6.18.39+rpt-rpi-v8`, artifact SHA-256
`13421cc55747df027a15a5d373d3ca1bce6a45179a682952f2db3a80cefdbf3c`.
It checks the checksum, kernel ABI and source version before making changes.
A newly built artifact, even from the same source, requires separate validation;
it is not automatically accepted by this installer.

```sh
sudo ./scripts/manage-persistent-module.sh install /absolute/path/to/brcmfmac-retry.ko
sudo systemctl reboot
```

The installer puts the module in
`/lib/modules/6.18.39+rpt-rpi-v8/updates/gtk-rekey/brcmfmac.ko`, regenerates
module dependencies and the initramfs, and preserves the distribution module
under `kernel/`. Existing modprobe options continue to apply. It does not
change firmware, network configuration or the currently loaded driver.

The first reboot has a **15-minute automatic rollback guard**. After verifying
SSH, the loaded module and application services, confirm the installation:

```sh
sudo /usr/local/libexec/brcmfmac-gtk-rekey/manage-persistent-module confirm
```

Confirmation requires the tested module's source version to be loaded, the
installed checksum to match, and module selection to resolve to the override.
It then removes the installation rollback timer. If unconfirmed, the local
timer removes the override, regenerates dependencies and the boot image, and
reboots into stock. This guard depends on the system remaining able to run
its local timer; it does not guarantee recovery from every hard hang.

To remove the persistent patch later:

```sh
sudo /usr/local/libexec/brcmfmac-gtk-rekey/manage-persistent-module remove --reboot
```

Removal refuses to delete a module whose checksum no longer matches this
installer. The root-owned helper remains available after confirmation. Six
isolated installer tests cover artifact rejection, next-boot timer arming,
loaded-module confirmation, rollback, boot-image update failure, and refusal
to remove an unrelated replacement.

This installation applies only to the pinned kernel release. A different
kernel loads its distribution module, so rekey failures may return after a
kernel upgrade until a matching patch is built, tested and installed. The
installer does not hold kernel or firmware package updates.

## Privacy

This is intentionally a public, device-agnostic repository. Do not attach raw
logs without sanitizing network names, hardware addresses, local addresses,
hostnames, credentials, and tokens. The diagnostic patch itself emits none of
those values.

## License

The Linux kernel patches are provided under GPL-2.0-only, matching the patched
kernel source file. Repository build and test scripts are also GPL-2.0-only.
