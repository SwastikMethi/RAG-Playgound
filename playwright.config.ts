import { defineConfig } from "@playwright/test";
import { delimiter, resolve } from "node:path";

const environment = {
  PYTHONPATH: [resolve("packages"), resolve("apps/api"), process.cwd()].join(delimiter),
  RAG_MODE: "fixture",
  RAG_MASTER_KEY: "dGhpcy1pcy1hLWZpeHR1cmUta2V5LWZvci10ZXN0cyE=",
  RAG_DATABASE_URL:
    "postgresql+psycopg://rag:local-development-only@127.0.0.1:6544/ragplayground_browser_test",
  RAG_ARTIFACT_ROOT: ".data/browser-artifacts",
  RAG_QDRANT_COLLECTION_PREFIX: "rag_browser_test",
  RAG_DATABASE_HOST_ALLOWLIST: '["127.0.0.1"]',
  RAG_DATABASE_RELATION_ALLOWLIST: '[{"host":"127.0.0.1","port":6544,"database":"ragplayground_browser_test","schema":"browser_fixture","relation":"notes","columns":["id","body"]}]',
};
export default defineConfig({
  testDir: "apps/web/e2e",
  timeout: 60000,
  workers: 1,
  use: {
    baseURL: "http://127.0.0.1:8781",
    viewport: { width: 1440, height: 900 },
    trace: "retain-on-failure",
  },
  webServer: [
    {
      command:
        ".venv/bin/python -m tests.browser_server",
      url: "http://127.0.0.1:8781/api/v1/health",
      env: environment,
      reuseExistingServer: false,
    },
    {
      command: ".venv/bin/python -m workers.main",
      env: environment,
      wait: { stdout: /Worker ready/ },
      reuseExistingServer: false,
    },
  ],
});
