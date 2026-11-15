"""First difference between two action logs (RP_LOG of the TypeScript RoutePulse and of bot4.py) on the same seed.

    python rp_diff.py logs/rp-ts-bench-2.jsonl logs/rp-py-bench-2.jsonl
"""
import json
import sys


def canon(a):
    return json.dumps(a, sort_keys=True, separators=(",", ":"))


def main() -> None:
    ta = [json.loads(l) for l in open(sys.argv[1])]
    pa = [json.loads(l) for l in open(sys.argv[2])]
    print(f"batches: ts {len(ta)}  py {len(pa)}")
    for i, (t, p) in enumerate(zip(ta, pa)):
        if t["now"] != p["now"] or t["stopAt"] != p["stopAt"]:
            print(f"#{i}: clock differs: ts now {t['now']} stopAt {t['stopAt']}  py now {p['now']} stopAt {p['stopAt']}")
            print("  ts actions:", [canon(a)[:160] for a in t["actions"]][:6])
            print("  py actions:", [canon(a)[:160] for a in p["actions"]][:6])
            return
        tc, pc = [canon(a) for a in t["actions"]], [canon(a) for a in p["actions"]]
        if tc != pc:
            print(f"#{i}: at minute {t['now']} (day {t['now'] // 1440}, {t['now'] % 1440 // 60:02d}:{t['now'] % 60:02d}): actions differ "
                  f"({len(tc)} ts, {len(pc)} py)")
            for k in range(max(len(tc), len(pc))):
                a = tc[k] if k < len(tc) else "-"
                b = pc[k] if k < len(pc) else "-"
                if a != b:
                    print(f"  [{k}] ts {a[:600]}\n       py {b[:600]}")
            return
    print("identical over", min(len(ta), len(pa)), "batches")


if __name__ == "__main__":
    main()
