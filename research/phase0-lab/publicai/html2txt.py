"""Convert saved HTML pages to plain text (evidence helper, no network)."""
import re, html, sys
for f in sys.argv[1:]:
    s = open(f, encoding="utf-8", errors="replace").read()
    s2 = re.sub(r"<script[^>]*>.*?</script>", "", s, flags=re.S)
    s2 = re.sub(r"<style[^>]*>.*?</style>", "", s2, flags=re.S)
    t = re.sub(r"<(br|/p|/div|/li|/h\d|/tr|/pre|/code|/section|/a)[^>]*>", "\n", s2)
    t = re.sub(r"<[^>]+>", " ", t)
    t = html.unescape(t)
    t = re.sub(r"[ \t]+", " ", t)
    t = re.sub(r"\n\s*\n+", "\n", t)
    open(f.rsplit(".", 1)[0] + ".txt", "w").write(t)
    print(f, len(t))
