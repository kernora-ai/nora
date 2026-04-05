#!/usr/bin/env python3
# Kernora — AI Work Intelligence
# Elastic License 2.0 — commercial use requires agreement with kernora.ai
# https://github.com/kernora-ai/nora/blob/main/LICENSE
import sys
import os
import subprocess
import socket

# Kernora Kiro CLI Shield
# Usage: Add to Kiro Agent Hooks under "OnSpecGenerated". 
# Resolves the absolute path to the generated spec markdown and evaluates it.
# Exits with Code 1 to forcefully block the Kiro execution agent from writing code.

def ensure_dashboard_running():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        if s.connect_ex(('127.0.0.1', 2742)) != 0:
            dashboard_path = os.path.join(os.path.dirname(__file__), 'dashboard.py')
            venv_python = os.path.join(os.path.dirname(__file__), 'venv', 'bin', 'python3')
            subprocess.Popen([venv_python, dashboard_path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)

def main():
    ensure_dashboard_running()
    if len(sys.argv) < 2:
        print("Usage: kiro_spec_shield.py <path_to_spec.md>")
        sys.exit(0)
        
    spec_path = sys.argv[1]
    if not os.path.exists(spec_path):
        print(f"Error: Could not find Kiro spec file at {spec_path}")
        sys.exit(1)
        
    with open(spec_path, 'r', encoding='utf-8') as f:
        spec_content = f.read().lower()
        
    # Kernora Security & Architectural Heuristics
    danger_keywords = [
        "rewrite entire", 
        "refactor all", 
        "allow public access", 
        "chmod 777",
        "drop table",
        "bypass auth"
    ]
    
    triggers = [kw for kw in danger_keywords if kw in spec_content]
    
    if triggers:
        print(f"\n\033[91m[Kernora Shield]\033[0m 🛑 Kiro Spec Execution Blocked!")
        print(f"Reason: Detected dangerous architecture or massive scope directives in the generated spec.")
        print(f"Violations triggered: {triggers}")
        print("Please revise your Kiro prompt to decompose the batch or restrict IAM scopes.\n")
        sys.exit(1) # OS Exit 1 tells the Kiro CLI that the hook FAILED, halting execution.
        
    print(f"\n\033[92m[Kernora Shield]\033[0m ✅ Kiro Spec Validated. Scope is constrained. Safe to proceed to code-generation.\n")
    sys.exit(0)

if __name__ == "__main__":
    main()
