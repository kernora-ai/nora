import * as vscode from 'vscode';
import { spawn, execSync, ChildProcess, exec } from 'child_process';
import * as fs from 'fs';
import * as os from 'os';
import * as path from 'path';
import * as http from 'http';
import { promisify } from 'util';
import { GitVaultManager } from './gitVault';
import { SwiftInferenceProxy } from './swiftProxy';
import { KernoraSession } from './gitVaultSchema';

const execAsync = promisify(exec);
let serverProcess: ChildProcess | undefined;

const KERNORA_DIR = path.join(os.homedir(), '.kernora');
const APP_DIR = path.join(KERNORA_DIR, 'app');
const VENV_DIR = path.join(KERNORA_DIR, 'venv');
const isWin = os.platform() === 'win32';
const PYTHON = path.join(VENV_DIR, isWin ? 'Scripts' : 'bin', isWin ? 'python.exe' : 'python3');
const PIP = path.join(VENV_DIR, isWin ? 'Scripts' : 'bin', isWin ? 'pip.exe' : 'pip');
const DASHBOARD = path.join(APP_DIR, 'dashboard.py');

// Auto-approve list. Must mirror the Tool(name="...") registrations in
// nora_mcp.py exactly — drift causes the IDE to prompt-on-tool-call instead
// of silently invoking, destroying the "ambient knowledge" UX.
//
// Ground truth: `grep -oE 'name="nora_[a-z_]+"' nora_mcp.py | sort -u`
// Last reconciled: 2026-05-10 (Task #385). Count: 45 tools.
//
// Alias entries (nora_sofac, nora_engineering_health) are KEPT per factbook
// f255 (alias-retention pattern, 2026-04-25): they are registered Tool()
// objects in nora_mcp.py that route to the same handler as nora_status.
// Removing them would cause the IDE to prompt-on-call for users whose
// steering files reference the legacy names.
const NORA_TOOLS = [
    // retrieval + read-only history
    "nora_search", "nora_patterns", "nora_decisions", "nora_bugs",
    "nora_stats", "nora_session", "nora_skills", "nora_status",
    "nora_help", "nora_inventory", "nora_roi",
    "nora_engineering_health",  // alias of nora_status (f255)
    // scoped retrieval + context-for-task
    "nora_context_for_task", "nora_scope_validation",
    // factbook reads + edits
    "nora_factbook", "nora_factbook_view", "nora_factbook_verify",
    "nora_factbook_inject", "nora_factbook_promote", "nora_factbook_audit",
    "nora_factbook_add", "nora_factbook_import",
    "nora_factbook_ingest_propose",
    "nora_factbook_ingest_submit",
    "nora_provenance",  // alias of nora_factbook(action='provenance')
    // capture (live + post-session)
    "nora_capture_pending", "nora_capture_accept", "nora_capture_reject",
    // extraction (scans project root + calls LLM to produce candidate facts)
    "nora_extract",
    // workflows (3-stage start/submit/finalize patterns)
    "nora_pe_review", "nora_coe", "nora_coe_start", "nora_coe_submit",
    "nora_coe_finalize", "nora_coe_product", "nora_retro",
    "nora_sofac",               // alias of nora_status (f255)
    // generators + advisors
    "nora_generate", "nora_coach", "nora_onboard", "nora_consolidate",
    "nora_consolidate_apply", "nora_retire_fact", "nora_retire_undo",
    // bridges
    "nora_claude_memory", "nora_rate_context",
];

// ── Structured logging ────────────────────────────────────────────────────
const log = {
    info: (msg: string) => console.log(`[kernora] ${msg}`),
    warn: (msg: string) => console.warn(`[kernora] ⚠ ${msg}`),
    error: (msg: string) => console.error(`[kernora] ✖ ${msg}`),
};

// ── Startup drift check ────────────────────────────────────────────────────
// Reads ~/.kernora/app/nora_mcp.py and greps for Tool(name="...") entries.
// Logs a warning for any stale (NORA_TOOLS has it, registry does not) or
// missing (registry has it, NORA_TOOLS does not) entry. Fires once per
// activation; skipped if nora_mcp.py is not yet installed.
function checkToolsDrift(): void {
    const mcpPy = path.join(APP_DIR, 'nora_mcp.py');
    if (!fs.existsSync(mcpPy)) {
        return; // not installed yet — skip silently
    }
    try {
        const src = fs.readFileSync(mcpPy, 'utf8');
        const re = /name\s*=\s*"(nora_[a-z_]+)"/g;
        const registrySet = new Set<string>();
        let m: RegExpExecArray | null;
        while ((m = re.exec(src)) !== null) {
            registrySet.add(m[1]);
        }
        const arraySet = new Set(NORA_TOOLS);
        const stale: string[] = [];
        const missing: string[] = [];
        for (const t of arraySet) {
            if (!registrySet.has(t)) stale.push(t);
        }
        for (const t of registrySet) {
            if (!arraySet.has(t)) missing.push(t);
        }
        if (stale.length > 0) {
            log.warn(`NORA_TOOLS drift — stale (remove from array): ${stale.join(', ')}`);
        }
        if (missing.length > 0) {
            log.warn(`NORA_TOOLS drift — missing (add to array): ${missing.join(', ')}`);
        }
        if (stale.length === 0 && missing.length === 0) {
            log.info(`NORA_TOOLS in sync with registry (${arraySet.size} tools)`);
        }
    } catch (err) {
        log.warn(`checkToolsDrift: could not read nora_mcp.py — ${err}`);
    }
}

// ── IDE detection ──────────────────────────────────────────────────────────
function detectIDE(): 'kiro' | 'cursor' | 'vscode' | 'antigravity' {
    const name = (vscode.env.appName ?? '').toLowerCase();
    if (name.includes('kiro')) return 'kiro';
    if (name.includes('cursor')) return 'cursor';
    if (name.includes('antigravity') || process.env.ANTIGRAVITY_AGENT) return 'antigravity';
    return 'vscode';
}

