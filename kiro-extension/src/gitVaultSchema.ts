export interface KernoraSession {
    id: string; // Unique session ID (e.g., UUID or timestamp hash)
    createdAt: string; // ISO-8601 Timestamp
    ide: 'vscode' | 'cursor' | 'kiro' | 'cli' | 'antigravity'; 
    contextFiles: string[]; // Files touched during this session

    // The Raw Telemetry (What the developer did)
    telemetry: {
        prompts: {
            role: 'user' | 'assistant';
            text: string;
            timestamp: string;
        }[];
        totalTokensEstimated: number;
    };

    // The AI Value-Add (What FoundationModels extracted)
    insights?: {
        themes: string[]; // High level topics (e.g., 'React Hooks', 'Authentication')
        bugsDetected: {
            pattern: string;
            description: string;
            severity: 'low' | 'medium' | 'high';
        }[];
        skillOpportunities: string[];
        promptQualityScore: number; // 1-10
    };
}

export interface KernoraConfig {
    version: string;
    syncEnabled: boolean;
    remoteGitUrl?: string; // e.g., https://github.corp.com/team/kernora-metrics.git
}

// Directory Structure on Disk:
// ~/Documents/KernoraData/
// ├── .git/
// ├── config.json (KernoraConfig)
// └── sessions/
//     └── 2026/
//         └── 04/
//             ├── 2026-04-02T10-15-22.json (KernoraSession)
//             └── 2026-04-02T14-30-00.json
