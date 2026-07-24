// Kernora — AI Work Intelligence
// Elastic License 2.0 — commercial use requires agreement with kernora.ai
// https://github.com/kernora-ai/nora/blob/main/LICENSE
import Foundation
#if canImport(FoundationModels)
import FoundationModels

@available(macOS 26, *)
class FoundationModelsServer {
    private let server: MinimalHTTPServer
    
    init() throws {
        self.server = try MinimalHTTPServer(port: 2744)
        
        self.server.requestHandler = { method, path, body in
            if method == "GET" && path == "/health" {
                let resp = ["ok": true, "model": "apple-foundationmodels", "context_window": 4096] as [String : Any]
                let data = try? JSONSerialization.data(withJSONObject: resp)
                return (200, data ?? Data())
            }
            if method == "POST" && path == "/analyze" {
                guard let req = try? JSONDecoder().decode(AnalyzeRequest.self, from: body) else {
                    return (400, Data("{\"error\":\"Invalid request body\"}".utf8))
                }
                if req.transcript.isEmpty {
                    return (400, Data("{\"error\":\"Empty transcript\"}".utf8))
                }
                
                // Do synchronous execution inside the handler queue
                let semaphore = DispatchSemaphore(value: 0)
                var responseData = Data()
                var statusCode = 500
                
                Task {
                    do {
                        let session = LanguageModelSession()
                        let result = try await session.respond(to: req.transcript, generating: AnalysisResult.self)
                        let unified = toUnifiedSchema(result.content)
                        responseData = try JSONSerialization.data(withJSONObject: unified)
                        statusCode = 200
                    } catch {
                        // Fallback to partial empty schema on failure (Requirement 12.4)
                        let fallbackResult = AnalysisResult(
                            themes: [], bugs: [], optimizations: [],
                            promptQuality: 0.0, promptAvgWords: 0, repetitionCount: 0,
                            skillOpportunity: "", summary: "", promptCoaching: "",
                            promptAntipatterns: [], tokensEstimated: 0,
                            sessionType: "", knowledgeDomains: []
                        )
                        let unified = toUnifiedSchema(fallbackResult)
                        responseData = try! JSONSerialization.data(withJSONObject: unified)
                        statusCode = 200
                    }
                    semaphore.signal()
                }
                
                // Timeout logic
                let result = semaphore.wait(timeout: .now() + 30.0)
                if result == .timedOut {
                    return (503, Data("{\"error\":\"timeout\"}".utf8))
                }
                
                return (statusCode, responseData)
            }
            return (404, Data("{\"error\":\"Not found\"}".utf8))
        }
    }
    
    func start() {
        self.server.start()
    }
}
#endif