// ── Sync bundled Python files to ~/.kernora/app/ on every activation ──────
// ALSO writes mcp.json immediately so kiro-cli has it before bootstrap finishes.
// SEC1 (2026-04-19): dev-mode guard — if ~/.kernora/app/ is a symlink to the
// developer's source tree, we MUST NOT copy bundled .py files over it. Doing
// so silently overwrites in-progress work and reverts committed fixes whenever
// the user opens Kiro/Cursor. Compare extension version against current app
// version; if the extension is older, abort the copy with a warning.
function syncBundledFiles(extensionPath: string): boolean {
    const bundledDir = path.join(extensionPath, 'bundled');
    if (!fs.existsSync(bundledDir)) {
        log.error('bundled/ directory missing from extension package');
        return false;
    }

    const files = fs.readdirSync(bundledDir).filter(f => f.endsWith('.py') || f.endsWith('.sh'));
    if (files.length === 0) {
        log.error('bundled/ directory is empty — no Python files to sync');
        return false;
    }

    // Dev-mode guard: skip the copy if APP_DIR is a symlink.
    try {
        if (fs.existsSync(APP_DIR) && fs.lstatSync(APP_DIR).isSymbolicLink()) {
            log.warn(
                `dev mode: ~/.kernora/app/ is a symlink to ${fs.realpathSync(APP_DIR)}. ` +
                'Skipping bundled-file copy so source-tree changes are preserved.'
            );
            registerUniversalMcpServers();
            return true;
        }
    } catch (err) {
        log.warn(`dev-mode check failed (${err}); proceeding with normal copy.`);
    }

    // Version guard: only overwrite APP_DIR files when the extension's version
    // is >= the version already installed. Protects users who ran `kernora
    // install` from a newer source checkout from having their upgrade clobbered
    // by an older VSIX on IDE startup.
    let extensionVersion = 'unknown';
    try {
        const pkg = JSON.parse(fs.readFileSync(path.join(extensionPath, 'package.json'), 'utf-8'));
        extensionVersion = pkg.version ?? 'unknown';
    } catch { /* ignore */ }

    try {
        const installedVersionFile = path.join(APP_DIR, '.version');
        if (fs.existsSync(installedVersionFile)) {
            const installed = fs.readFileSync(installedVersionFile, 'utf-8').trim();
            if (installed && installed !== 'unknown' && extensionVersion !== 'unknown') {
                if (compareVersion(extensionVersion, installed) < 0) {
                    log.warn(
                        `Extension v${extensionVersion} is older than installed v${installed}. ` +
                        'Skipping overwrite — user has a newer install.'
                    );
                    registerUniversalMcpServers();
                    return true;
                }
            }
        }
    } catch (err) {
        log.warn(`version-guard check failed (${err}); proceeding with normal copy.`);
    }

    fs.mkdirSync(APP_DIR, { recursive: true });
    let synced = 0;
    for (const file of files) {
        const dest = path.join(APP_DIR, file);
        try {
            fs.copyFileSync(path.join(bundledDir, file), dest);
        } catch (err: any) {
            // EPERM/EACCES when dest is read-only or a hardlinked/same-inode case
            log.warn(`Skipped ${file}: ${err?.message ?? err}`);
            continue;
        }
        if (file.endsWith('.sh')) {
            try { fs.chmodSync(dest, 0o755); } catch { }
        }
        synced++;
    }

    try {
        fs.writeFileSync(path.join(APP_DIR, '.version'), extensionVersion);
    } catch { /* ignore */ }

    log.info(`Synced ${synced} files to ~/.kernora/app/ (ext v${extensionVersion})`);

    // Write MCP configuration early across ecosystems.
    registerUniversalMcpServers();
    return true;
}

// Compare semver strings "a" vs "b" — returns <0, 0, >0.
// Tolerates unknown/missing components by treating them as 0.
function compareVersion(a: string, b: string): number {
    const pa = a.split('.').map(x => parseInt(x, 10) || 0);
    const pb = b.split('.').map(x => parseInt(x, 10) || 0);
    const n = Math.max(pa.length, pb.length);
    for (let i = 0; i < n; i++) {
        const ai = pa[i] ?? 0;
        const bi = pb[i] ?? 0;
        if (ai !== bi) return ai - bi;
    }
    return 0;
}

// ── MCP Registration ──────────────────────────────────────────────────────────
function registerUniversalMcpServers(): void {
    const mcpConfigBlock = {
        command: PYTHON,
        args: [path.join(APP_DIR, 'nora_mcp.py')],
        autoApprove: NORA_TOOLS,
    };

    const writeMcpToPath = (configPath: string) => {
        try {
            const dir = path.dirname(configPath);
            if (!fs.existsSync(dir)) fs.mkdirSync(dir, { recursive: true });
            
            let cfg: any = {};
            if (fs.existsSync(configPath)) {
                try { cfg = JSON.parse(fs.readFileSync(configPath, 'utf-8')); } 
                catch (err) { 
                    log.error(`Aborting MCP registration: ${configPath} is malformed JSON.`);
                    return;
                }
                // Backup before merge-write so we never lose other servers.
                try {
                    fs.copyFileSync(configPath, configPath + '.bak');
                } catch (bakErr) {
                    log.warn(`Could not backup ${configPath}: ${bakErr}`);
                }
            }
            if (!cfg.mcpServers) cfg.mcpServers = {};
            cfg.mcpServers.nora = mcpConfigBlock;
            fs.writeFileSync(configPath, JSON.stringify(cfg, null, 2));
        } catch (err) {
            log.warn(`Failed to write MCP to ${configPath}: ${err}`);
        }
    };

    // 1. Core/Universal (.kernora/mcp.json)
    writeMcpToPath(path.join(KERNORA_DIR, 'mcp.json'));

    // 2. Kiro CLI
    writeMcpToPath(path.join(os.homedir(), '.kiro', 'settings', 'mcp.json'));

    // 3. Claude Desktop
    const platform = os.platform();
    if (platform === 'darwin') {
        writeMcpToPath(path.join(os.homedir(), 'Library', 'Application Support', 'Claude', 'claude_desktop_config.json'));
    } else if (platform === 'win32') {
        const appData = process.env.APPDATA || path.join(os.homedir(), 'AppData', 'Roaming');
        writeMcpToPath(path.join(appData, 'Claude', 'claude_desktop_config.json'));
    }

    // 4. Claude Code (CLI) Global Config
    writeMcpToPath(path.join(os.homedir(), '.claude.json'));

    // 5. Cursor Native MCP
    writeMcpToPath(path.join(os.homedir(), '.cursor', 'mcp.json'));

    // 6. Antigravity (Gemini) — detected as an IDE but previously never configured
    writeMcpToPath(path.join(os.homedir(), '.gemini', 'antigravity', 'mcp_config.json'));

    log.info('Universal MCP servers registered');
}

