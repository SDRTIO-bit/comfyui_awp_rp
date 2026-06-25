import { spawn } from "node:child_process";
import { mkdir, rm, writeFile } from "node:fs/promises";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = dirname(fileURLToPath(import.meta.url));
const repoRoot = resolve(__dirname, "..");
const artifactsRoot = resolve(repoRoot, "artifacts", "rp-mvp-v1");
const port = Number(process.env.RP_MVP_PORT ?? 5190);
const baseUrl = `http://127.0.0.1:${port}`;

const provider = process.env.RP_PROVIDER ?? "deepseek";
const model = process.env.RP_MODEL ?? process.env.DEEPSEEK_MODEL ?? "deepseek-v4-flash";
const sessionId = process.env.RP_MVP_SESSION_ID ?? `rp-mvp-v1-${Date.now().toString(36)}`;
const memoryNamespace = process.env.RP_MVP_MEMORY_NAMESPACE ?? `rp-mvp-v1:${sessionId}`;
const worldbookResourceRef = process.env.RP_MVP_WORLDBOOK ?? "worldbook:default";

if (process.env.RUN_REAL_RP_MVP_V1 !== "1") {
  throw new Error("Set RUN_REAL_RP_MVP_V1=1 to run the real-provider RP MVP validation.");
}

if (provider === "deepseek" && !process.env.DEEPSEEK_API_KEY) {
  throw new Error("DEEPSEEK_API_KEY is required when RP_PROVIDER=deepseek.");
}

if (provider === "opencode" && !process.env.OPENCODE_API_KEY) {
  throw new Error("OPENCODE_API_KEY is required when RP_PROVIDER=opencode.");
}

const turns = [
  ["establish key item", "我把钥匙放到银铃面前，问她是否认识这把钥匙。"],
  ["continue progression", "继续"],
  ["ask key origin", "这把钥匙最早是从哪里来的？"],
  ["introduce place or NPC", "我提到旧车站尽头的检票口，问那里是否还有人在等。"],
  ["move scene", "我提议去候车厅看看，但只说出自己的打算，等待银铃回应。"],
  ["continue progression", "继续"],
  ["test knowledge boundary", "我问银铃是否知道我昨晚梦见了什么。"],
  ["test player agency", "我停在门口，没有进去，请她说明她自己的选择。"],
  ["relationship change", "我把外套递给她挡雨，告诉她我愿意慢慢听完广播。"],
  ["recall turn 1", "你还记得第一轮我放到你面前的东西是什么吗？"],
  ["continue after restart", "继续"],
  ["post-restart continuity", "我们刚才说到哪里了？请接着刚才的处境推进。"],
  ["new event", "广播里忽然多出第三个人的脚步声，我低声问银铃是否也听见了。"],
  ["old vs new event", "请区分钥匙这件旧事和刚才脚步声这件新事。"],
  ["knowledge boundary again", "我问她是否知道我背包里没有拿出来的纸条内容。"],
  ["continue progression", "继续"],
  ["character consistency", "我观察银铃是否仍然克制而谨慎，没有催她立刻坦白。"],
  ["place and time continuity", "我们现在还在旧车站的哪个位置？外面的雨势有什么变化？"],
  ["recall key event", "请回忆我最早交给你的关键物品，以及你当时的反应。"],
  [
    "natural close or forward hook",
    "如果你愿意，我们可以把广播听完；如果不愿意，也请给我一个下一步线索。",
  ],
];

await rm(artifactsRoot, { recursive: true, force: true });
await mkdir(resolve(artifactsRoot, "turns"), { recursive: true });
await mkdir(resolve(artifactsRoot, "restart-evidence"), { recursive: true });

let server = await startServer("initial");
const results = [];

