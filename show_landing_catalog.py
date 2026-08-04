import re, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

html = open(r"C:\Users\emman\appvault-cloud-prod\templates\landing.html", encoding="utf-8").read()
idx = html.find("Full App Catalog")
print(html[idx-300:idx+4500])