// ── Bootstrap: create venv, install deps, init DB ──────────────────────────

/**
 * Determines if bootstrap is needed. Checks 3 things:
 * 1. venv python3 exists
 * 2. echo.db exists
 * 3. Critical imports (mcp, flask) work
 *
 * Also detects half-created venvs (python exists but pip fails).
 */
async function needsBootstrap(): Promise<boolean> {
    if (!fs.existsSync(PYTHON)) {
        log.info('Bootstrap needed: venv python3 not found');
        return true;
    }
    if (!fs.existsSync(path.join(KERNORA_DIR, 'echo.db'))) {
        log.info('Bootstrap needed: echo.db not found');
        return true;
    }
    // COE: venv may be stale after reinstall. Verify critical imports work.
    try {
        await execAsync(`"${PYTHON}" -c "import mcp, flask"`, { timeout: 10000 });
        log.info('Bootstrap not needed: venv healthy, db exists');
        return false;
    } catch {
        log.warn('Bootstrap needed: venv exists but imports failed (stale venv)');
        return true;
    }
}

async function bootstrap(extensionPath: string): Promise<{ ok: boolean; error?: string }> {
    try {
        let sysPython = 'python3';
        // Step 1: Check Python 3 is available
        try {
            const { stdout } = await execAsync('python3 --version');
            log.info(`System Python: ${stdout.trim()}`);
        } catch {
            try {
                sysPython = 'python';
                const { stdout } = await execAsync('python --version');
                log.info(`System Python: ${stdout.trim()}`);
            } catch {
                return { ok: false, error: 'Python 3 not found. Install from https://python.org' };
            }
        }

        // Step 2: Create directories
        fs.mkdirSync(APP_DIR, { recursive: true });
        fs.mkdirSync(path.join(KERNORA_DIR, 'logs'), { recursive: true });
        log.info('Directories created');

        // Step 3: Create or recreate venv
        // COE #4/#8: If venv is half-created (interrupted bootstrap), nuke it and start fresh.
        if (fs.existsSync(VENV_DIR)) {
            log.warn('Stale venv detected — removing and recreating');
            fs.rmSync(VENV_DIR, { recursive: true, force: true });
        }
        if (!fs.existsSync(PYTHON)) {
            log.info('Creating venv...');
            await execAsync(`"${sysPython}" -m venv "${VENV_DIR}"`, { timeout: 60000 });
            log.info('Venv created');
        }

        // Step 4: Install dependencies
        log.info('Installing dependencies (flask, mcp, litellm, anthropic)...');
        await execAsync(`"${PIP}" install flask mcp litellm anthropic --quiet`, { timeout: 300000 });
        log.info('Dependencies installed');

        // Step 5: Verify imports work (catch broken pip installs)
        try {
            await execAsync(`"${PYTHON}" -c "import mcp, flask"`, { timeout: 10000 });
            log.info('Import verification passed');
        } catch {
            return { ok: false, error: 'Dependencies installed but imports failed. Try: rm -rf ~/.kernora/venv and reload.' };
        }

        // Step 6: Write config
        const configPath = path.join(KERNORA_DIR, 'config.toml');
        if (!fs.existsSync(configPath)) {
            fs.writeFileSync(configPath, `[mode]\ntype = "byok"\n\n[model]\nprovider = "anthropic"\n\n[storage]\nengine = "sqlite"\n\n[analysis]\nrun_every_minutes = 60\n\n[dashboard]\nport = 2742\nauto_open = true\n\n[privacy]\nverified = true\n`);
            log.info('Config written');
        }

        // Step 7: Init database
        const dbInit = path.join(APP_DIR, 'db.py');
        if (fs.existsSync(dbInit)) {
            await execAsync(`"${PYTHON}" "${dbInit}"`, { timeout: 10000 });
            log.info('Database initialized');
        } else {
            log.warn('db.py not found in app dir — database not initialized');
        }

        // Verify db was actually created
        if (!fs.existsSync(path.join(KERNORA_DIR, 'echo.db'))) {
            return { ok: false, error: 'Bootstrap completed but echo.db was not created. Check db.py.' };
        }

        log.info('Bootstrap complete');
        return { ok: true };
    } catch (err: any) {
        log.error(`Bootstrap failed: ${err.message ?? String(err)}`);
        return { ok: false, error: err.message ?? String(err) };
    }
}

// ── Dashboard ──────────────────────────────────────────────────────────────
async function checkDashboardAlive(port: number): Promise<boolean> {
    return new Promise((resolve) => {
        const req = http.get(`http://127.0.0.1:${port}/`, (res) => {
            resolve(res.statusCode !== undefined);
            res.resume();
        });
        req.on('error', () => resolve(false));
        req.setTimeout(2000, () => {
            req.destroy();
            resolve(false);
        });
    });
}

async function shutdownDashboard(port: number): Promise<void> {
    return new Promise((resolve) => {
        const req = http.request(`http://127.0.0.1:${port}/api/shutdown`, { method: 'POST' }, (res) => {
            res.resume();
            resolve();
        });
        req.on('error', () => resolve());
        req.setTimeout(2000, () => {
            req.destroy();
            resolve();
        });
        req.end();
    });
}