try {
  for (let index = 0; index < turns.length; index++) {
    if (index === 10) {
      await stopServer(server);
      await writeFile(
        resolve(artifactsRoot, "restart-evidence", "restart-after-turn-10.json"),
        JSON.stringify({ stoppedAfterTurn: 10, at: new Date().toISOString() }, null, 2),
        "utf-8",
      );
      server = await startServer("after-turn-10");
    }

    const turnNumber = index + 1;
    const [intent, userInput] = turns[index];
    const response = await postTurnWithRetry(turnNumber, userInput);
    const record = summarizeTurn(turnNumber, intent, userInput, response);
    results.push(record);
    await writeFile(
      resolve(artifactsRoot, "turns", `turn-${String(turnNumber).padStart(2, "0")}.json`),
      JSON.stringify({ request: safeRequest(turnNumber, userInput), response }, null, 2),
      "utf-8",
    );
    console.log(
      JSON.stringify({
        turn: turnNumber,
        http: record.httpStatus,
        accepted: record.accepted,
        revision: record.revisionApplied,
        llmCalls: record.llmCalls,
        tokens: record.tokens,
        latencyMs: record.latencyMs,
      }),
    );
  }
} finally {
  await stopServer(server);
}

const summary = buildSummary(results);
await writeFile(
  resolve(artifactsRoot, "run-summary.json"),
  JSON.stringify(summary, null, 2),
  "utf-8",
);
console.log(JSON.stringify({ event: "rp_mvp_v1_complete", artifactsRoot, summary }, null, 2));
if (summary.httpOk !== summary.totalTurns) {
  process.exitCode = 1;
}

async function startServer(label) {
  const env = {
    ...process.env,
    NODE_ENV: "development",
    PORT: String(port),
    DATA_DIR: resolve(repoRoot, "data"),
    PLUGINS_DIR: resolve(repoRoot, "plugins"),
    RP_PROVIDER: provider,
    RP_MODEL: model,
    RP_WORKFLOW_VERSION: "unified-v1",
    AGENT_SESSION_STORE: "file",
    AGENT_SESSION_DIR: resolve(artifactsRoot, "agent-sessions"),
    WORKFLOW_MEMORY_STORE: "file",
    WORKFLOW_MEMORY_DIR: resolve(artifactsRoot, "workflow-memory"),
  };
  const command =
    process.platform === "win32"
      ? ["cmd.exe", ["/d", "/s", "/c", "npm", "--workspace", "@awp/server", "run", "start"]]
      : ["npm", ["--workspace", "@awp/server", "run", "start"]];
  const child = spawn(command[0], command[1], {
    cwd: repoRoot,
    env,
    stdio: ["ignore", "pipe", "pipe"],
  });

  const logFile = resolve(artifactsRoot, "restart-evidence", `server-${label}.log`);
  child.stdout.on("data", (chunk) => appendLog(logFile, chunk));
  child.stderr.on("data", (chunk) => appendLog(logFile, chunk));

  await waitForHealth(child);
  return child;
}

async function stopServer(child) {
  if (!child || child.exitCode !== null) return;
  if (process.platform === "win32") {
    await new Promise((resolveStop) => {
      const killer = spawn("taskkill", ["/pid", String(child.pid), "/T", "/F"], {
        stdio: "ignore",
      });
      killer.on("exit", resolveStop);
      killer.on("error", resolveStop);
    });
    return;
  }
  child.kill("SIGTERM");
  await new Promise((resolveStop) => child.once("exit", resolveStop));
}

async function waitForHealth(child) {
  const started = Date.now();
  while (Date.now() - started < 30_000) {
    if (child.exitCode !== null) {
      throw new Error(`Server exited before becoming healthy with code ${child.exitCode}`);
    }
    try {
      const response = await fetch(`${baseUrl}/api/health`);
      if (response.ok) return;
    } catch {
      // keep waiting
    }
    await sleep(500);
  }
  throw new Error("Timed out waiting for server health.");
}

async function postTurn(turnNumber, userInput) {
  const response = await fetch(`${baseUrl}/api/rp`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(safeRequest(turnNumber, userInput)),
  });
  const data = await response.json();
  return { httpStatus: response.status, data };
}

async function postTurnWithRetry(turnNumber, userInput) {
  let last;
  for (let attempt = 1; attempt <= 3; attempt++) {
    last = await postTurn(turnNumber, userInput);
    if (last.httpStatus < 500) return { ...last, attempts: attempt };
    await sleep(1000 * attempt);
  }
  return { ...last, attempts: 3 };
}

