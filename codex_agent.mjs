import { Codex } from "@openai/codex-sdk";

function readStdin() {
  return new Promise((resolve, reject) => {
    let data = "";
    process.stdin.setEncoding("utf8");
    process.stdin.on("data", (chunk) => (data += chunk));
    process.stdin.on("end", () => resolve(data));
    process.stdin.on("error", reject);
  });
}

async function main() {
  const raw = await readStdin();
  const payload = raw ? JSON.parse(raw) : {};

  const message = typeof payload.message === "string" ? payload.message : "";
  const threadId = typeof payload.threadId === "string" ? payload.threadId : null;

  const model = typeof payload.model === "string" ? payload.model : undefined;
  const sandboxMode = payload.sandboxMode || "read-only";
  const approvalPolicy = payload.approvalPolicy || "never";
  const workingDirectory = payload.workingDirectory || process.cwd();

  const apiKey =
    (typeof payload.apiKey === "string" && payload.apiKey) ||
    process.env.CODEX_API_KEY ||
    process.env.OPENAI_API_KEY ||
    process.env.OPENAI_KEY ||
    undefined;

  const baseUrl =
    (typeof payload.baseUrl === "string" && payload.baseUrl) ||
    process.env.OPENAI_BASE_URL ||
    process.env.OPENAI_API_BASE ||
    undefined;

  const codex = new Codex({
    apiKey,
    baseUrl,
  });

  const thread = threadId
    ? codex.resumeThread(threadId, {
        model,
        sandboxMode,
        approvalPolicy,
        workingDirectory,
        skipGitRepoCheck: true,
      })
    : codex.startThread({
        model,
        sandboxMode,
        approvalPolicy,
        workingDirectory,
        skipGitRepoCheck: true,
      });

  const turn = await thread.run(message);

  process.stdout.write(
    JSON.stringify({
      threadId: thread.id,
      finalResponse: turn.finalResponse,
      usage: turn.usage,
    }),
  );
}

main().catch((err) => {
  process.stderr.write(String(err?.stack || err));
  process.exit(1);
});
