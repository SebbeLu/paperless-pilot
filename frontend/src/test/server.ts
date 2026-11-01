import { HttpResponse, http } from "msw";
import { setupServer } from "msw/node";
import type { SystemStatus } from "@/api/client";

export const emptyQueue = { queued: 0, running: 0, failed: 0, succeeded: 0 };

export const healthyStatus: SystemStatus = {
  queue: { queued: 71, running: 1, failed: 1, succeeded: 12 },
  open_suggestions: 23,
  paperless: {
    reachable: true,
    version: "3.2.1",
    documents_total: 709,
    documents_inbox: 95,
    problem: null,
    error: null,
  },
  hosts: [
    {
      name: "Mac",
      url: "http://mac.local:11434",
      reachable: true,
      version: "0.24.0",
      models: ["gemma4:26b", "qwen2.5:14b"],
      problem: null,
      error: null,
    },
    {
      name: "Gaming-PC",
      url: "http://gaming-pc:11434",
      reachable: false,
      version: null,
      models: [],
      problem: "unreachable",
      error: "Ollama (Gaming-PC) nicht erreichbar: Zeitüberschreitung",
    },
  ],
};

export const statusHandler = (status: SystemStatus) =>
  http.get("*/api/system/status", () => HttpResponse.json(status));

/** Standardantworten, damit jede Seite ohne weitere Einrichtung rendert. */
export const defaultHandlers = [
  statusHandler(healthyStatus),
  http.get("*/api/suggestions", () => HttpResponse.json([])),
  http.get("*/api/hosts", () => HttpResponse.json([])),
  http.get("*/api/jobs", () => HttpResponse.json([])),
  http.get("*/api/changes", () => HttpResponse.json([])),
  http.get("*/api/lessons", () => HttpResponse.json([])),
];

export const server = setupServer(...defaultHandlers);
