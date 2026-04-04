import Foundation
import MLXLLM
import MLXLMCommon

// Define the incoming input structure from IDE extension
struct InferenceRequest: Codable {
    let sessionId: String
    let payload: String
}

// Define the outgoing structured JSON format
struct FoundationModelInsights: Codable {
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

func runStdinMode() async throws {
    print("🍏 Kernora MLX Edge Inference Ready. Listening on STDIN...")
    let modelIdentifier = "mlx-community/Qwen2.5-Coder-3B-Instruct-4bit"
    var chatSession: ChatSession? = nil

    while let line = readLine() {
        guard let data = line.data(using: .utf8) else { continue }
        
        do {
            let request = try JSONDecoder().decode(InferenceRequest.self, from: data)
            
            if chatSession == nil {
                print("🔄 Cold-Start: Loading MLX Edge Model (\(modelIdentifier))...")
                let modelContext = try await LLMModelFactory.shared.loadContainer(configuration: ModelConfiguration(id: modelIdentifier))
                chatSession = ChatSession(modelContext)
                print("✅ MLX Model Loaded. Apple Neural Engine Active.")
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
            
            TRANSCRIPT TO EVALUATE:
            \(request.payload)
            """

            print("🧠 Inference running...")
            if let session = chatSession {
                var finalJsonString = try await session.respond(to: metaPrompt)
                finalJsonString = finalJsonString.replacingOccurrences(of: "```json", with: "").replacingOccurrences(of: "```", with: "").trimmingCharacters(in: CharacterSet.whitespacesAndNewlines)

                print("SUCCESS_START")
                print(finalJsonString)
                print("SUCCESS_END")
                fflush(stdout)
            }
        } catch {
            print("ERROR: MLX runtime failure -> (\(error.localizedDescription))")
            fflush(stdout)
        }
    }
}

struct KernoraInferenceService {
    static func main() async throws {
        let args = CommandLine.arguments
        var mode = "server"
        
        for i in 0..<args.count {
            if args[i] == "--mode" && i + 1 < args.count {
                mode = args[i + 1]
            }
        }
        
        if mode == "stdin" {
            try await runStdinMode()
            return
        }
        
        #if canImport(FoundationModels)
        if #available(macOS 26, *) {
            do {
                let srv = try FoundationModelsServer()
                srv.start()
                // Keep the server running
                try await Task.sleep(nanoseconds: UInt64.max)
            } catch {
                print("FoundationModelsServer failed to start: \(error)")
                exit(1)
            }
        } else {
            print("FoundationModels requires macOS 26. Falling back to MLX-LM.")
            do {
                let srv = try MLXServer()
                srv.start()
                try await Task.sleep(nanoseconds: UInt64.max)
            } catch {
                print("MLXServer failed to start: \(error)")
                exit(1)
            }
        }
        #else
        print("FoundationModels framework not found. Falling back to MLX-LM.")
        do {
            let srv = try MLXServer()
            srv.start()
            try await Task.sleep(nanoseconds: UInt64.max)
        } catch {
            print("MLXServer failed to start: \(error)")
            exit(1)
        }
        #endif
    }
}

// Call the entry point using Swift concurrency
Task {
    do {
        try await KernoraInferenceService.main()
    } catch {
        print("Application crashed: \(error)")
        exit(1)
    }
}
dispatchMain()
