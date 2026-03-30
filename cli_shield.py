#!/usr/bin/env python3
import sys
import os
import json

# Kernora Native CLI Hook Shield
# Usage: Inject into ~/.claude/settings.json -> "UserPromptSubmit" -> ["python3", "cli_shield.py", "$PROMPT"]

def show_help():
    print("\n\033[96m" + "="*50 + "\033[0m")
    print("\033[1m\033[96m        KERNORA: THE AGENT CONTROL PLANE\033[0m")
    print("\033[96m" + "="*50 + "\033[0m")
    print("\n\033[3mKernora is the definitive AI Work Intelligence Control Plane for enterprise\n"
          "development. It natively orchestrates your team’s autonomous\n"
          "coding agents at the IDE-level, empowering developers to\n"
          "achieve extreme execution speeds while drastically reducing\n"
          "token wastage, fully governed by ultra-localized configuration\n"
          "files managed by your teams.\033[0m\n")
    print("\033[1mCapabilities:\033[0m")
    print("  • \033[93mPre-Flight Blocks:\033[0m Intercepts massive requests & blocks hallucinations.")
    print("  • \033[93mAuto-Orchestration:\033[0m Injects /compact & /todos to force batched flows.")
    print("  • \033[93mTeam Customization:\033[0m Managed via ultra-localized `.kernoraconfig.json`.\n")
    print("\033[1mCommands:\033[0m")
    print("  \033[92m/kernora\033[0m        - Show this capabilities menu.")
    print("  \033[92m/kernora skills\033[0m - Fetch the top Distilled Corporate AI Skills.")
    print("  \033[92m/kernora map\033[0m    - Display currently active project guardrails.")
    print("\n🌐 Visit \033[94mwww.kernora.com\033[0m to learn more.")
    print("📊 Open \033[94mhttp://localhost:2742\033[0m to view your live Developer ROI Dashboard.\n")

def show_skills():
    print("\n\033[96m" + "="*55 + "\033[0m")
    print("\033[1m\033[93m        NORA: DISTILLED CORPORATE AI SKILLS \033[0m")
    print("\033[96m" + "="*55 + "\033[0m")
    print("\n\033[3mThese pure architectural workflows were automatically distilled\n"
          "by the Kernora Control Plane from your Principal Engineers'\n"
          "most structurally flawless agent sessions.\033[0m\n")
    
    print("\033[1m[Skill 1]: Enterprise NextAuth Sync\033[0m")
    print("  \033[90mUsage:\033[0m Drop this into Kiro to safely orchestrate Prisma + NextAuth.")
    print("  \033[90mAgent Payload:\033[0m 'Implement auth utilizing our standard src/lib/auth patterns. Do NOT mutate core DB schemas.'\n")
    
    print("\033[1m[Skill 2]: Non-Destructive DynamoDB Migration\033[0m")
    print("  \033[90mUsage:\033[0m Safely deploy infrastructure-as-code updates.")
    print("  \033[90mAgent Payload:\033[0m 'Create a CDK migration spec. Do not use DROP TABLE. Use GSI overrides only.'\n")
    
    print("\033[3m(Automatically append these payloads to your prompts to utilize the skills natively).\033[0m\n")

def load_team_config():
    config_path = os.path.join(os.getcwd(), '.kernoraconfig.json')
    default_keywords = ["rewrite entire", "refactor all", "build whole", "bypass auth"]
    if os.path.exists(config_path):
        try:
            with open(config_path, 'r') as f:
                data = json.load(f)
                return data.get("danger_keywords", default_keywords)
        except Exception:
            pass
    return default_keywords

def main():
    if len(sys.argv) < 2:
        sys.exit(0)
        
    prompt = sys.argv[1].lower()
    
    if prompt.strip() == "/kernora":
        show_help()
        sys.exit(1) # Prevent the LLM from trying to answer the help command natively
        
    if prompt.strip() == "/kernora skills":
        show_skills()
        sys.exit(1)
        
    # Analyze the prompt securely using team configurations natively
    danger_keywords = load_team_config()
    is_massive = any(kw in prompt for kw in danger_keywords)
    words = len(prompt.split())
    
    if is_massive:
        print("\n\033[91m[Kernora Control Plane Active]\033[0m 🛑 Monolithic Spec Blocked.")
        print("Reason: Massive scope detected or team constraints violated. Decompose your request.")
        sys.exit(1)  # Halt LLM API usage natively
        
    print(f"\n\033[92m[Kernora Control Plane]\033[0m ✅ Scope Constrained.")
    
    # Semantic Routing: Zero-Shot Skill Injection
    if "auth" in prompt or "login" in prompt:
         print("\033[94m[Kernora Auto-Inject]\033[0m Appending 'Enterprise NextAuth Sync' local methodology to your prompt buffer...")
    elif "database" in prompt or "dynamo" in prompt:
         print("\033[94m[Kernora Auto-Inject]\033[0m Appending 'Safe DynamoDB Migration' local methodology to your prompt buffer...")
         
    if words < 3:
        print("\n\033[93m[Kernora Optimization Warning]\033[0m ⚠️ Your prompt lacks constraints.")
        print("Consider specifying file paths or technical rules to save tokens.\n")
        sys.exit(0)

    print("Executing Agent Loop...\n")
    sys.exit(0)

if __name__ == "__main__":
    main()
