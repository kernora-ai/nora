// testGitVault.ts
import { GitVaultManager } from './gitVault';
import { KernoraSession } from './gitVaultSchema';

async function runTest() {
    console.log("🚀 Starting Kernora Git Vault Test...");
    
    // 1. Initialize the vault manager
    const vault = new GitVaultManager();
    console.log(`📁 Target Vault Directory: ${vault.vaultDir}`);

    // 2. Ensure Git repository is created
    console.log("⚙️  Initializing Vault (git init)...");
    await vault.initializeVault();

    // 3. Create a dummy test session
    const testSession: KernoraSession = {
        id: "test_" + Date.now().toString().slice(-6),
        createdAt: new Date().toISOString(),
        ide: "vscode",
        contextFiles: ["src/app.tsx", "package.json"],
        telemetry: {
            prompts: [
                {
                    role: "user",
                    text: "How do I fix the React hook dependency array here?",
                    timestamp: new Date().toISOString()
                }
            ],
            totalTokensEstimated: 142
        },
        insights: {
            themes: ["react", "debugging"],
            bugsDetected: [
                {
                    pattern: "Missing exhaustive deps",
                    description: "useEffect dependency array missing variables used inside.",
                    severity: "medium"
                }
            ],
            skillOpportunities: ["React Context API refactoring"],
            promptQualityScore: 8.5
        }
    };

    // 4. Save and commit
    console.log(`💾 Saving Session Telemetry: ${testSession.id}...`);
    await vault.saveSessionInsight(testSession);
    
    console.log("\n✅ Test Complete!");
    console.log(`🔍 Try running: 'cd ${vault.vaultDir} && git log' to see your data vault in action.`);
}

runTest().catch(console.error);
