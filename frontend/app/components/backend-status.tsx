"use client";

import { useCallback, useEffect, useState } from "react";

type HealthStatus = "checking" | "connected" | "unavailable";

const apiBaseUrl =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://127.0.0.1:8001/api/v1";

export default function BackendStatus() {
  const [status, setStatus] = useState<HealthStatus>("checking");
  const [attempt, setAttempt] = useState(0);

  const checkHealth = useCallback(async (signal: AbortSignal) => {
    try {
      const response = await fetch(`${apiBaseUrl}/health`, {
        signal,
        cache: "no-store",
      });
      if (!response.ok) {
        setStatus("unavailable");
        return;
      }
      const result: unknown = await response.json();
      setStatus(
        typeof result === "object" &&
          result !== null &&
          "status" in result &&
          result.status === "ok"
          ? "connected"
          : "unavailable",
      );
    } catch (error) {
      if (error instanceof DOMException && error.name === "AbortError") {
        return;
      }
      setStatus("unavailable");
    }
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    const timeout = window.setTimeout(() => controller.abort(), 4000);
    void checkHealth(controller.signal);
    return () => {
      window.clearTimeout(timeout);
      controller.abort();
    };
  }, [attempt, checkHealth]);

  const label =
    status === "checking"
      ? "Connecting to API"
      : status === "connected"
        ? "API connected"
        : "API unavailable";

  return (
    <button
      className={`api-status api-status-${status}`}
      type="button"
      onClick={() => {
        setStatus("checking");
        setAttempt((current) => current + 1);
      }}
      aria-label={`${label}. Click to retry.`}
      title={`${label}. Click to retry.`}
    >
      <span className="status-indicator" />
      <span>{label}</span>
      {status === "unavailable" && <span className="retry-label">Retry</span>}
    </button>
  );
}
