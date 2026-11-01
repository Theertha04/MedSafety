import re

with open("frontend/app.js", "r", encoding="utf-8") as f:
    code = f.read()

pattern = r'(\/\*[\s\S]*?\*\/|\/\/[^\n]*|"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'|`(?:\\.|[^`\\])*`)'
clean = re.sub(pattern, lambda m: " " * len(m.group(0)), code)

stack = []
pairs = {")": "(", "}": "{", "]": "["}
orig_lines = code.split("\n")

for i, ch in enumerate(clean):
    line_no = clean[:i].count("\n") + 1
    if ch in "({[":
        stack.append((ch, line_no))
    elif ch in ")}]":
        if not stack:
            print("Extra", ch, "at line", line_no)
            break
        top_ch, top_line = stack.pop()
        if pairs[ch] != top_ch:
            print(f'Line {line_no}: Found "{ch}", but expected matching "{pairs[ch]}" for "{top_ch}" opened on line {top_line}')
            print(f"Context of opened bracket at line {top_line}:")
            for l in range(max(0, top_line - 3), min(len(orig_lines), top_line + 3)):
                print(f"{l+1}: {orig_lines[l]}")
            print(f"Context of closing bracket at line {line_no}:")
            for l in range(max(0, line_no - 3), min(len(orig_lines), line_no + 3)):
                print(f"{l+1}: {orig_lines[l]}")
            break
else:
    if stack:
        print("Unclosed:", stack)
    else:
        print("PERFECT: 0 syntax/bracket errors in app.js!")