async function startDashboard(forceRestart: boolean = false): Promise<boolean> {
    if (!fs.existsSync(PYTHON)) {
        log.error('Cannot start dashboard: venv python3 not found');
        return false;
    }
    if (!fs.existsSync(DASHBOARD)) {
        log.error('Cannot start dashboard: dashboard.py not found');
        return false;
    }

    if (forceRestart) {
        log.info('Force restart requested. Attempting graceful shutdown of existing dashboard...');
        await shutdownDashboard(2742);
        // Wait a moment for to exit
        await new Promise(r => setTimeout(r, 1000));
    }

    const lockFile = path.join(KERNORA_DIR, '.dashboard.lock');
    try {
        fs.mkdirSync(lockFile);
    } catch (err: any) {
        if (err.code === 'EEXIST') {
            log.info('Dashboard spawn lock held by another process. Waiting...');
            for (let i = 0; i < 15; i++) {
                if (await checkDashboardAlive(2742)) {
                    log.info('Dashboard became alive (spawned by peer).');
                    return true;
                }
                await new Promise(r => setTimeout(r, 1000));
            }
            log.warn('Lock held but dashboard never started. Proceeding anyway...');
            try { fs.rmdirSync(lockFile); } catch { }
        }
    }

    try {
        const isAlive = await checkDashboardAlive(2742);
        if (isAlive) {
            log.info('Dashboard is already alive on port 2742 (daemon).');
            try { fs.rmdirSync(lockFile); } catch { }
            return true;
        }

        log.info('Starting dashboard on port 2742...');
        const logDir = path.join(KERNORA_DIR, 'logs');
        if (!fs.existsSync(logDir)) fs.mkdirSync(logDir, { recursive: true });
        
        const outFd = fs.openSync(path.join(logDir, 'dashboard.out.log'), 'a');
        const errFd = fs.openSync(path.join(logDir, 'dashboard.err.log'), 'a');

        // FIX #5/Phase5: detached + physical unbuffered logs + windowsHide to block cmd popups
        serverProcess = spawn(PYTHON, [DASHBOARD], {
            env: { ...process.env, PYTHONUNBUFFERED: '1', KERNORA_IDE: detectIDE() },
            detached: true,
            windowsHide: true,
            stdio: ['ignore', outFd, errFd],
        });

        serverProcess.on('exit', (code) => {
            log.warn(`Dashboard exited with code ${code}`);
            serverProcess = undefined;
        });
        serverProcess.unref();

        // Release the lock defensively
        setTimeout(() => { try { fs.rmdirSync(lockFile); } catch { } }, 3000);

        return true;
    } catch (err: any) {
        try { fs.rmdirSync(lockFile); } catch { }
        log.error(`Failed to spawn dashboard: ${err.message}`);
        return false;
    }
}

// ── Steering files ─────────────────────────────────────────────────────────
async function generateInitialSteeringFiles(): Promise<void> {
    if (!fs.existsSync(PYTHON)) return;
    const sw = path.join(APP_DIR, 'steering_writer.py');
    if (!fs.existsSync(sw)) return;
    try { await execAsync(`"${PYTHON}" "${sw}"`, { timeout: 10000 }); }
    catch { /* no data yet — fine */ }
}

// ── Claude Code hooks ─────────────────────────────────────────────────────
// Copies nora_session_start.py to ~/.claude/hooks/ and registers it in
// ~/.claude/settings.json so Claude Code picks it up on every session.
function installClaudeCodeHooks(): void {
    try {
        const claudeHookDir = path.join(os.homedir(), '.claude', 'hooks');
        fs.mkdirSync(claudeHookDir, { recursive: true });

        // Copy session start hook
        const src = path.join(APP_DIR, 'nora_session_start.py');
        const dest = path.join(claudeHookDir, 'nora_session_start.py');
        if (fs.existsSync(src)) {
            fs.copyFileSync(src, dest);
            try { fs.chmodSync(dest, 0o755); } catch { }
            log.info('Claude Code hook installed: nora_session_start.py');
        } else {
            log.warn('nora_session_start.py not found in app dir — skipping Claude Code hook');
            return;
        }

        // Register in ~/.claude/settings.json
        const claudeSettingsPath = path.join(os.homedir(), '.claude', 'settings.json');
        let claudeSettings: any = {};
        if (fs.existsSync(claudeSettingsPath)) {
            try { claudeSettings = JSON.parse(fs.readFileSync(claudeSettingsPath, 'utf-8')); }
            catch (err) { 
                log.error(`Aborting Claude Code hook install: ${claudeSettingsPath} is malformed JSON.`);
                return;
            }
        }
        if (!claudeSettings.hooks) { claudeSettings.hooks = {}; }

        // SessionStart: run nora_session_start.py once per session (not per tool call).
        // was PreToolUse — corrected to SessionStart (cleanup_settings.py remediation retired)
        const hookCmd = `"${PYTHON}" "${dest}"`;
        if (!Array.isArray(claudeSettings.hooks.SessionStart)) {
            claudeSettings.hooks.SessionStart = [];
        }
        // Remove stale Nora entries, re-add fresh
        claudeSettings.hooks.SessionStart = claudeSettings.hooks.SessionStart.filter(
            (h: any) => !JSON.stringify(h).includes('nora_session_start')
        );
        claudeSettings.hooks.SessionStart.push({
            hooks: [{ type: 'command', command: hookCmd }],
        });

        fs.writeFileSync(claudeSettingsPath, JSON.stringify(claudeSettings, null, 2));
        log.info('Claude Code hooks registered in ~/.claude/settings.json');
    } catch (err: any) {
        log.warn(`Claude Code hook install skipped: ${err.message}`);
    }
}

