// Kernora — AI Work Intelligence
// Elastic License 2.0 — commercial use requires agreement with kernora.ai
// https://github.com/kernora-ai/nora/blob/main/LICENSE
import Foundation

#if canImport(FoundationModels)
@available(macOS 26, *)
func toUnifiedSchema(_ r: AnalysisResult) -> [String: Any] {
    var dict: [String: Any] = [:]
    
    let mappedThemes = r.themes.map { t in
        ["label": t.label, "severity": t.severity, "count": t.count]
    }
    dict["themes"] = mappedThemes
    
    let mappedBugs = r.bugs.map { b in
        ["title": b.title, "severity": b.severity, "error_signature": b.errorSignature, "file_path": b.filePath, "fix_code": b.fixCode]
    }
    dict["bugs"] = mappedBugs
    
    let mappedOps = r.optimizations.map { o in
        ["title": o.title, "impact": o.impact, "suggestion": o.suggestion]
    }
    dict["optimizations"] = mappedOps
    
    dict["prompt_quality"] = r.promptQuality
    dict["prompt_avg_words"] = r.promptAvgWords
    dict["repetition_count"] = r.repetitionCount
    dict["skill_opportunity"] = r.skillOpportunity
    dict["summary"] = r.summary
    dict["prompt_coaching"] = r.promptCoaching
    dict["prompt_antipatterns"] = r.promptAntipatterns
    dict["tokens_estimated"] = r.tokensEstimated
    dict["session_type"] = r.sessionType
    dict["knowledge_domains"] = r.knowledgeDomains
    
    // Default fields
    dict["playbook"] = ""
    dict["architectural_decisions"] = []
    dict["anti_patterns"] = []
    dict["claude_md_rules"] = []
    dict["reusable_patterns"] = []
    dict["files_touched"] = []
    dict["tools_used"] = []
    dict["agent_workflow_rules"] = []
    dict["model_used"] = "local/apple-foundationmodels"
    
    return dict
}
#endif
