import * as fs from 'fs';
import * as path from 'path';
import * as os from 'os';
import { exec } from 'child_process';
import { promisify } from 'util';
import { KernoraSession } from './gitVaultSchema';

const execAsync = promisify(exec);

export class GitVaultManager {
    public readonly vaultDir: string;

    constructor() {
        // We default to a highly visible, trusted location for the user.
        this.vaultDir = path.join(os.homedir(), 'Documents', 'KernoraData');
    }

    /**
     * Ensures the vault directory exists and is initialized as a Git repository (if enabled).
     */
    public async initializeVault(): Promise<void> {
        const configPath = path.join(os.homedir(), '.kernora', 'config.toml');
        const isGitEnabled = fs.existsSync(configPath) && fs.readFileSync(configPath, 'utf8').includes('git');
        
        if (!isGitEnabled) {
            return;
        }
        if (!fs.existsSync(this.vaultDir)) {
            fs.mkdirSync(this.vaultDir, { recursive: true });
            
            // Generate standard empty config file
            const configPath = path.join(this.vaultDir, 'config.json');
            fs.writeFileSync(configPath, JSON.stringify({
                version: "1.0",
                syncEnabled: false
            }, null, 4));
        }

        const gitDir = path.join(this.vaultDir, '.git');
        if (!fs.existsSync(gitDir)) {
            try {
                await execAsync('git init', { cwd: this.vaultDir });
                // Initial commit
                await execAsync('git add config.json', { cwd: this.vaultDir });
                await execAsync('git commit -m "Initialize Kernora Local Data Vault"', { cwd: this.vaultDir });
                console.log('✅ Kernora Local Git Vault initialized at:', this.vaultDir);
            } catch (err) {
                console.error('Failed to initialize git repository in KernoraData:', err);
            }
        }
    }

    /**
     * Saves a session to a daily JSON file and creates a discrete Git commit (if enabled).
     */
    public async saveSessionInsight(session: KernoraSession): Promise<void> {
        const configPath = path.join(os.homedir(), '.kernora', 'config.toml');
        const isGitEnabled = fs.existsSync(configPath) && fs.readFileSync(configPath, 'utf8').includes('git');
        
        if (!isGitEnabled) {
            console.log(`✅ Session ${session.id} successfully secured in SQLite vault.`);
            return;
        }

        // Structure: sessions/YYYY/MM/DD.json
        const dateObj = new Date(session.createdAt);
        const year = dateObj.getUTCFullYear().toString();
        const month = String(dateObj.getUTCMonth() + 1).padStart(2, '0');
        const day = String(dateObj.getUTCDate()).padStart(2, '0');

        const sessionFolder = path.join(this.vaultDir, 'sessions', year, month);
        if (!fs.existsSync(sessionFolder)) {
            fs.mkdirSync(sessionFolder, { recursive: true });
        }

        const filename = `${year}-${month}-${day}-session-${session.id}.json`;
        const filePath = path.join(sessionFolder, filename);

        // Prettify the JSON so developers can read their own telemetry cleanly
        fs.writeFileSync(filePath, JSON.stringify(session, null, 4));

        try {
            await execAsync(`git add "sessions/${year}/${month}/${filename}"`, { cwd: this.vaultDir });
            
            // Create a descriptive audit trail inside the user's local git log
            const commitMessage = `📝 Recorded Kernora Insight (${session.ide}): Session ${session.id}`;
            await execAsync(`git commit -m "${commitMessage}"`, { cwd: this.vaultDir });
            console.log(`✅ Session ${session.id} successfully secured in Git vault.`);
        } catch (err) {
            console.error('Failed to commit session insights to git:', err);
        }
    }
}