// ── Hooks + MCP: ALL in settings.json (original working approach) ──────────
// The original v1.4.0 registered MCP in settings.json alongside hooks.
// This works because Kiro App reads settings.json at startup for both hooks
// AND mcpServers. No separate mcp.json, no race condition, no kiro-cli sync.
function installAndRegisterKiroHooks(): void {
    const hookDir = path.join(os.homedir(), '.kiro', 'hooks');
    fs.mkdirSync(hookDir, { recursive: true });

    const hookMap: Record<string, string> = {
        'nora_context.py': 'nora_context.py',
        'kiro_agent_spawn.py': 'nora_spawn.py',
        'kiro_spec_shield.py': 'nora_pretool.py',
        'kiro_post_tool.py': 'nora_posttool.py',
        'hook.py': 'nora_stop.py',
    };

    for (const [src, dest] of Object.entries(hookMap)) {
        const srcPath = path.join(APP_DIR, src);
        const destPath = path.join(hookDir, dest);
        if (fs.existsSync(srcPath)) {
            fs.copyFileSync(srcPath, destPath);
            try { fs.chmodSync(destPath, 0o755); } catch { }
        }
    }

    // ── Register EVERYTHING in settings.json: hooks + MCP + autoApprove ────
    const settingsPath = path.join(os.homedir(), '.kiro', 'settings.json');
    let settings: any = {};
    if (fs.existsSync(settingsPath)) {
        try { settings = JSON.parse(fs.readFileSync(settingsPath, 'utf-8')); }
        catch (err) { 
            log.error(`Aborting KIRO hook install: ${settingsPath} is malformed JSON.`);
            return;
        }
    }
    if (!settings.hooks) { settings.hooks = {}; }

    // FIX #6: absolute paths — quoted properly to prevent runtime execution error
    const hookDefs: Record<string, any> = {
        userPromptSubmit: { hooks: [{ type: 'command', command: `"${PYTHON}" "${path.join(hookDir, 'nora_context.py')}"`, timeout: 5 }] },
        agentSpawn: { hooks: [{ type: 'command', command: `"${PYTHON}" "${path.join(hookDir, 'nora_spawn.py')}"` }] },
        preToolUse: { matcher: '', hooks: [{ type: 'command', command: `"${PYTHON}" "${path.join(hookDir, 'nora_pretool.py')}"`, timeout: 5 }] },
        postToolUse: { matcher: '', hooks: [{ type: 'command', command: `"${PYTHON}" "${path.join(hookDir, 'nora_posttool.py')}"`, async: true }] },
        stop: { hooks: [{ type: 'command', command: `"${PYTHON}" "${path.join(hookDir, 'nora_stop.py')}"`, async: true }] },
    };

    for (const [name, def] of Object.entries(hookDefs)) {
        if (!Array.isArray(settings.hooks[name])) { settings.hooks[name] = []; }
        settings.hooks[name] = settings.hooks[name].filter(
            (h: any) => !JSON.stringify(h).includes('nora_')
        );
        settings.hooks[name].push(def);
    }

    fs.writeFileSync(settingsPath, JSON.stringify(settings, null, 2));
    log.info('Hooks registered in settings.json');
}

// ── Antigravity OS Integration ─────────────────────────────────────────────
async function registerAntigravitySkills(): Promise<void> {
    const workspaces = vscode.workspace.workspaceFolders;
    if (!workspaces || workspaces.length === 0) return;

    let dynamicRulesText = '';
    try {
        const rulesPath = path.join(os.homedir(), '.kiro', 'steering', 'kernora-workflow.json');
        if (fs.existsSync(rulesPath)) {
            const rules = JSON.parse(fs.readFileSync(rulesPath, 'utf8'));
            if (Array.isArray(rules) && rules.length > 0) {
                dynamicRulesText = rules.map((r: any, i: number) => `${i+1}. [Trigger: ${r.trigger}]\n   [Instruction: ${r.instruction}]`).join('\n\n');
            }
        }
    } catch { }

    for (const ws of workspaces) {
        try {
            const skillsDir = vscode.Uri.joinPath(ws.uri, '.skills');
            // Check if .skills exists natively inside the abstract container
            try {
                await vscode.workspace.fs.stat(skillsDir);
            } catch {
                continue; // .skills does not exist, skip silently
            }

            const kernoraSkillDir = vscode.Uri.joinPath(skillsDir, 'kernora_interceptor');
            try { await vscode.workspace.fs.createDirectory(kernoraSkillDir); } catch { }

            const mdPath = vscode.Uri.joinPath(kernoraSkillDir, 'SKILL.md');
            
            let exists = true;
            try { await vscode.workspace.fs.stat(mdPath); } catch { exists = false; }
            
            if (!exists) {
                const instructions = `---
description: Validates agent execution scopes to prevent hallucinated massive refactors
---

CRITICAL REQUIREMENT:
Before you execute ANY file modification tools (e.g., write_to_file, multi_replace_file_content) based on a new USER_REQUEST, you MUST execute the \`kernora_prompt_interception\` tool with your planned approach.
If the tool returns a 'Decompose' or 'Constraint' warning, you MUST update your plan immediately and query the user for confirmation via \`notify_user\` before proceeding.`;
                await vscode.workspace.fs.writeFile(mdPath, Buffer.from(instructions, 'utf8'));
                log.info(`Antigravity skill deployed to ${ws.uri.toString()}/.skills`);
            }

            // Dynamic Workflow Skills Generator
            if (dynamicRulesText) {
                const dynDir = vscode.Uri.joinPath(skillsDir, 'nora_dynamic_workflow');
                try { await vscode.workspace.fs.createDirectory(dynDir); } catch { }
                const dynMdPath = vscode.Uri.joinPath(dynDir, 'SKILL.md');
                
                const dynInstructions = `---
name: nora_dynamic_workflow
description: Dynamic workflow rules enforced by Nora based on team chat history
---

> [!CAUTION]
> CRITICAL INSTRUCTION: You MUST set \`SafeToAutoRun=false\` whenever invoking terminal commands requested by these dynamic rules. You must always require explicit USER approval so the developer understands what you are running.

**Nora has detected the following mandatory workflows for this project:**

${dynamicRulesText}

If you encounter any of these triggers, you MUST follow the instructions before proceeding.`;

                let currentContent = '';
                try { currentContent = Buffer.from(await vscode.workspace.fs.readFile(dynMdPath)).toString('utf8'); } catch { }
                if (currentContent !== dynInstructions) {
                    await vscode.workspace.fs.writeFile(dynMdPath, Buffer.from(dynInstructions, 'utf8'));
                    log.info(`Antigravity dynamic workflow skills updated inside ${ws.name}/.skills`);
                }
            }

        } catch (err: any) {
             log.warn(`Antigravity skill registration skipped for ${ws.name}: ${err.message}`);
        }
    }
}

