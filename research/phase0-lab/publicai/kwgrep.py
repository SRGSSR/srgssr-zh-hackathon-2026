"""Keyword-in-context grep over saved text/html files (evidence helper)."""
import re, sys
pat = re.compile(sys.argv[1], re.I)
w = int(sys.argv[2])
for f in sys.argv[3:]:
    s = open(f, encoding="utf-8", errors="replace").read()
    lines = s.split("\n") if f.endswith(".txt") else None
    if lines is not None:
        for n, l in enumerate(lines, 1):
            if pat.search(l):
                print(f"{f}:{n}: {l.strip()[:w]}")
    else:
        for m in pat.finditer(s):
            print(f"{f}@{m.start()}: ...{s[max(0,m.start()-w):m.end()+w]}...".replace("\n", " "))
