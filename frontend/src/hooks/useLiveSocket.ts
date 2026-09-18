/**
 * WebSocket connection to the pipeline.
 *
 * Two decisions worth calling out:
 *
 * 1. **History lives in a ref, not in state.** At 10x speed the backend emits
 *    ten frames a second. Pushing every frame into React state would re-render
 *    the entire dashboard ten times a second and make the charts stutter.
 *    Instead frames accumulate in a ref and a single interval publishes a
 *    snapshot at a fixed, comfortable rate. The *latest* frame is still state,
 *    so the headline numbers stay instant.
 *
 * 2. **Reconnection backs off.** If the backend is restarted the socket
 *    reconnects on an exponential backoff rather than hammering the port.
 */

import { useCallback, useEffect, useRef, useState } from "react";

import type {
  Alert,
  ApplianceEvent,
  LiveFrame,
  SimulationStatus,
  SocketMessage,
} from "@/types";

/** How many frames of chart history to retain in the browser. */
const HISTORY_LIMIT = 900;

/** How often the accumulated history is published to React, in ms. */
const PUBLISH_INTERVAL_MS = 250;

const MAX_ALERTS = 60;
const MAX_EVENTS = 120;

export type ConnectionState = "connecting" | "open" | "closed";

export interface LiveData {
  frame: LiveFrame | null;
  history: LiveFrame[];
  status: SimulationStatus | null;
  alerts: Alert[];
  events: ApplianceEvent[];
  connection: ConnectionState;
  /** Frames received since the socket opened; a cheap liveness indicator. */
  received: number;
  refreshStatus: () => void;
}

function socketUrl(): string {
  const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  return `${protocol}//${window.location.host}/ws`;
}

export function useLiveSocket(): LiveData {
  const [frame, setFrame] = useState<LiveFrame | null>(null);
  const [history, setHistory] = useState<LiveFrame[]>([]);
  const [status, setStatus] = useState<SimulationStatus | null>(null);
  const [alerts, setAlerts] = useState<Alert[]>([]);
  const [events, setEvents] = useState<ApplianceEvent[]>([]);
  const [connection, setConnection] = useState<ConnectionState>("connecting");
  const [received, setReceived] = useState(0);

  const socketRef = useRef<WebSocket | null>(null);
  const historyRef = useRef<LiveFrame[]>([]);
  const dirtyRef = useRef(false);
  const retryRef = useRef(0);
  const closedByUs = useRef(false);

  const refreshStatus = useCallback(() => {
    socketRef.current?.send(JSON.stringify({ type: "resync" }));
  }, []);

  useEffect(() => {
    let reconnectTimer: number | undefined;

    const connect = () => {
      setConnection("connecting");
      const socket = new WebSocket(socketUrl());
      socketRef.current = socket;

      socket.onopen = () => {
        retryRef.current = 0;
        setConnection("open");
      };

      socket.onmessage = (event) => {
        const message = JSON.parse(event.data as string) as SocketMessage;

        switch (message.type) {
          case "frame": {
            const incoming = message.data;
            setFrame(incoming);
            setReceived((count) => count + 1);

            historyRef.current.push(incoming);
            if (historyRef.current.length > HISTORY_LIMIT) {
              historyRef.current.splice(
                0,
                historyRef.current.length - HISTORY_LIMIT,
              );
            }
            dirtyRef.current = true;

            // Alerts and events are rare, so they can update immediately
            // without any risk of a render storm.
            if (incoming.alerts.length) {
              setAlerts((previous) =>
                [...incoming.alerts, ...previous].slice(0, MAX_ALERTS),
              );
            }
            if (incoming.events.length) {
              setEvents((previous) =>
                [...incoming.events, ...previous].slice(0, MAX_EVENTS),
              );
            }
            break;
          }

          case "status":
            setStatus(message.data);
            break;

          case "snapshot": {
            historyRef.current = message.data.frames.slice(-HISTORY_LIMIT);
            setHistory([...historyRef.current]);
            const last = historyRef.current.at(-1);
            if (last) setFrame(last);
            setAlerts(message.data.alerts.slice(0, MAX_ALERTS));
            setEvents(message.data.events.slice(0, MAX_EVENTS));
            break;
          }

          case "pong":
            break;
        }
      };

      socket.onclose = () => {
        setConnection("closed");
        if (closedByUs.current) return;
        // Exponential backoff, capped, so a backend restart is picked up
        // quickly but an unreachable server is not hammered.
        retryRef.current = Math.min(retryRef.current + 1, 6);
        const delay = Math.min(500 * 2 ** (retryRef.current - 1), 10_000);
        reconnectTimer = window.setTimeout(connect, delay);
      };

      socket.onerror = () => socket.close();
    };

    connect();

    // Publish accumulated history at a steady rate rather than per frame.
    const publisher = window.setInterval(() => {
      if (!dirtyRef.current) return;
      dirtyRef.current = false;
      setHistory([...historyRef.current]);
    }, PUBLISH_INTERVAL_MS);

    // Keep-alive: some proxies drop an idle socket after 30-60 seconds.
    const heartbeat = window.setInterval(() => {
      if (socketRef.current?.readyState === WebSocket.OPEN) {
        socketRef.current.send(JSON.stringify({ type: "ping" }));
      }
    }, 20_000);

    return () => {
      closedByUs.current = true;
      window.clearInterval(publisher);
      window.clearInterval(heartbeat);
      if (reconnectTimer) window.clearTimeout(reconnectTimer);
      socketRef.current?.close();
    };
  }, []);

  return {
    frame,
    history,
    status,
    alerts,
    events,
    connection,
    received,
    refreshStatus,
  };
}
