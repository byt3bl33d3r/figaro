import { useGuacamole } from '../hooks/useGuacamole';

interface VNCViewerProps {
  workerId: string | undefined;
  viewOnly?: boolean;
  className?: string;
  onConnect?: () => void;
  onDisconnect?: () => void;
}

export function VNCViewer({
  workerId,
  viewOnly = true,
  className = '',
  onConnect,
  onDisconnect,
}: VNCViewerProps) {
  const { containerRef, connected, connecting, error } = useGuacamole({
    workerId,
    viewOnly,
    onConnect,
    onDisconnect,
  });

  return (
    <div className={`relative ${className}`}>
      <div
        ref={containerRef}
        className="vnc-container w-full h-full bg-black"
      />
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
          ) : !workerId ? (
            <div className="text-cctv-text-dim">No Desktop URL</div>
          ) : (
            <div className="text-cctv-text-dim">Disconnected</div>
          )}
        </div>
      )}
    </div>
  );
}
