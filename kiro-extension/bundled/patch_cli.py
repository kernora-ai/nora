#!/usr/bin/env python3
import sys

files_to_patch = [
    "kernora_cli.py",
    "kiro-extension/bundled/kernora_cli.py"
]

for filename in files_to_patch:
    try:
        with open(filename, "r") as f:
            content = f.read()

        old_str = """    if "kiro" in app_name:
        ide = "kiro"
    elif "cursor" in app_name:
        ide = "cursor\""""
        new_str = """    if "kiro" in app_name:
        ide = "kiro"
    elif "cursor" in app_name:
        ide = "cursor"
    elif "antigravity" in app_name or os.environ.get("ANTIGRAVITY_AGENT"):
        ide = "antigravity\""""
        
        content = content.replace(old_str, new_str)

        with open(filename, "w") as f:
            f.write(content)
        
        print(f"Patched {filename}")
    except FileNotFoundError:
        print(f"File not found: {filename}")
