// Kernora — AI Work Intelligence
// Elastic License 2.0 — commercial use requires agreement with kernora.ai
// https://github.com/kernora-ai/nora/blob/main/LICENSE
import Foundation

struct AnalyzeRequest: Codable {
    var transcript: String
    var sessionId: String?
}

#if canImport(FoundationModels)
import FoundationModels

@available(macOS 26, *)
@Generable
struct Theme: Codable {
    @Guide(description: "A short, descriptive label for the pattern")
    var label: String
    @Guide(description: "Severity of the theme: 'high', 'medium', or 'low'")
    var severity: String
    @Guide(description: "Number of occurrences")
    var count: Int
}

@available(macOS 26, *)
@Generable
struct Bug: Codable {
    @Guide(description: "A clean title describing the bug")
    var title: String
    @Guide(description: "Severity of the bug: 'high', 'medium', or 'low'")
    var severity: String
    @Guide(description: "Signature or snippet of the code causing the bug")
    var errorSignature: String
    @Guide(description: "The file path where the bug occurs")
    var filePath: String
    @Guide(description: "Suggested code fix for the bug")
    var fixCode: String
}

@available(macOS 26, *)
@Generable
struct Optimization: Codable {
    @Guide(description: "A clean title for the optimization")
    var title: String
    @Guide(description: "Impact of the optimization: 'high', 'medium', or 'low'")
    var impact: String
    @Guide(description: "Specific suggestion on how to optimize")
    var suggestion: String
}

@available(macOS 26, *)
@Generable
struct AnalysisResult: Codable {
    @Guide(description: "Identified themes and patterns")
    var themes: [Theme]
    @Guide(description: "Detected bugs and issues")
    var bugs: [Bug]
    @Guide(description: "Suggested code optimizations")
    var optimizations: [Optimization]
    @Guide(description: "Quality of the prompt on a scale from 0.0 to 1.0")
    var promptQuality: Float
    @Guide(description: "Average word count of the prompts")
    var promptAvgWords: Int
    @Guide(description: "Number of repetitive questions or statements")
    var repetitionCount: Int
    @Guide(description: "A coaching note on skills the developer can improve")
    var skillOpportunity: String
    @Guide(description: "A summary of the overall transcript")
    var summary: String
    @Guide(description: "Direct coaching advice on how to improve prompting")
    var promptCoaching: String
    @Guide(description: "Any observed prompt anti-patterns")
    var promptAntipatterns: [String]
    @Guide(description: "Total estimated tokens used in the session")
    var tokensEstimated: Int
    @Guide(description: "The type of the session (e.g., 'coding', 'debugging', 'planning')")
    var sessionType: String
    @Guide(description: "The knowledge domains covered in the session (e.g., ['python', 'react'])")
    var knowledgeDomains: [String]
}
#endif
