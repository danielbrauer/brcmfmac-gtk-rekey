#!/usr/bin/env python3
"""Exercise actual firmware-interface status handling with a transport stub."""
from pathlib import Path
import re
import subprocess
import sys
import tempfile

source_path = Path(sys.argv[1])
source = source_path.read_text()
header = source_path.with_name('fwil.h').read_text()
errors = re.search(r'brcmf_fil_errstr\[\] = \{(.*?)\};', source, re.S).group(1)
names = re.findall(r'"(BCME_[A-Z0-9_]+)"', errors)
expected = -names.index('BCME_REPLAY')
actual = int(re.search(r'#define BRCMF_FWERR_REPLAY\s+\((-?\d+)\)', header).group(1))
assert actual == expected == -51
start = source.index('static s32\nbrcmf_fil_cmd_data(')
end = source.index('\ns32\nbrcmf_fil_cmd_data_set(', start)
command = source[start:end]
start = source.index('s32\nbrcmf_fil_bsscfg_data_set_with_fwerr(')
end = source.index('\nBRCMF_EXPORT_SYMBOL_GPL(brcmf_fil_bsscfg_data_set);', start)
setters = source[start:end]
preamble = r'''
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <errno.h>
#ifndef EBADE
#define EBADE 52
#endif
typedef uint32_t u32;
typedef unsigned int uint;
typedef int32_t s32;
#define BRCMF_BUS_UP 1
#define BRCMF_DCMD_MAXLEN 64
#define BRCMF_C_SET_VAR 263
#define min_t(type,a,b) ((type)(a) < (type)(b) ? (type)(a) : (type)(b))
#define bphy_err(...) ((void)0)
#define brcmf_dbg(...) ((void)0)
#define brcmf_dbg_hex_dump(...) ((void)0)
struct brcmf_bus { int state; };
struct brcmf_pub { struct brcmf_bus *bus_if; int proto_block; char proto_buf[64]; };
struct brcmf_if { struct brcmf_pub *drvr; int ifidx, bsscfgidx; bool fwil_fwerr; };
static int transport_result, firmware_result, protocol_calls;
static bool create_ok;
static void mutex_lock(int *m) { assert(*m == 0); *m = 1; }
static void mutex_unlock(int *m) { assert(*m == 1); *m = 0; }
static int brcmf_proto_set_dcmd(struct brcmf_pub *d, int i, u32 c,
                               void *buffer, u32 len, s32 *fwerr) {
    assert(d->proto_block == 1); protocol_calls++;
    *fwerr = firmware_result; return transport_result;
}
static int brcmf_proto_query_dcmd(struct brcmf_pub *d, int i, u32 c,
                                 void *buffer, u32 len, s32 *fwerr) {
    return brcmf_proto_set_dcmd(d, i, c, buffer, len, fwerr);
}
static u32 brcmf_create_bsscfg(s32 index, const char *name, void *data, u32 len,
                              void *buffer, u32 size) {
    return create_ok ? 16 : 0;
}
'''
tests = r'''
struct testcase {
    const char *name;
    int host, firmware, bus_up;
    bool buffer_ok, legacy_flag, explicit_status;
    int result, output, calls;
};
int main(void) {
    struct testcase cases[] = {
        {"success", 0, 0, 1, true, false, true, 0, 0, 1},
        {"replay", 0, -51, 1, true, false, true, -EBADE, -51, 1},
        {"other-fw-error", 0, -23, 1, true, false, true, -EBADE, -23, 1},
        {"transport-error", -EIO, -51, 1, true, false, true, -EIO, 0, 1},
        {"transport-EBADE", -EBADE, -51, 1, true, false, true, -EBADE, 0, 1},
        {"bus-down", 0, -51, 0, true, false, true, -EIO, 0, 0},
        {"builder-failed", 0, -51, 1, false, false, true, -EPERM, 0, 0},
        {"explicit-ignores-legacy-mode", 0, -51, 1, true, true, true, -EBADE, -51, 1},
        {"explicit-host-error-in-legacy-mode", -EIO, -51, 1, true, true, true, -EIO, 0, 1},
        {"legacy-raw-mode", 0, -51, 1, true, true, false, -51, 999, 1},
        {"legacy-normal-mode", 0, -51, 1, true, false, false, -EBADE, 999, 1},
        {"legacy-success", 0, 0, 1, true, false, false, 0, 999, 1},
    };
    unsigned total = sizeof(cases)/sizeof(cases[0]);
    for (unsigned i=0; i<total; ++i) {
        struct testcase t = cases[i];
        struct brcmf_bus bus = {.state=t.bus_up};
        struct brcmf_pub drvr = {.bus_if=&bus};
        struct brcmf_if ifp = {.drvr=&drvr, .fwil_fwerr=t.legacy_flag};
        transport_result=t.host; firmware_result=t.firmware; create_ok=t.buffer_ok;
        protocol_calls=0;
        s32 fwerr=999;
        int result = t.explicit_status ?
            brcmf_fil_bsscfg_data_set_with_fwerr(&ifp, "wsec_key", NULL, 0, &fwerr) :
            brcmf_fil_bsscfg_data_set(&ifp, "wsec_key", NULL, 0);
        if (result != t.result || fwerr != t.output || protocol_calls != t.calls) {
            fprintf(stderr, "%s: result=%d fwerr=%d calls=%d\n", t.name, result, fwerr, protocol_calls);
            return 1;
        }
        assert(ifp.fwil_fwerr == t.legacy_flag && drvr.proto_block == 0);
    }
    printf("%u firmware-status tests passed (transport stub)\n", total);
    return 0;
}
'''
with tempfile.TemporaryDirectory() as directory:
    root = Path(directory)
    c = root / 'test.c'
    c.write_text(preamble + command + setters + tests)
    binary = root / 'test'
    subprocess.run(['cc', '-std=c11', '-Wall', '-Wextra', '-Wno-unused-parameter',
                    str(c), '-o', str(binary)], check=True)
    subprocess.run([str(binary)], check=True)
