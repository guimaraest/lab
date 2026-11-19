import { spawn } from "node:child_process";
import { fileURLToPath } from "node:url";
import path from "node:path";
import express from "express";
import { z } from "zod";

const app = express();
const port = Number(process.env.PORT ?? 4173);
const apiPort = Number(process.env.API_PORT ?? (process.env.NODE_ENV === "production" ? port : 4174));
const python = process.env.CEA_PYTHON ?? "python3";
const root = path.dirname(fileURLToPath(import.meta.url));
const worker = path.resolve(root, "../../solver.py");
const client = path.resolve(root, "../client");

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

app.use(express.json({ limit: "32kb" }));

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

if (process.env.NODE_ENV === "production") {
  app.use(express.static(client));
  app.use((_request, response) => response.sendFile(path.join(client, "index.html")));
}

app.listen(apiPort, "0.0.0.0", () => {
  console.log(`CEA Studio listening on port ${apiPort}`);
});
