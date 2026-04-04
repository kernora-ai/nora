// Kernora — AI Work Intelligence
// Elastic License 2.0 — commercial use requires agreement with kernora.ai
// https://github.com/kernora-ai/nora/blob/main/LICENSE
import Foundation
import MLXLLM
import MLXLMCommon

class MLXServer {
    private let server: MinimalHTTPServer
    private var chatSession: ChatSession? = nil
    private var isDownloading: Bool = false
    private let modelIdentifier = "mlx-community/Qwen2.5-Coder-3B-Instruct-4bit"
    
    init() throws {
        self.server = try MinimalHTTPServer(port: 2745)
        
        self.server.requestHandler = { [weak self] method, path, body in
            guard let self = self else { return (500, Data()) }
            
            if method == "GET" && path == "/health" {
                if self.isDownloading {
                    let resp: [String: Any] = ["ok": true, "model": "Qwen2.5-Coder-3B", "context_window": 8192, "downloading": true, "progress": 0.5]
                    let data = try? JSONSerialization.data(withJSONObject: resp)
                    return (200, data ?? Data())
                } else {
                    let resp: [String: Any] = ["ok": true, "model": "Qwen2.5-Coder-3B", "context_window": 8192]
                    let data = try? JSONSerialization.data(withJSONObject: resp)
                    return (200, data ?? Data())
                }
            }
            if method == "POST" && path == "/analyze" {
                if self.isDownloading {
                    return (503, Data("{\"error\":\"model_downloading\", \"progress\": 0.5}".utf8))
                }
                
                guard let req = try? JSONDecoder().decode(AnalyzeRequest.self, from: body) else {
                    return (400, Data("{\"error\":\"Invalid request body\"}".utf8))
                }
                
                let semaphore = DispatchSemaphore(value: 0)
                var responseData = Data()
                var statusCode = 500
                
                Task {
                    do {
                        if self.chatSession == nil {
                            self.isDownloading = true
                            print("🔄 Loading MLX Edge Model (\(self.modelIdentifier))...")
                            let modelContext = try await LLMModelFactory.shared.loadContainer(configuration: ModelConfiguration(id: self.modelIdentifier))
                            self.chatSession = ChatSession(modelContext)
                            self.isDownloading = false
                            print("✅ MLX Model Loaded.")
                        }
                        
                        let metaPrompt = """
                        You are Kernora AI, an advanced pair programming evaluator. Analyze the user's transcript and generate exactly one valid JSON object with the following schema:
                        {
                           "themes": ["string"],
                           "bugsDetected": [{"pattern": "string", "description": "string", "severity": "low|medium|high"}],
                           "skillOpportunities": ["string"],
                           "promptQualityScore": float (1.0 to 10.0)
                        }
                        Do not include markdown tags or explanation. Just the JSON.
                        TRANSCRIPT: \(req.transcript)
                        """
                        
                        var finalJsonString = try await self.chatSession!.respond(to: metaPrompt)
                        finalJsonString = finalJsonString.replacingOccurrences(of: "```json", with: "").replacingOccurrences(of: "```", with: "").trimmingCharacters(in: .whitespacesAndNewlines)
                        
                        if let dict = try? JSONSerialization.jsonObject(with: Data(finalJsonString.utf8)) as? [String: Any] {
                            let unified = mapLegacyToUnified(dict)
                            responseData = try JSONSerialization.data(withJSONObject: unified)
                            statusCode = 200
                        } else {
                            // Fallback exactly to empty schema
                            let unified = mapLegacyToUnified([:])
                            responseData = try JSONSerialization.data(withJSONObject: unified)
                            statusCode = 200
                        }
                    } catch {
                        self.isDownloading = false
                        let unified = mapLegacyToUnified([:])
                        responseData = try! JSONSerialization.data(withJSONObject: unified)
                        statusCode = 200
                    }
                    semaphore.signal()
                }
                
                let result = semaphore.wait(timeout: .now() + 60.0)
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
