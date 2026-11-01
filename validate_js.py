with open("frontend/app.js", "r", encoding="utf-8") as f:
    text = f.read()

import re
print("Length of app.js:", len(text))
# Check for common JS errors or unclosed blocks
# Count curly braces
open_b = text.count("{")
close_b = text.count("}")
print("Curly braces:", open_b, "open vs", close_b, "close")

open_p = text.count("(")
close_p = text.count(")")
print("Parentheses:", open_p, "open vs", close_p, "close")

open_s = text.count("[")
close_s = text.count("]")
print("Square brackets:", open_s, "open vs", close_s, "close")

assert open_b == close_b, f"Mismatched curly braces: {open_b} != {close_b}"
assert open_p == close_p, f"Mismatched parentheses: {open_p} != {close_p}"
assert open_s == close_s, f"Mismatched square brackets: {open_s} != {close_s}"
print("All JS blocks match!")
