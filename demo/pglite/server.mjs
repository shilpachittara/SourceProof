/**
 * Local PGlite server — Postgres-compatible storage for the demo.
 * Data persists under PGDATA (default: ./data/pglite).
 */
import { mkdir } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { PGlite } from "@electric-sql/pglite";
import { PGLiteSocketServer } from "@electric-sql/pglite-socket";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const dataDir = process.env.PGDATA || path.join(__dirname, "../../data/pglite");
const host = process.env.PGHOST || "0.0.0.0";
const port = Number(process.env.PGPORT || 5432);

await mkdir(dataDir, { recursive: true });

const db = new PGlite(dataDir);
const server = new PGLiteSocketServer({
  db,
  port,
  host,
  connectionQueueTimeout: 60_000,
});

await server.start();
console.log(`PGlite listening on ${host}:${port}`);
console.log(`Data directory: ${dataDir}`);

const shutdown = async () => {
  console.log("Shutting down PGlite...");
  await server.stop();
  await db.close();
  process.exit(0);
};

process.on("SIGINT", shutdown);
process.on("SIGTERM", shutdown);
