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
- `retry`: includes the trace and, after firmware rejection of a changed key
  in an occupied CCMP group-key slot, clears that slot using the driver's
  existing deletion representation and retries once.

Neither variant logs key bytes, credentials, SSIDs, BSSIDs, MAC addresses, IP
addresses, or other network configuration.

## Status

Research prototype. A live `trace` test reproduced failure when an occupied
GTK slot was reused. A subsequent stock-driver probe identified the firmware
rejection as **`BCME_REPLAY` (-51)**. An expanded trace then reproduced it with
a changed key and an advancing EAPOL-Key Replay Counter, strongly suggesting
a false replay rejection during replacement. The `retry` variant has been
built by CI but has **not been deployed or demonstrated to fix the problem**.
The completed trace tests were cleaned up and the target returned to its
untouched stock driver, with normal options and control services verified.

The modules are built as temporary test artifacts. They should be loaded from
a staging directory without replacing the distribution module. A reboot must
continue to load the untouched stock driver.

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

### Proposed recovery and remaining work

The `retry` patch leaves successful installations unchanged. After firmware
rejection (`-EBADE`) of a changed key in an occupied CCMP group-key slot, it
clears just that slot using the existing deletion representation and retries
the requested key once. Initial installs, pairwise keys, non-CCMP keys,
transport errors, and keys identical to that slot's cached CCMP key do not
enter this recovery. The identical-key guard avoids deliberately clearing a
cached copy of the same key and resetting its replay state. This guard does
not establish complete replay safety: the host cache is not authoritative
firmware state and broader protocol validation is still required.
The current patch has no additional delay. The OpenBSD history does not by
itself justify adding one.

This is an experimental recovery path, not an upstream fix. It currently
triggers on any firmware rejection satisfying those conditions and is not
restricted by chip or firmware version. Before broader use, review error
selection, device scoping, failure handling, and key/replay-state behavior.
Clearing a key is state-changing; if recovery fails, connectivity can still
be lost. Successful return codes alone will not demonstrate correct traffic
decryption or security behavior.

The expanded trace establishes a changed key and advancing handshake counter
at the rejection. Next compare the stock driver across access points and
review the replacement command's replay-state semantics. Do not treat
clearing the slot and obtaining a successful return as a validated fix for a
replay rejection. Replay protection must remain correct. Any later candidate
test must hold kernel, firmware and module options constant, observe repeated reuse of
both GTK slots, and verify sustained group traffic as well as key-install
outcomes. Keep all logs free of key material and network identifiers.

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

## Privacy

This is intentionally a public, device-agnostic repository. Do not attach raw
logs without sanitizing network names, hardware addresses, local addresses,
hostnames, credentials, and tokens. The diagnostic patch itself emits none of
those values.

## License

The Linux kernel patches are provided under GPL-2.0-only, matching the patched
kernel source file. Repository build and test scripts are also GPL-2.0-only.
