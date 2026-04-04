import { spawn } from 'child_process';
import * as path from 'path';

/**
 * Interface representing the JSON output from Apple's FoundationModels CoreML Inference
 */
export interface FoundationModelInsights {
    themes: string[];
    bugsDetected: {
        pattern: string;
        description: string;
        severity: 'low' | 'medium' | 'high';
    }[];
    skillOpportunities: string[];
    promptQualityScore: number;
}

export class SwiftInferenceProxy {
    private binaryPath: string;
    private childProcess: ReturnType<typeof spawn> | null = null;
    private requestQueue: Map<string, { resolve: (val: any) => void, reject: (err: any) => void, timeout: NodeJS.Timeout }> = new Map();
    private outputBuffer: string = "";

    constructor() {
        this.binaryPath = path.join(__dirname, '..', '..', 'kernora-native-mac', '.build', 'debug', 'kernora-native-mac');
    }

    private getOrCreateDaemon(): ReturnType<typeof spawn> {
        if (this.childProcess && !this.childProcess.killed) {
            return this.childProcess;
        }

        console.log("[MLX Daemon] Booting Apple Neural Engine Native Process...");
        const nativeDir = path.join(__dirname, '..', '..', 'kernora-native-mac');
        this.childProcess = spawn('swift', ['run', '--configuration', 'release', 'kernora-native-mac'], { 
            cwd: nativeDir,
            stdio: ['pipe', 'pipe', 'pipe'] 
        });

        this.childProcess.stderr?.on('data', (data) => {
            console.log(`[MLX Download Status]: ${data.toString().trim()}`);
        });

        this.childProcess.stdout?.on('data', (data) => {
            const chunk = data.toString();
            console.log(`[MLX stdout]: ${chunk.trim()}`);
            this.outputBuffer += chunk;

            if (this.outputBuffer.includes('SUCCESS_END')) {
                const parts = this.outputBuffer.split('SUCCESS_START');
                if (parts.length > 1) {
                    const payloadChunk = parts[1].split('SUCCESS_END');
                    if (payloadChunk.length > 0) {
                        const jsonString = payloadChunk[0].trim();
                        this.outputBuffer = payloadChunk[1] || ""; // keep remainder if any

                        try {
                            const parsedData = JSON.parse(jsonString);
                            const nextReqId = this.requestQueue.keys().next().value;
                            if (nextReqId) {
                                const reqHandlers = this.requestQueue.get(nextReqId);
                                if (reqHandlers) {
                                    clearTimeout(reqHandlers.timeout);
                                    reqHandlers.resolve(parsedData);
                                    this.requestQueue.delete(nextReqId);
                                }
                            }
                        } catch (err) {
                            console.error("[MLX Daemon] Partial or corrupt JSON ignored:", err);
                        }
                    }
                }
            }
        });

        this.childProcess.on('error', (err) => {
            console.error("[MLX Daemon] Process crashed:", err.message);
            this.flushQueue(new Error("Native MLX Prox crashed."));
            this.childProcess = null;
        });

        this.childProcess.on('exit', () => {
            this.flushQueue(new Error("Native MLX Process exited unexpectedly."));
            this.childProcess = null;
        });

        return this.childProcess;
    }

    private flushQueue(err: Error) {
        for (const [id, handlers] of this.requestQueue.entries()) {
            clearTimeout(handlers.timeout);
            handlers.reject(err);
        }
        this.requestQueue.clear();
    }

    public async analyzeSession(sessionId: string, promptPayload: string): Promise<FoundationModelInsights> {
        return new Promise((resolve, reject) => {
            const daemon = this.getOrCreateDaemon();

            // Set immense timeout ONLY for the potential cold-start download
            const globalTimeout = setTimeout(() => {
                reject(new Error("Timeout: MLX Edge Engine exceeded 10 minutes pipeline window."));
                this.requestQueue.delete(sessionId);
            }, 600000);

            this.requestQueue.set(sessionId, { resolve, reject, timeout: globalTimeout });

            // Safely serialize and pump to the warm daemon stdin
            // Newlines are naturally escaped by JSON.stringify
            const safePayload = JSON.stringify({ sessionId, payload: promptPayload });
            daemon.stdin?.write(safePayload + "\n");
        });
    }
}
