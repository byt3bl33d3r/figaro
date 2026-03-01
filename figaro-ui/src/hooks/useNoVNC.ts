import { useEffect, useRef, useCallback, useState } from 'react';

// Type for the RFB class (loaded dynamically)
interface RFBInstance {
  viewOnly: boolean;
  scaleViewport: boolean;
  clipViewport: boolean;
  resizeSession: boolean;
  disconnect: () => void;
  sendKey: (keysym: number, code: string | null, down?: boolean) => void;
  sendCtrlAltDel: () => void;
  focus: () => void;
  addEventListener: (type: string, listener: (e: any) => void) => void;
}

interface RFBConstructor {
  new (
    target: HTMLElement,
    url: string,
    options?: { credentials?: { username?: string; password?: string } }
  ): RFBInstance;
}

interface UseNoVNCOptions {
  url: string | undefined;
  username?: string;
  password?: string;
  viewOnly?: boolean;
  scaleViewport?: boolean;
  clipViewport?: boolean;
  onConnect?: () => void;
  onDisconnect?: (clean: boolean) => void;
  onSecurityFailure?: (e: { detail: { status: number; reason: string } }) => void;
}

interface UseNoVNCReturn {
  containerRef: React.RefObject<HTMLDivElement>;
  connected: boolean;
  connecting: boolean;
  error: string | null;
  disconnect: () => void;
  sendKey: (keysym: number, down: boolean) => void;
  sendCtrlAltDel: () => void;
  focus: () => void;
}

// Cache the RFB class after loading
let RFBClass: RFBConstructor | null = null;
let loadPromise: Promise<RFBConstructor> | null = null;

async function loadRFB(): Promise<RFBConstructor> {
  if (RFBClass) return RFBClass;
  if (loadPromise) return loadPromise;

  loadPromise = import('@novnc/novnc/lib/rfb.js').then((module) => {
    RFBClass = module.default as RFBConstructor;
    return RFBClass;
  });

  return loadPromise;
}

const RECONNECT_BASE_DELAY = 1000;
const RECONNECT_MAX_DELAY = 15000;
const RECONNECT_MAX_ATTEMPTS = 20;

export function useNoVNC(options: UseNoVNCOptions): UseNoVNCReturn {
  const {
    url,
    username,
    password = import.meta.env.VITE_VNC_DEFAULT_PASSWORD || '',
    viewOnly = true,
    scaleViewport = true,
    clipViewport = false,
    onConnect,
    onDisconnect,
    onSecurityFailure,
  } = options;

  const containerRef = useRef<HTMLDivElement>(null);
  const rfbRef = useRef<RFBInstance | null>(null);
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
    if (rfbRef.current) {
      rfbRef.current.disconnect();
      rfbRef.current = null;
    }
    setConnected(false);
    setConnecting(false);
  }, [clearReconnectTimer]);

  const sendKey = useCallback((keysym: number, down: boolean) => {
    rfbRef.current?.sendKey(keysym, null, down);
  }, []);

  const sendCtrlAltDel = useCallback(() => {
    rfbRef.current?.sendCtrlAltDel();
  }, []);

  const focus = useCallback(() => {
    rfbRef.current?.focus();
  }, []);

  useEffect(() => {
    if (!url || !containerRef.current) {
      return;
    }

    // Clean up previous connection
    disconnect();
    setError(null);
    setConnecting(true);
    reconnectAttemptRef.current = 0;

    let cancelled = false;

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
          connect();
        }
      }, delay);
    }

    async function connect() {
      if (cancelled || !containerRef.current) {
        return;
      }

      try {
        const RFB = await loadRFB();

        if (cancelled || !containerRef.current) {
          return;
        }

        // noVNC appends a canvas to the container — clear stale children from previous attempts
        while (containerRef.current.firstChild) {
          containerRef.current.removeChild(containerRef.current.firstChild);
        }

        const creds: { username?: string; password?: string } = {};
        if (username) creds.username = username;
        if (password) creds.password = password;
        const rfb = new RFB(containerRef.current, url!, {
          credentials: Object.keys(creds).length > 0 ? creds : undefined,
        });

        rfb.viewOnly = viewOnly;
        rfb.scaleViewport = scaleViewport;
        rfb.clipViewport = clipViewport;
        rfb.resizeSession = false;

        rfb.addEventListener('connect', () => {
          if (!cancelled) {
            reconnectAttemptRef.current = 0;
            setConnected(true);
            setConnecting(false);
            setError(null);
            onConnect?.();
          }
        });

        rfb.addEventListener('disconnect', (e: { detail: { clean: boolean } }) => {
          if (!cancelled) {
            setConnected(false);
            setConnecting(false);
            rfbRef.current = null;
            onDisconnect?.(e.detail.clean);
            // Reconnect on any disconnect — the proxy may close cleanly
            // on orchestrator restart. The `cancelled` flag prevents
            // reconnection when the user explicitly calls disconnect().
            scheduleReconnect();
          }
        });

        rfb.addEventListener('securityfailure', (e: { detail: { status: number; reason: string } }) => {
          if (!cancelled) {
            setError(`Security failure: ${e.detail.reason}`);
            setConnecting(false);
            onSecurityFailure?.(e);
          }
        });

        rfbRef.current = rfb;
      } catch (err) {
        if (!cancelled) {
          setError(String(err));
          setConnecting(false);
          scheduleReconnect();
        }
      }
    }

    connect();

    return () => {
      cancelled = true;
      clearReconnectTimer();
      disconnect();
    };
  }, [url, username, password, viewOnly, scaleViewport, clipViewport, disconnect, clearReconnectTimer, onConnect, onDisconnect, onSecurityFailure]);

  // Update viewOnly when it changes
  useEffect(() => {
    if (rfbRef.current) {
      rfbRef.current.viewOnly = viewOnly;
    }
  }, [viewOnly]);

  return {
    containerRef: containerRef as React.RefObject<HTMLDivElement>,
    connected,
    connecting,
    error,
    disconnect,
    sendKey,
    sendCtrlAltDel,
    focus,
  };
}
