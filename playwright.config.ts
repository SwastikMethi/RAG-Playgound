import { defineConfig } from "@playwright/test";

const environment = {
  RAG_APP_TOKEN: "fixture-browser-token-no-real-access",
  RAG_MODE: "fixture",
  RAG_DATABASE_URL:
    "postgresql+psycopg://rag:local-development-only@127.0.0.1:6544/ragplayground_test",
  RAG_ARTIFACT_ROOT: ".data/browser-artifacts",
  RAG_QDRANT_COLLECTION_PREFIX: "rag_browser_test",
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
        ".venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8781",
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
