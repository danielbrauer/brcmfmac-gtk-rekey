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
  length, and whether the driver's key slot was already occupied.
- `retry`: includes the trace and, after a failed replacement of an occupied
  CCMP group-key slot, clears that slot using the driver's existing deletion
  representation and retries once.

Neither variant logs key bytes, credentials, SSIDs, BSSIDs, MAC addresses, IP
addresses, or other network configuration.

## Status

Research prototype. Do not install the `retry` variant before the `trace`
variant confirms the occupied-slot hypothesis.

The modules are built as temporary test artifacts. They should be loaded from
a staging directory without replacing the distribution module. A reboot must
continue to load the untouched stock driver.

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

Inspect the detached jobs with:

```sh
systemctl status brcmfmac-test-activate.service
systemctl status brcmfmac-test-rollback.timer
journalctl -u brcmfmac-test-activate -u brcmfmac-test-rollback
```

## Privacy

This is intentionally a public, device-agnostic repository. Do not attach raw
logs without sanitizing network names, hardware addresses, local addresses,
hostnames, credentials, and tokens. The diagnostic patch itself emits none of
those values.

## License

The Linux kernel patches are provided under GPL-2.0-only, matching the patched
kernel source file. Repository build and test scripts are also GPL-2.0-only.
