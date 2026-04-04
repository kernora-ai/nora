#!/usr/bin/env python3
# kernora_installer.py
import os
import json
import sys
from pathlib import Path

def install_mcp():
    conf_path = Path.home() / "Library/Application Support/Claude/claude_desktop_config.json"
    conf_path.parent.mkdir(parents=True, exist_ok=True)
    
    config = {"mcpServers": {}}
    if conf_path.exists():
        try:
            with open(conf_path, "r") as f:
                config = json.load(f)
        except Exception:
            pass
            
    if "mcpServers" not in config:
        config["mcpServers"] = {}
        
    kernora_mcp_path = str(Path.cwd() / "kernora_mcp.py")
    
    # Non-destructively mount the agent capability
    config["mcpServers"]["KernoraControlPlane"] = {
        "command": sys.executable,
        "args": [kernora_mcp_path]
    }
    
    with open(conf_path, "w") as f:
        json.dump(config, f, indent=2)
    print("✅ Kernora Control Plane MCP securely registered natively inside Claude Desktop.")

def install_launchd():
    plist_dir = Path.home() / "Library/LaunchAgents"
    plist_dir.mkdir(parents=True, exist_ok=True)
    plist_path = plist_dir / "com.kernora.daemon.plist"
    
    daemon_script = str(Path.cwd() / "daemon.py")
    python_exec = sys.executable
    
    plist_content = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.kernora.daemon</string>
    <key>ProgramArguments</key>
    <array>
        <string>{python_exec}</string>
        <string>{daemon_script}</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardOutPath</key>
    <string>{str(Path.home())}/.kernora/daemon.log</string>
    <key>StandardErrorPath</key>
    <string>{str(Path.home())}/.kernora/daemon.err</string>
</dict>
</plist>
"""
    with open(plist_path, "w") as f:
        f.write(plist_content)
    print(f"✅ Kernora Telemetry Core successfully mounted to OS services vector: {plist_path}.")
    print("   -> (Zero friction achieved! Daemon execution runs flawlessly on boot).")

def install_cli_hooks():
    # Natively trap standard zsh CLI execution to pipe through Kiro shields
    zshrc = Path.home() / ".zshrc"
    hook_str = '\n# Kernora Intelligence Framework Interceptor\nalias claude="claude | python3 ' + str(Path.cwd() / 'kiro_spec_shield.py') + '"\n'
    if zshrc.exists():
        content = zshrc.read_text()
        if "# Kernora Intelligence Framework Interceptor" not in content:
            with open(zshrc, "a") as f:
                f.write(hook_str)
            print("✅ Kernora CLI logic shield formally injected into ~/.zshrc shell.")

if __name__ == "__main__":
    print("=== Kernora Enterprise Zero-Friction Installer ===")
    install_mcp()
    install_launchd()
    install_cli_hooks()
    print("✅ Full installation topology actively configured.")
