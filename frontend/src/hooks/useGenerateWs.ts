import { useCallback, useEffect, useRef, useState } from "react";

export interface ProgressEvent {
  stage: string;
  message: string;
  progress?: number;
  status?: string;
  completed?: number;
  total?: number;
  plan?: { part_title: string; title: string }[];
  pdf?: boolean;
  level?: "info" | "warning" | "error" | "success";
  detail?: string;
  judge_score?: number;
  tokens?: {
    calls: number;
    input_tokens: number;
    output_tokens: number;
    total_tokens: number;
  };
  /** Graph visualization fields */
  node?: string;
  action?: string;
  chapters?: { name: string; sections: number }[];
  documents?: string[];
  chapter?: string;
  chapter_done?: number;
  chapter_total?: number;
  /** Web research results — sources found during research phase */
  research_results?: { title: string; url: string; source: string }[];
}

export function useGenerateWs(projectId: string) {
  const [events, setEvents] = useState<ProgressEvent[]>([]);
  const [latest, setLatest] = useState<ProgressEvent | null>(null);
  const [running, setRunning] = useState(false);
  const wsRef = useRef<WebSocket | null>(null);

  const start = useCallback(
    (
      providerId: number,
      model?: string,
      roleProviders?: Record<
        string,
        { provider_id: number; model?: string }
      >,
    ) => {
      setEvents([]);
      setLatest(null);
      setRunning(true);

      const proto = location.protocol === "https:" ? "wss" : "ws";
      const ws = new WebSocket(
        `${proto}://${location.host}/ws/generate/${projectId}`,
      );
      wsRef.current = ws;

      ws.onopen = () => {
        ws.send(
          JSON.stringify({
            provider_id: providerId,
            model,
            role_providers: roleProviders,
          }),
        );
      };
      ws.onmessage = (e) => {
        const data: ProgressEvent = JSON.parse(e.data);
        setEvents((prev) => [...prev, data]);
        setLatest(data);
        if (
          data.stage === "done" ||
          data.stage === "error" ||
          data.stage === "stopped"
        ) {
          setRunning(false);
        }
      };
      ws.onclose = () => setRunning(false);
      ws.onerror = () => setRunning(false);
    },
    [projectId],
  );

  const stop = useCallback(() => {
    wsRef.current?.send(JSON.stringify({ action: "stop" }));
  }, []);

  useEffect(() => {
    return () => wsRef.current?.close();
  }, []);

  return { events, latest, running, start, stop };
}
