import { useNoVNC } from '../hooks/useNoVNC';

interface VNCViewerProps {
  url: string | undefined;
  username?: string;
  password?: string;
  viewOnly?: boolean;
  className?: string;
  onConnect?: () => void;
  onDisconnect?: (clean: boolean) => void;
}

export function VNCViewer({
  url,
  username,
  password,
  viewOnly = true,
  className = '',
  onConnect,
  onDisconnect,
}: VNCViewerProps) {
  const { containerRef, connected, connecting, error } = useNoVNC({
    url,
    username,
    password,
    viewOnly,
    scaleViewport: true,
    onConnect,
    onDisconnect,
  });

  return (
    <div className={`relative ${className}`}>
      {/* VNC Canvas Container */}
      <div
        ref={containerRef}
        className="vnc-container w-full h-full bg-black"
      />

      {/* Connection Status Overlay */}
      {!connected && (
        <div className="absolute inset-0 flex items-center justify-center bg-cctv-bg/80">
          {connecting ? (
            <div className="text-cctv-text-dim animate-pulse">
              Connecting...
            </div>
          ) : error ? (
            <div className="text-center p-4">
              <div className="text-cctv-error mb-2">Connection Error</div>
              <div className="text-cctv-text-dim text-sm">{error}</div>
            </div>
          ) : !url ? (
            <div className="text-cctv-text-dim">No VNC URL</div>
          ) : (
            <div className="text-cctv-text-dim">Disconnected</div>
          )}
        </div>
      )}
    </div>
  );
}
