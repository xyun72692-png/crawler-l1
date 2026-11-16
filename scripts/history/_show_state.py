# -*- coding: utf-8 -*-
import io
import json

p = r"D:\agent-work\manifests\state_wzrc_inc_verify.json"
d = json.load(io.open(p, encoding="utf-8"))
for k, v in d.items():
    if isinstance(v, list):
        if k == "seen_keys":
            print("  %-22s <list %d items>" % (k, len(v)))
        else:
            print("  %-22s %s" % (k, v[:30]))
    else:
        print("  %-22s %r" % (k, v))