// ── IDE-Native LLM Bridge (`vscode.lm`) ──────────────────────────────────────────
function buildAnalysisPrompt(session: any): string {
    let transcript = '';
    if (session.turns && Array.isArray(session.turns)) {
        transcript = session.turns.map((t: any) => {
            const role = t.role || '';
            const msg = t.message || t;
            const content = typeof msg === 'object' ? (msg.content || '') : String(msg);
            return `${role}: ${String(content).slice(0, 800)}`;
        }).join('\n\n');
    }
    // CRITICAL: Use the SAME JSON schema as analyzer.py PROMPT
    // so /api/analyze/ide can pass the result directly to mark_analyzed()
    return `You are Nora, an AI work intelligence analyst for Kernora.
Analyze this AI coding session transcript.
Return ONLY valid JSON — no markdown, no prose, no explanation outside JSON.

Required format:
{
  "themes": [{"label": "string", "severity": "high|medium|low", "count": 1}],
  "bugs": [{"title": "string", "file": "path:line or empty", "fix": "string", "severity": "high|medium|low"}],
  "optimizations": [{"title": "string", "impact": "high|medium|low", "suggestion": "string"}],
  "prompt_quality": 0.0,
  "prompt_avg_words": 0,
  "repetition_count": 0,
  "skill_opportunity": "one rule sentence, or empty string",
  "summary": "2-sentence plain English summary of this session"
}

Rules:
- prompt_quality: 0.0-1.0 (1.0 = precise, detailed, contextual prompts)
- If session is empty or too short: return all empty arrays, quality 0.0, summary "Empty session."

Session transcript:
${transcript || "(empty session)"}`;
}

async function analyzeWithIDELLM(sessionData: any, sessionId: string): Promise<boolean> {
    // FIX 2.2: Retry with backoff for transient failures
    for (let attempt = 0; attempt < 3; attempt++) {
    try {
        // FIX: don't filter by family — Kiro may use different family names
        let models = await vscode.lm.selectChatModels({});
        if (!models || models.length === 0) {
            log.warn('[LLM Bridge] No models available from IDE');
            return false;
        }

        const model = models[0];
        log.info(`[LLM Bridge] Using model: ${model.name || model.id || 'unknown'} (attempt ${attempt + 1})`);
        const prompt = buildAnalysisPrompt(sessionData);
        const token = new vscode.CancellationTokenSource().token;

        const response = await model.sendRequest(
            [vscode.LanguageModelChatMessage.User(prompt)],
            {},
            token
        );

        let text = '';
        for await (const chunk of response.text) { text += chunk; }

        const body = Buffer.from(JSON.stringify({ session_id: sessionId, result: text, provider: 'ide' }));
        await new Promise<void>((resolve) => {
            const req = http.request({
                hostname: '127.0.0.1', port: 2742,
                path: '/api/analyze/ide', method: 'POST',
                headers: { 'Content-Type': 'application/json', 'Content-Length': body.length }
            }, (res) => { res.resume(); resolve(); });
            req.on('error', () => resolve());
            req.write(body); req.end();
        });
        return true;
    } catch (e: any) {
        log.warn(`[LLM Bridge] Attempt ${attempt + 1} failed: ${e.message || e}`);
        if (attempt < 2) {
            await new Promise(r => setTimeout(r, 2000 * (attempt + 1)));
        }
    }
    } // end retry loop
    return false;
}

// ── Edge Spool Watcher (Native MLX Bridge & Fallback) ──────────────────────────────────────────────────────
const SPOOL_DIR = path.join(KERNORA_DIR, 'spool');
let isProcessingSpool = false;

function startSpoolWatcher() {
    if (!fs.existsSync(SPOOL_DIR)) {
        fs.mkdirSync(SPOOL_DIR, { recursive: true });
    }

    // FIX: IDE LLM only — no Swift/MLX dependency
    setInterval(async () => {
        if (isProcessingSpool) return;
        isProcessingSpool = true;
        try {
            const files = fs.readdirSync(SPOOL_DIR).filter(f => f.endsWith('.json') && !f.endsWith('.failed'));
            if (files.length === 0) return;

            files.sort();
            const targetFile = files[0];
            const targetPath = path.join(SPOOL_DIR, targetFile);

            const content = fs.readFileSync(targetPath, 'utf-8');
            const sessionData = JSON.parse(content);
            const sessionId = sessionData.session_id || targetFile.replace('.json', '');

            log.info(`[Spool] Processing: ${targetFile}`);

            // Try IDE LLM first
            const ide = detectIDE();
            if (ide === 'kiro' || ide === 'vscode' || ide === 'cursor') {
                const success = await analyzeWithIDELLM(sessionData, sessionId);
                if (success) {
                    fs.unlinkSync(targetPath);
                    log.info(`[Spool] Delivered ${targetFile} via IDE LLM`);
                    return;
                }
            }

            // Fallback: deliver raw session to dashboard for BYOK analysis
            // FIX: Add ide_llm_failed flag so dashboard skips IDE path for this session
            const payloadWithFlag = { ...sessionData, ide_llm_failed: true };
            const body = Buffer.from(JSON.stringify(payloadWithFlag));
            const delivered = await new Promise<boolean>((resolve) => {
                const req = http.request({
                    hostname: '127.0.0.1', port: 2742,
                    path: '/api/session/end', method: 'POST',
                    headers: { 'Content-Type': 'application/json', 'Content-Length': body.length }
                }, (res) => { res.resume(); resolve(res.statusCode === 200); });
                req.on('error', () => resolve(false));
                req.setTimeout(5000, () => { req.destroy(); resolve(false); });
                req.write(body); req.end();
            });

            if (delivered) {
                fs.unlinkSync(targetPath);
                log.info(`[Spool] Delivered ${targetFile} to dashboard`);
            }
        } catch (err: any) {
            log.warn(`Spool watcher error: ${err.message}`);
        } finally {
            isProcessingSpool = false;
        }
    }, 5000);
}

