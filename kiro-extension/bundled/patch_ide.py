#!/usr/bin/env python3
import sys

files_to_patch = [
    "dashboard.py",
    "dashboard_installed.py",
    "kiro-extension/bundled/dashboard.py"
]

for filename in files_to_patch:
    try:
        with open(filename, "r") as f:
            content = f.read()

        # Replace the `in ("kiro", "cursor")` with `in ("kiro", "cursor", "antigravity")`
        old_tuple = "(\"kiro\", \"cursor\")"
        new_tuple = "(\"kiro\", \"cursor\", \"antigravity\")"
        
        content = content.replace(old_tuple, new_tuple)

        with open(filename, "w") as f:
            f.write(content)
        
        print(f"Patched {filename}")
    except FileNotFoundError:
        print(f"File not found: {filename}")
