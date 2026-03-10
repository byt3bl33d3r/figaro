import { useEffect, useRef, useCallback, useState } from 'react';
import Guacamole from 'guacamole-common-js';
import { getGuacamoleToken, getGuacamoleWsUrl } from '../api/guacamole';

interface UseGuacamoleOptions {
  workerId: string | undefined;
  viewOnly?: boolean;
  onConnect?: () => void;
  onDisconnect?: () => void;
}

interface UseGuacamoleReturn {
  containerRef: React.RefObject<HTMLDivElement>;
  connected: boolean;
  connecting: boolean;
  error: string | null;
  disconnect: () => void;
}

const RECONNECT_BASE_DELAY = 1000;
const RECONNECT_MAX_DELAY = 15000;
const RECONNECT_MAX_ATTEMPTS = 20;

function updateScale(client: Guacamole.Client, container: HTMLElement): void {
  const display = client.getDisplay();
  const displayWidth = display.getWidth();
  const displayHeight = display.getHeight();
  if (!displayWidth || !displayHeight) return;
  const scale = Math.min(
    container.clientWidth / displayWidth,
    container.clientHeight / displayHeight,
  );
  display.scale(scale);
}

export function useGuacamole(options: UseGuacamoleOptions): UseGuacamoleReturn {
  const {
    workerId,
    viewOnly = true,
    onConnect,
    onDisconnect,
  } = options;

  const containerRef = useRef<HTMLDivElement>(null);
  const clientRef = useRef<Guacamole.Client | null>(null);
  const keyboardRef = useRef<Guacamole.Keyboard | null>(null);
  const reconnectTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const reconnectAttemptRef = useRef(0);
  const [connected, setConnected] = useState(false);
  const [connecting, setConnecting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const clearReconnectTimer = useCallback(() => {
    if (reconnectTimerRef.current) {
      clearTimeout(reconnectTimerRef.current);
      reconnectTimerRef.current = null;
    }
  }, []);

  const disconnect = useCallback(() => {
    clearReconnectTimer();
    if (keyboardRef.current) {
      keyboardRef.current.onkeydown = null;
      keyboardRef.current.onkeyup = null;
      keyboardRef.current.reset();
      keyboardRef.current = null;
    }
    if (clientRef.current) {
      clientRef.current.disconnect();
      clientRef.current = null;
    }
    setConnected(false);
    setConnecting(false);
  }, [clearReconnectTimer]);

  useEffect(() => {
    if (!workerId || !containerRef.current) {
      return;
    }

    // Clean up previous connection and reset state for new connection attempt.
    // These setState calls are intentional — they synchronize UI state with the
    // external Guacamole connection lifecycle at the start of a new effect.
    clearReconnectTimer();
    if (keyboardRef.current) {
      keyboardRef.current.onkeydown = null;
      keyboardRef.current.onkeyup = null;
      keyboardRef.current.reset();
      keyboardRef.current = null;
    }
    if (clientRef.current) {
      clientRef.current.disconnect();
      clientRef.current = null;
    }
    // eslint-disable-next-line react-hooks/set-state-in-effect -- intentional: sync UI state with external connection lifecycle
    setConnected(false);
    setConnecting(true);
    setError(null);
    reconnectAttemptRef.current = 0;

    let cancelled = false;
    let resizeObserver: ResizeObserver | null = null;

    function scheduleReconnect() {
      if (cancelled) return;
      if (reconnectAttemptRef.current >= RECONNECT_MAX_ATTEMPTS) {
        setError('Connection failed — max retries reached');
        setConnecting(false);
        return;
      }
      const delay = Math.min(
        RECONNECT_BASE_DELAY * Math.pow(2, reconnectAttemptRef.current),
        RECONNECT_MAX_DELAY,
      );
      reconnectAttemptRef.current++;
      setConnecting(true);
      setError(`Reconnecting in ${Math.round(delay / 1000)}s...`);
      reconnectTimerRef.current = setTimeout(() => {
        if (!cancelled) {
          connectGuacamole();
        }
      }, delay);
    }

    async function connectGuacamole() {
      if (cancelled || !containerRef.current) {
        return;
      }

      try {
        const token = await getGuacamoleToken(workerId!);

        if (cancelled || !containerRef.current) {
          return;
        }

        const wsUrl = getGuacamoleWsUrl(token);
        const tunnel = new Guacamole.WebSocketTunnel(wsUrl);
        const client = new Guacamole.Client(tunnel);

        client.onstatechange = (state: number) => {
          if (cancelled) return;

          if (state === 3) {
            // CONNECTED
            reconnectAttemptRef.current = 0;
            setConnected(true);
            setConnecting(false);
            setError(null);
            onConnect?.();

            // Append display element to container
            if (containerRef.current) {
              while (containerRef.current.firstChild) {
                containerRef.current.removeChild(containerRef.current.firstChild);
              }
              const display = client.getDisplay();
              const displayElement = display.getElement();
              displayElement.style.margin = '0 auto';
              containerRef.current.appendChild(displayElement);
              updateScale(client, containerRef.current);

              // Rescale when the remote desktop resizes
              display.onresize = () => {
                if (containerRef.current && clientRef.current) {
                  updateScale(clientRef.current, containerRef.current);
                }
              };

              // Set up input handlers if not viewOnly
              if (!viewOnly) {
                const mouse = new Guacamole.Mouse(displayElement);
                const scaleMouse = (state: Guacamole.Mouse.State) => {
                  const scale = display.getScale();
                  const scaled: Guacamole.Mouse.State = {
                    x: state.x / scale,
                    y: state.y / scale,
                    left: state.left,
                    middle: state.middle,
                    right: state.right,
                    up: state.up,
                    down: state.down,
                  };
                  client.sendMouseState(scaled);
                };
                mouse.onmousedown = scaleMouse;
                mouse.onmouseup = scaleMouse;
                mouse.onmousemove = scaleMouse;

                const keyboard = new Guacamole.Keyboard(document);
                keyboardRef.current = keyboard;
                keyboard.onkeydown = (keysym) => {
                  client.sendKeyEvent(1, keysym);
                  return false;
                };
                keyboard.onkeyup = (keysym) => {
                  client.sendKeyEvent(0, keysym);
                };
              }

              // Set up resize observer for scaling
              try {
                resizeObserver = new ResizeObserver(() => {
                  if (containerRef.current && clientRef.current) {
                    updateScale(clientRef.current, containerRef.current);
                  }
                });
                resizeObserver.observe(containerRef.current);
              } catch {
                // ResizeObserver not available (e.g. in test environments)
              }
            }
          } else if (state === 5) {
            // DISCONNECTED
            setConnected(false);
            setConnecting(false);
            clientRef.current = null;
            onDisconnect?.();
            scheduleReconnect();
          }
        };

        client.onerror = (status: Guacamole.Status) => {
          if (!cancelled) {
            setError(status.message ?? `Guacamole error: ${status.code}`);
          }
        };

        clientRef.current = client;
        client.connect('');
      } catch (err) {
        if (!cancelled) {
          setError(String(err));
          setConnecting(false);
          scheduleReconnect();
        }
      }
    }

    connectGuacamole();

    return () => {
      cancelled = true;
      clearReconnectTimer();
      if (resizeObserver) {
        try { resizeObserver.disconnect(); } catch { /* noop */ }
      }
      disconnect();
    };
  }, [workerId, viewOnly, disconnect, clearReconnectTimer, onConnect, onDisconnect]);

  return {
    containerRef: containerRef as React.RefObject<HTMLDivElement>,
    connected,
    connecting,
    error,
    disconnect,
  };
}
