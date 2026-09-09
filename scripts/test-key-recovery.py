#!/usr/bin/env python3
"""Compile the patched add_key function against a recording firmware stub."""
from pathlib import Path
import subprocess
import sys
import tempfile

source = Path(sys.argv[1]).read_text()
start = source.index("static bool brcmf_gtk_replay_recovery_allowed(")
end = source.index("\nstatic s32\nbrcmf_cfg80211_get_key(", start)
function = source[start:end]
preamble = r'''
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <errno.h>
#ifndef EBADE
#define EBADE 52
#endif
typedef uint8_t u8;
typedef uint32_t u32;
typedef int32_t s32;
#define ETH_ALEN 6
#define BRCMF_MAX_DEFAULT_KEYS 6
#define BRCMF_PRIMARY_KEY 2
#define BRCM_CC_43430_CHIP_ID 43430
#define BRCMF_FWERR_REPLAY (-51)
#define NL80211_IFTYPE_STATION 2
#define NL80211_IFTYPE_AP 3
#define NL80211_IFTYPE_P2P_CLIENT 8
#define CRYPTO_ALGO_OFF 0
#define CRYPTO_ALGO_WEP1 1
#define CRYPTO_ALGO_TKIP 2
#define CRYPTO_ALGO_WEP128 3
#define CRYPTO_ALGO_AES_CCM 4
#define WLAN_CIPHER_SUITE_WEP40 0x000fac01
#define WLAN_CIPHER_SUITE_TKIP 0x000fac02
#define WLAN_CIPHER_SUITE_CCMP 0x000fac04
#define WLAN_CIPHER_SUITE_WEP104 0x000fac05
#define WLAN_CIPHER_SUITE_AES_CMAC 0x000fac06
#define WEP_ENABLED 1
#define TKIP_ENABLED 2
#define AES_ENABLED 4
#define brcmf_dbg(...) ((void)0)
#define brcmf_info(...) do { if (0) printf(__VA_ARGS__); } while (0)
#define bphy_err(...) ((void)0)
struct brcmf_wsec_key {
    u32 index, len, algo, flags, iv_initialized;
    u8 data[32], ea[6];
    struct { u32 hi; unsigned short lo; } rxiv;
};
struct brcmf_bus { u32 chip, chiprev; };
struct brcmf_pub { struct brcmf_bus *bus_if; const char *fwver; };
struct brcmf_profile { struct brcmf_wsec_key key[6]; };
struct brcmf_vif { struct brcmf_profile profile; struct { int iftype; } wdev; };
struct brcmf_if { struct brcmf_vif *vif; struct brcmf_pub *drvr; };
struct brcmf_cfg80211_info { struct brcmf_pub *pub; };
struct wiphy { struct brcmf_cfg80211_info *cfg; };
struct net_device { struct brcmf_if *ifp; };
struct key_params { int key_len, seq_len; u32 cipher; const u8 *key, *seq; };
static struct brcmf_wsec_key calls[4];
static int results[4], firmware_results[4], count;
static bool status_requested[4];
static struct brcmf_cfg80211_info *wiphy_to_cfg(struct wiphy *w) { return w->cfg; }
static struct brcmf_if *netdev_priv(struct net_device *n) { return n->ifp; }
static bool check_vif_up(struct brcmf_vif *v) { return true; }
static bool brcmf_is_apmode(struct brcmf_vif *v) { return false; }
static bool is_multicast_ether_addr(const u8 *a) { return a[0] & 1; }
static const void *memchr_inv(const void *p, int c, unsigned n) {
    const u8 *s = p; while (n--) { if (*s != c) return s; ++s; } return NULL;
}
static int brcmf_cfg80211_del_key(struct wiphy *w, struct net_device *n,
                                int link, u8 index, bool pairwise, const u8 *mac) {
    return -EINVAL;
}
static int send_key_to_dongle(struct brcmf_if *ifp, struct brcmf_wsec_key *key, s32 *fwerr) {
    assert(count < 4); calls[count] = *key;
    status_requested[count] = fwerr != NULL;
    if (fwerr) *fwerr = firmware_results[count];
    return results[count++];
}
static int brcmf_fil_bsscfg_int_get(struct brcmf_if *i, const char *name, s32 *v) {
    *v = 0; return 0;
}
static int brcmf_fil_bsscfg_int_set(struct brcmf_if *i, const char *name, s32 v) {
    return 0;
}
'''
tests = r'''
int main(void) {
    const char *names[] = {"changed", "success", "identical", "pairwise", "unused",
                         "transport-error", "non-CCMP", "clear-failure", "retry-failure",
                         "nonzero-receive-sequence", "wrong-chip", "wrong-revision", "wrong-firmware",
                         "AP-mode", "P2P-client", "other-firmware-error", "transport-EBADE",
                         "missing-sequence", "invalid-sequence-length", "old-non-CCMP",
                         "old-wrong-key-length", "old-pairwise-slot", "new-wrong-key-length",
                         "identical-other-group-slot", "identical-pairwise-slot",
                         "matching-prefix-different-length", "different-other-cached-key",
                         "extended-key", "invalid-index", "oversize-key"};
    for (int test = 0; test < 30; ++test) {
        struct brcmf_vif vif = {0};
        struct brcmf_bus bus = {.chip=BRCM_CC_43430_CHIP_ID, .chiprev=2};
        struct brcmf_pub pub = {.bus_if=&bus, .fwver="01-3b307371"};
        vif.wdev.iftype = NL80211_IFTYPE_STATION;
        struct brcmf_cfg80211_info cfg = { .pub = &pub };
        struct brcmf_if ifp = { .vif = &vif, .drvr = &pub };
        struct wiphy w = { .cfg = &cfg };
        struct net_device n = { .ifp = &ifp };
        u8 key[32], sequence[6] = {0};
        memset(key, 0x42, sizeof(key));
        struct key_params params = {.key_len=16, .seq_len=6,
                                    .cipher=WLAN_CIPHER_SUITE_CCMP, .key=key, .seq=sequence};
        struct brcmf_wsec_key *old = &vif.profile.key[2];
        old->algo = CRYPTO_ALGO_AES_CCM; old->len = 16; old->flags = BRCMF_PRIMARY_KEY;
        memset(old->data, 0x41, old->len);
        memset(calls, 0, sizeof(calls)); memset(results, 0, sizeof(results));
        memset(firmware_results, 0, sizeof(firmware_results));
        memset(status_requested, 0, sizeof(status_requested));
        count = 0; results[0] = -EBADE; firmware_results[0] = BRCMF_FWERR_REPLAY;
        int expected_calls = 3, expected_result = 0;
        bool pairwise = false;
        const u8 *mac = NULL;
        u8 synthetic_mac[6] = {2, 0, 0, 0, 0, 1};
        u8 index = 2;
        if (test == 1) { results[0] = 0; expected_calls = 1; }
        if (test == 2) { memcpy(old->data, key, 16); expected_calls = 1; expected_result = -EBADE; }
        if (test == 3) { pairwise = true; expected_calls = 1; expected_result = -EBADE; }
        if (test == 4) { old->algo = CRYPTO_ALGO_OFF; expected_calls = 1; expected_result = -EBADE; }
        if (test == 5) { results[0] = -EIO; expected_calls = 1; expected_result = -EIO; }
        if (test == 6) { params.cipher = WLAN_CIPHER_SUITE_TKIP; params.key_len = 32;
                         old->algo = CRYPTO_ALGO_TKIP; expected_calls = 1; expected_result = -EBADE; }
        if (test == 7) { results[1] = -EIO; expected_calls = 2; expected_result = -EIO; }
        if (test == 8) { results[2] = -EBADE; expected_result = -EBADE; }
        if (test == 9) { for (int j=0;j<6;++j) sequence[j] = j + 1; }
        if (test >= 10) { expected_calls = 1; expected_result = -EBADE; }
        if (test == 10) bus.chip++;
        if (test == 11) bus.chiprev++;
        if (test == 12) pub.fwver = "01-3b307371-extra";
        if (test == 13) vif.wdev.iftype = NL80211_IFTYPE_AP;
        if (test == 14) vif.wdev.iftype = NL80211_IFTYPE_P2P_CLIENT;
        if (test == 15) firmware_results[0] = -23;
        if (test == 16) firmware_results[0] = 0;
        if (test == 17) params.seq = NULL;
        if (test == 18) params.seq_len = 5;
        if (test == 19) old->algo = CRYPTO_ALGO_TKIP;
        if (test == 20) old->len = 15;
        if (test == 21) old->flags = 0;
        if (test == 22) params.key_len = 15;
        if (test >= 23 && test <= 26) {
            struct brcmf_wsec_key *other = &vif.profile.key[0];
            other->algo = CRYPTO_ALGO_AES_CCM;
            other->len = test == 25 ? 32 : 16;
            other->flags = test == 24 ? 0 : BRCMF_PRIMARY_KEY;
            memcpy(other->data, key, 16);
            if (test == 26) other->data[0]++;
            if (test >= 25) { expected_calls = 3; expected_result = 0; }
        }
        if (test == 27) mac = synthetic_mac;
        if (test == 28) { index = BRCMF_MAX_DEFAULT_KEYS; expected_calls = 0; expected_result = -EINVAL; }
        if (test == 29) { params.key_len = 33; expected_calls = 0; expected_result = -EINVAL; }
        int result = brcmf_cfg80211_add_key(&w, &n, -1, index, pairwise, mac, &params);
        if (result != expected_result || count != expected_calls) {
            fprintf(stderr, "%s: unexpected result or operation count\n", names[test]); return 1;
        }
        if (test >= 10 && test <= 14) assert(!status_requested[0]);
        if (test == 15 || test == 16) assert(status_requested[0]);
        if (count >= 2) {
            assert(calls[1].index == 2 && calls[1].algo == CRYPTO_ALGO_OFF);
            assert(calls[1].flags == BRCMF_PRIMARY_KEY && calls[1].len == 0);
            for (int j=0;j<32;++j) assert(calls[1].data[j] == 0);
        }
        if (count == 3) {
            assert(memcmp(&calls[0], &calls[2], sizeof(calls[0])) == 0);
            assert(calls[2].iv_initialized == 1);
            assert(memcmp(calls[2].data, key, 16) == 0);
        }
        if (test == 9) {
            assert(calls[2].rxiv.hi == 0x06050403 && calls[2].rxiv.lo == 0x0201);
        }
    }
    puts("30 recovery-path tests passed (recording firmware stub)");
    return 0;
}
'''
with tempfile.TemporaryDirectory() as directory:
    root = Path(directory)
    c = root / "test.c"
    c.write_text(preamble + function + tests)
    binary = root / "test"
    subprocess.run(["cc", "-std=c11", "-Wall", "-Wextra", "-Wno-unused-parameter",
                    "-Wno-unused-variable", "-Wno-sign-compare", str(c), "-o", str(binary)], check=True)
    subprocess.run([str(binary)], check=True)
