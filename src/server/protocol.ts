import { WebSocket } from "ws";

export type Send = (type: string | Buffer, payload?: object) => void;

/**
 * createSend returns a Send function bound to a WebSocket.
 * - Binary Buffer: sent as-is (raw audio frames to browser)
 * - String type: JSON-serialised as { type, ...payload }
 * - No-op if the socket is not OPEN — safe to call after close
 */
export function createSend(ws: WebSocket): Send {
    return (type, payload) => {
        if (ws.readyState !== WebSocket.OPEN) return;
        if (Buffer.isBuffer(type)) {
            ws.send(type);
        } else {
            ws.send(JSON.stringify({ type, ...(payload ?? {}) }));
        }
    };
}