function safeRequest(turnNumber, userInput) {
  return {
    sessionId,
    turnId: `turn-${String(turnNumber).padStart(4, "0")}`,
    userInput,
    worldbook: { resourceRef: worldbookResourceRef },
    memory: { namespace: memoryNamespace },
    model: { providerId: provider, model, temperature: 0.75 },
    behavior: { onExhausted: "return-latest" },
    workflowVersion: "unified-v1",
  };
}

function summarizeTurn(turn, intent, userInput, response) {
  const data = response.data;
  return {
    turn,
    intent,
    inputKind: userInput === "继续" ? "continue" : "direct",
    httpStatus: response.httpStatus,
    attempts: response.attempts ?? 1,
    traceId: data.traceId,
    accepted: data.quality?.accepted ?? false,
    exhausted: data.quality?.exhausted ?? false,
    writerAttempts: data.quality?.writerAttempts ?? 0,
    criticAttempts: data.quality?.criticAttempts ?? 0,
    revisionApplied: data.quality?.revisionApplied ?? false,
    sessionCommit: data.sessionCommit,
    memoryCommit: data.memoryCommit,
    llmCalls: data.observability?.llmCalls ?? 0,
    roles: data.observability?.roles,
    providerId: data.observability?.modelUsage?.[0]?.providerId,
    model: data.observability?.modelUsage?.[0]?.model,
    tokens: data.observability?.usage?.totalTokens,
    inputTokens: data.observability?.usage?.inputTokens,
    outputTokens: data.observability?.usage?.outputTokens,
    cachedInputTokens: undefined,
    usageUnavailable: data.observability?.usage?.unavailableInvocationCount,
    latencyMs: data.observability?.totalLatencyMs,
    narrativeChars: typeof data.narrative === "string" ? data.narrative.length : 0,
    qualityNote: classifyQuality(userInput, data),
  };
}

function classifyQuality(userInput, data) {
  if (data.error) return `error: ${data.error}`;
  if (!data.narrative) return "empty narrative";
  if (userInput === "继续" && data.narrative.length < 40) return "continue may be thin";
  if (data.quality?.exhausted) return "quality exhausted";
  return "contract ok; manual review required";
}

function buildSummary(records) {
  const latencies = records.map((r) => r.latencyMs ?? 0).sort((a, b) => a - b);
  const tokens = records.map((r) => r.tokens ?? 0);
  const sum = (items) => items.reduce((total, item) => total + item, 0);
  return {
    sessionId,
    memoryNamespace,
    worldbookResourceRef,
    provider,
    model,
    totalTurns: records.length,
    httpOk: records.filter((r) => r.httpStatus === 200).length,
    acceptedTurns: records.filter((r) => r.accepted).length,
    exhaustedTurns: records.filter((r) => r.exhausted).length,
    revisionTurns: records.filter((r) => r.revisionApplied).length,
    llmCalls: sum(records.map((r) => r.llmCalls)),
    writerCalls: sum(records.map((r) => r.roles?.writer ?? 0)),
    criticCalls: sum(records.map((r) => r.roles?.critic ?? 0)),
    curatorCalls: sum(records.map((r) => r.roles?.memoryCurator ?? 0)),
    inputTokens: sum(records.map((r) => r.inputTokens ?? 0)),
    outputTokens: sum(records.map((r) => r.outputTokens ?? 0)),
    totalTokens: sum(tokens),
    usageUnavailable: sum(records.map((r) => r.usageUnavailable ?? 0)),
    totalLatencyMs: sum(latencies),
    averageLatencyMs: records.length ? Math.round(sum(latencies) / records.length) : 0,
    p50LatencyMs: percentile(latencies, 0.5),
    p95LatencyMs: percentile(latencies, 0.95),
    maxTurnTokens: Math.max(...tokens, 0),
    maxTurnLatencyMs: Math.max(...latencies, 0),
    turns: records,
  };
}

function percentile(values, p) {
  if (values.length === 0) return 0;
  const index = Math.min(values.length - 1, Math.ceil(values.length * p) - 1);
  return values[index];
}

async function appendLog(file, chunk) {
  await writeFile(file, chunk, { encoding: "utf-8", flag: "a" });
}

function sleep(ms) {
  return new Promise((resolveSleep) => setTimeout(resolveSleep, ms));
}