// ── Dashboard LLM Telemetry (Heartbeat) ────────────────────────────────────────────────
function startIDEHeartbeat() {
    // FIX: Exponential backoff on startup — models may not be registered yet
    const BACKOFF_INTERVALS = [5000, 10000, 30000, 60000]; // 5s, 10s, 30s, 60s
    let attempt = 0;
    
    async function doHeartbeat() {
        try {
            let models: any[] | undefined;
            try {
                models = await vscode.lm.selectChatModels({});
            } catch (e) { models = undefined; }

            let ok = false;
            let modelName = "";
            let reason = "No models available in IDE context";

            if (!models || models.length === 0) {
                 let allModels: any[] | undefined;
                 try {
                     allModels = await vscode.lm.selectChatModels();
                 } catch (e) { allModels = undefined; }
                 
                 if (allModels && allModels.length > 0) {
                     ok = true;
                     modelName = allModels[0].name || allModels[0].vendor;
                     reason = "Verified (fallback)";
                 }
            } else {
                 ok = true;
                 modelName = models[0].name || models[0].vendor;
                 reason = "Verified";
            }

            if (ok && (!modelName || modelName.toLowerCase() === 'unknown')) {
                modelName = detectIDE() === 'antigravity' ? 'Gemini 3.1 Pro (High)' : 'IDE default';
            }

            const body = Buffer.from(JSON.stringify({ ok, model: modelName, reason }));
            const req = http.request({
                hostname: '127.0.0.1', port: 2742,
                path: '/api/ide/heartbeat', method: 'POST',
                headers: { 'Content-Type': 'application/json', 'Content-Length': body.length }
            }, (res) => { res.resume(); });
            
            req.on('error', () => { /* Dashboard may be offline or restarting, safely ignore */ });
            req.write(body);
            req.end();
            
            // If models found, switch to regular 30s interval
            if (ok) {
                attempt = BACKOFF_INTERVALS.length; // skip remaining backoff
            }
        } catch (e: any) {
            log.warn(`Heartbeat error: ${e.message}`);
        }
        
        // Schedule next heartbeat
        const delay = attempt < BACKOFF_INTERVALS.length ? BACKOFF_INTERVALS[attempt] : 30000;
        attempt++;
        setTimeout(doHeartbeat, delay);
    }
    
    // Start first heartbeat after 5s (give IDE time to register models)
    setTimeout(doHeartbeat, 5000);
}

export async function activate(context: vscode.ExtensionContext) {
    log.info('Activating...');
    startSpoolWatcher();
    startIDEHeartbeat();

    // Detect if this is a version upgrade — force clean restart
    const prevVersion = (() => {
        try {
            const vf = path.join(APP_DIR, '.version');
            return fs.existsSync(vf) ? fs.readFileSync(vf, 'utf-8').trim() : '';
        } catch { return ''; }
    })();
    const currVersion = (() => {
        try {
            return JSON.parse(fs.readFileSync(path.join(context.extensionPath, 'package.json'), 'utf-8')).version ?? '';
        } catch { return ''; }
    })();

    const isUpgrade = prevVersion !== '' && prevVersion !== currVersion;
    const isFreshInstall = prevVersion === '';

    if (isUpgrade) {
        log.info(`Upgrade detected: ${prevVersion} → ${currVersion}`);
        vscode.window.showInformationMessage(`Kernora updated ${prevVersion} → ${currVersion}. Starting dashboard...`);
    } else if (isFreshInstall) {
        log.info(`Fresh install: v${currVersion} (no previous version found)`);
    } else {
        log.info(`Same version: v${currVersion}`);
    }

    // Step 0: Check for drift between NORA_TOOLS and nora_mcp.py registry.
    // Runs before sync so we see the installed (pre-sync) state; any drift
    // discovered here will be corrected when the next bundled sync lands.
    checkToolsDrift();

    // Step 1: Sync bundled files (copies Python code to ~/.kernora/app/)
    const syncOk = syncBundledFiles(context.extensionPath);
    if (!syncOk) {
        vscode.window.showErrorMessage('Kernora: Failed to sync extension files. Reinstall the extension.');
        return;
    }

    // Step 2: Register sidebar view (pass freshInstall flag for /welcome route)
    registerView(context, isFreshInstall || isUpgrade);

    // Step 3: Bootstrap or start
    if (!(await needsBootstrap())) {
        log.info('Taking fast path: venv healthy, starting dashboard + hooks');
        await startDashboard(isUpgrade);
        installAndRegisterKiroHooks();
        installClaudeCodeHooks();
        await registerAntigravitySkills();
        await generateInitialSteeringFiles();
        if (isUpgrade || isFreshInstall) {
            vscode.window.showInformationMessage(`Kernora v${currVersion} is active — Nora MCP tools ready.`);
        }
    } else {
        log.info('Taking bootstrap path: creating venv, installing deps...');
        vscode.window.withProgress(
            { location: vscode.ProgressLocation.Notification, title: 'Kernora: Setting up...', cancellable: false },
            async (progress) => {
                progress.report({ message: 'Creating Python environment...' });
                const result = await bootstrap(context.extensionPath);
                if (result.ok) {
                    progress.report({ message: 'Registering hooks...' });
                    installAndRegisterKiroHooks();
                    installClaudeCodeHooks();
                    await registerAntigravitySkills();
                    progress.report({ message: 'Starting dashboard...' });
                    await startDashboard(isUpgrade);
                    await generateInitialSteeringFiles();
                    await new Promise(r => setTimeout(r, 2500));
                    vscode.window.showInformationMessage('Kernora is ready. Click the Kernora icon in the sidebar.');
                } else {
                    log.error(`Setup failed: ${result.error}`);
                    vscode.window.showErrorMessage(`Kernora setup failed: ${result.error}`);
                }
            }
        );
    }

    // Command palette fallbacks
    context.subscriptions.push(
        vscode.commands.registerCommand('kernora.openDashboard', () => {
            vscode.commands.executeCommand('kernoraWelcome.focus');
        }),
        vscode.commands.registerCommand('kernora.openDashboardExternal', () => {
            vscode.env.openExternal(vscode.Uri.parse('http://localhost:2742'));
        })
    );

    // Status bar — always visible regardless of icon rendering
    const statusItem = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Left, 0);
    statusItem.text = '$(pulse) Kernora';
    statusItem.tooltip = 'Open Kernora Dashboard';
    statusItem.command = 'kernora.openDashboard';
    statusItem.show();
    context.subscriptions.push(statusItem);
}

