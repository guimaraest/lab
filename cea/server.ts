import { mkdtemp, readFile, rm, stat, writeFile } from "node:fs/promises";
import { spawn } from "node:child_process";
import os from "node:os";
import { fileURLToPath } from "node:url";
import path from "node:path";
import express from "express";
import { z } from "zod";

const app = express();
const port = Number(process.env.PORT ?? 4173);
const apiPort = Number(process.env.API_PORT ?? (process.env.NODE_ENV === "production" ? port : 4174));
const python = process.env.CEA_PYTHON ?? "python3";
const ceaExecutable = process.env.CEA_CLI ?? "/opt/cea-source/build/py-build/source/cea";
const ceaData = process.env.CEA_DATA_DIR ?? "/opt/cea-venv/lib/python3.11/site-packages/cea/data";
const root = path.dirname(fileURLToPath(import.meta.url));
const worker = path.resolve(root, "../../solver.py");
const client = path.resolve(root, "../client");
const maxDeckSize = 512 * 1024;
const maxOutputSize = 10 * 1024 * 1024;

const solveSchema = z.object({
  mode: z.enum(["equilibrium", "rocket"]),
  reactants: z
    .array(
      z.object({
        species: z.string().trim().min(1).max(64),
        moles: z.number().finite().positive().max(1e9),
      }),
    )
    .min(1)
    .max(12),
  pressure: z.number().finite().positive().max(1e7),
  temperature: z.number().finite().positive().max(1e6),
  equilibriumType: z.enum(["HP", "TP"]).optional(),
  exitPressureRatio: z.number().finite().gt(1).max(1e7).optional(),
});

const deckSchema = z.object({
  input: z.string().trim().min(1).max(maxDeckSize),
});

app.use(express.json({ limit: "600kb" }));

app.get("/api/health", (_request, response) => {
  response.json({ status: "ok", engine: "NASA CEA Python API" });
});

app.post("/api/solve", (request, response) => {
  const parsed = solveSchema.safeParse(request.body);
  if (!parsed.success) {
    response.status(400).json({
      error: "Check the calculation settings and reactant amounts.",
      details: parsed.error.issues.map((issue) => issue.message),
    });
    return;
  }

  const species = parsed.data.reactants.map((reactant) => reactant.species.trim().toUpperCase());
  if (new Set(species).size !== species.length) {
    response.status(400).json({ error: "Each reactant species can only be listed once." });
    return;
  }

  const child = spawn(python, [worker], { stdio: ["pipe", "pipe", "pipe"] });
  let stdout = "";
  let stderr = "";
  child.stdout.setEncoding("utf8").on("data", (chunk: string) => {
    stdout += chunk;
  });
  child.stderr.setEncoding("utf8").on("data", (chunk: string) => {
    stderr += chunk;
  });
  child.on("error", (error) => {
    response.status(503).json({ error: `Could not start the CEA runtime: ${error.message}` });
  });
  child.on("close", (code) => {
    if (response.headersSent) return;
    if (code !== 0) {
      response.status(422).json({
        error: stderr.trim().split("\n").filter(Boolean).at(-1) ?? "CEA could not solve this case.",
      });
      return;
    }
    try {
      response.json(JSON.parse(stdout));
    } catch {
      response.status(500).json({ error: "CEA returned an unreadable result." });
    }
  });
  child.stdin.end(JSON.stringify(parsed.data));
});

app.post("/api/deck", async (request, response) => {
  const parsed = deckSchema.safeParse(request.body);
  if (!parsed.success) {
    response.status(400).json({
      error: `Enter a CEA input deck (maximum ${maxDeckSize / 1024} KiB).`,
    });
    return;
  }

  let directory: string | undefined;
  try {
    directory = await mkdtemp(path.join(os.tmpdir(), "lab-cea-"));
    await writeFile(path.join(directory, "case.inp"), parsed.data.input, {
      encoding: "utf8",
      mode: 0o600,
    });

    const run = await runCeaCase(directory);
    if (run.timedOut) {
      response.status(504).json({ error: "CEA deck execution exceeded the 120 second limit." });
      return;
    }
    if (run.code !== 0) {
      response.status(422).json({
        error: [run.stderr, run.stdout].map((text) => text.trim()).find(Boolean)?.slice(-2000)
          ?? `CEA exited with status ${run.code}.`,
      });
      return;
    }

    const outputPath = path.join(directory, "case.out");
    const outputStats = await stat(outputPath);
    if (outputStats.size > maxOutputSize) {
      response.status(413).json({ error: "CEA output exceeds the 10 MiB limit." });
      return;
    }
    response.json({ output: await readFile(outputPath, "utf8") });
  } catch (error) {
    response.status(500).json({
      error: `Could not run the CEA input deck: ${error instanceof Error ? error.message : String(error)}`,
    });
  } finally {
    if (directory) {
      try {
        await rm(directory, { recursive: true, force: true });
      } catch (error) {
        console.error(`Could not clean up CEA temporary directory ${directory}:`, error);
      }
    }
  }
});

function runCeaCase(directory: string) {
  return new Promise<{
    code: number | null;
    stdout: string;
    stderr: string;
    timedOut: boolean;
  }>((resolve, reject) => {
    const child = spawn(ceaExecutable, ["case"], {
      cwd: directory,
      env: { ...process.env, CEA_DATA_DIR: ceaData },
      stdio: ["ignore", "pipe", "pipe"],
    });
    let stdout = "";
    let stderr = "";
    let timedOut = false;
    const timeout = setTimeout(() => {
      timedOut = true;
      child.kill("SIGKILL");
    }, 120_000);

    child.stdout.setEncoding("utf8").on("data", (chunk: string) => {
      stdout = `${stdout}${chunk}`.slice(-8192);
    });
    child.stderr.setEncoding("utf8").on("data", (chunk: string) => {
      stderr = `${stderr}${chunk}`.slice(-8192);
    });
    child.on("error", (error) => {
      clearTimeout(timeout);
      reject(error);
    });
    child.on("close", (code) => {
      clearTimeout(timeout);
      resolve({ code, stdout, stderr, timedOut });
    });
  });
}

if (process.env.NODE_ENV === "production") {
  app.use(express.static(client));
  app.use((_request, response) => response.sendFile(path.join(client, "index.html")));
}

app.listen(apiPort, "0.0.0.0", () => {
  console.log(`CEA Studio listening on port ${apiPort}`);
});
