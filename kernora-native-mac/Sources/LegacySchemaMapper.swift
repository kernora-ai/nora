// Kernora — AI Work Intelligence
// Elastic License 2.0 — commercial use requires agreement with kernora.ai
// https://github.com/kernora-ai/nora/blob/main/LICENSE
import Foundation

// Old struct used by MLX
struct MLXInsights: Codable {
    let themes: [String]
    let bugsDetected: [BugEntry]
    let skillOpportunities: [String]
    let promptQualityScore: Double

    struct BugEntry: Codable {
        let pattern: String
        let description: String
        let severity: String
    }
}

func mapLegacyToUnified(_ raw: [String: Any]) -> [String: Any] {
    var unified: [String: Any] = [:]
    
    // Default safe parsing
    let themes = raw["themes"] as? [String] ?? []
    unified["themes"] = themes.map { label in
        ["label": label, "severity": "medium", "count": 1]
    }
    
    let oldBugs = raw["bugsDetected"] as? [[String: Any]] ?? []
    unified["bugs"] = oldBugs.map { bug in
        [
            "title": bug["description"] as? String ?? "",
            "severity": bug["severity"] as? String ?? "medium",
            "error_signature": bug["pattern"] as? String ?? "",
            "file_path": "",
            "fix_code": ""
        ]
    }
    
    let skills = raw["skillOpportunities"] as? [String] ?? []
    unified["optimizations"] = skills.map { skill in
        ["title": skill, "impact": "medium", "suggestion": ""]
    }
    
    let quality = raw["promptQualityScore"] as? Double ?? 0.0
    // Quality is 1..10 in old model, we need 0..1
    let unifiedQuality = min(max(quality / 10.0, 0.0), 1.0)
    unified["prompt_quality"] = unifiedQuality
    
    // Fill required unify fields
    unified["prompt_avg_words"] = 0
    unified["repetition_count"] = 0
    unified["skill_opportunity"] = skills.first ?? ""
    unified["summary"] = ""
    unified["prompt_coaching"] = ""
    unified["prompt_antipatterns"] = []
    unified["tokens_estimated"] = 0
    unified["session_type"] = "coding"
    unified["knowledge_domains"] = []
    
    unified["playbook"] = ""
    unified["architectural_decisions"] = []
    unified["anti_patterns"] = []
    unified["claude_md_rules"] = []
    unified["reusable_patterns"] = []
    unified["files_touched"] = []
    unified["tools_used"] = []
    unified["agent_workflow_rules"] = []
    unified["model_used"] = "local/mlx-qwen2.5-coder-3b"
    
    return unified
}