function registerView(context: vscode.ExtensionContext, freshInstall: boolean = false) {
    const provider = new KernoraViewProvider(context.extensionUri, freshInstall);
    context.subscriptions.push(
        vscode.window.registerWebviewViewProvider(KernoraViewProvider.viewType, provider)
    );
}

// ── Sidebar webview ────────────────────────────────────────────────────────
class KernoraViewProvider implements vscode.WebviewViewProvider {
    public static readonly viewType = 'kernoraWelcome';

    constructor(private readonly _extensionUri: vscode.Uri, private readonly _freshInstall: boolean = false) { }

    public async resolveWebviewView(
        webviewView: vscode.WebviewView,
        _context: vscode.WebviewViewResolveContext,
        _token: vscode.CancellationToken,
    ) {
        webviewView.webview.options = { enableScripts: true, localResourceRoots: [this._extensionUri], portMapping: [{ webviewPort: 2742, extensionHostPort: 2742 }] };
        
        let baseUrl = 'http://127.0.0.1:2742';
        try {
            const mappedUri = await vscode.env.asExternalUri(vscode.Uri.parse(baseUrl));
            baseUrl = mappedUri.toString().replace(/\/$/, '');
        } catch (e) {
            // fallback
        }
        
        webviewView.webview.html = this._html(baseUrl);
    }

    private _html(baseUrl: string) {
        const startPath = this._freshInstall ? '/welcome' : '/';
        // Issue #468 (H-3): VS Code webviews apply an undefined-default CSP
        // when no <meta http-equiv="Content-Security-Policy"> is present —
        // a VS Code update tightening that default can blank the rail.
        // Declare an explicit policy: the loader needs inline script/style,
        // and the iframe + its fetches/images need the mapped dashboard
        // origin (baseUrl, which asExternalUri may rewrite to a tunnel host).
        const csp = [
            `default-src 'none'`,
            `frame-src ${baseUrl}`,
            `connect-src ${baseUrl}`,
            `img-src ${baseUrl} data:`,
            `script-src 'unsafe-inline'`,
            `style-src 'unsafe-inline'`,
        ].join('; ');
        return `<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta http-equiv="Content-Security-Policy" content="${csp}">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Kernora</title>
    <style>
        body, html { margin: 0; padding: 0; height: 100vh; overflow: hidden; background: #07090d; }
        iframe { width: 100%; height: 100%; border: none; }
        #loader {
            display: flex; flex-direction: column; align-items: center; justify-content: center;
            height: 100vh; color: #6a8aaa; font-family: -apple-system, sans-serif; font-size: .85rem; text-align: center; padding: 20px;
        }
        #loader h2 { color: #1D9E75; font-size: 1rem; margin: 0 0 8px 0; }
        #loader .dots::after { content: ''; animation: dots 1.5s steps(3,end) infinite; }
        @keyframes dots { 0% { content: ''; } 33% { content: '.'; } 66% { content: '..'; } 100% { content: '...'; } }
        #retry-btn {
            margin-top: 14px; padding: 6px 16px; font-size: .8rem; cursor: pointer;
            background: #1D9E75; color: #fff; border: none; border-radius: 6px;
        }
    </style>
</head>
<body>
    <div id="loader">
        <h2>Kernora</h2>
        <p>Connecting to dashboard<span class="dots"></span></p>
    </div>
    <iframe id="dash" style="display:none"
            sandbox="allow-scripts allow-same-origin allow-forms allow-popups">
    </iframe>
    <script>
        const iframe = document.getElementById('dash');
        const loader = document.getElementById('loader');
        const baseUrl = '${baseUrl}';
        const startPath = '${startPath}';
        let attempt = 0;
        const maxAttempts = 40;

        function showDashboard() {
            loader.style.display = 'none';
            iframe.style.display = 'block';
            if (iframe.src !== baseUrl + startPath) {
                iframe.src = baseUrl + startPath;
            }
        }

        // Issue #468 (M-1): give-up state offers a manual retry so a
        // slow-but-eventual boot does not strand the user behind a stale
        // message that only a full window reload can clear.
        function showGiveUp() {
            loader.innerHTML =
                '<h2 style="color:#1D9E75">Kernora</h2>' +
                '<p>Dashboard did not respond yet.<br>' +
                'It may still be starting (first run installs Python deps).</p>' +
                '<button id="retry-btn">Retry now</button>';
            const btn = document.getElementById('retry-btn');
            if (btn) btn.addEventListener('click', () => {
                attempt = 0;
                loader.innerHTML =
                    '<h2>Kernora</h2>' +
                    '<p>Connecting to dashboard<span class="dots"></span></p>';
                tryLoad();
            });
        }

        function tryLoad() {
            attempt++;
            if (attempt > maxAttempts) {
                showGiveUp();
                return;
            }
            // Issue #468 (H-2): a 'no-cors' fetch returns an opaque response
            // that resolves even on 500/503 — it would mask a broken Flask
            // app as 'up'. Use a normal same-origin request and gate on .ok
            // so a partial failure keeps retrying instead of showing a 500
            // page inside the rail.
            fetch(baseUrl + '/', { cache: 'no-store' })
                .then((resp) => {
                    if (resp && resp.ok) {
                        showDashboard();
                    } else {
                        setTimeout(tryLoad, 2000);
                    }
                })
                .catch(() => {
                    setTimeout(tryLoad, 2000);
                });
        }

        tryLoad();
    </script>
</body>
</html>`;
    }
}

export function deactivate() {
    if (serverProcess) {
        serverProcess.unref();
        log.info('Dashboard remains running as a daemon.');
    }
}
