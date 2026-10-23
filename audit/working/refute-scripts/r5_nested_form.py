"""R5: parse training_scenario_active.html with an HTML5 tree builder to test nested-form claim (F-S09-05)."""
import sys
sys.path.insert(0, sys.argv[1])
import html5lib
src = open(sys.argv[2]).read()
doc = html5lib.parse("<body>" + src + "</body>", namespaceHTMLElements=False)
forms = doc.findall(".//form")
print("form elements:", len(forms))
for f in forms:
    print(" form hx-post=", f.get("hx-post"))
    for b in f.iter("button"):
        print("   button type=", b.get("type"), "text=", "".join(b.itertext()).strip()[:30])
