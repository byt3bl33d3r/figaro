import ReactMarkdown from 'react-markdown';

interface PromptEditorModalProps {
  prompt: string;
  onPromptChange: (value: string) => void;
  onClose: () => void;
}

export function PromptEditorModal({ prompt, onPromptChange, onClose }: PromptEditorModalProps) {
  return (
    <div className="fixed inset-0 bg-black/80 flex items-center justify-center z-[60]" onClick={onClose}>
      <div className="bg-cctv-panel border border-cctv-border rounded-lg w-full max-w-5xl mx-4 h-[80vh] flex flex-col shadow-xl" onClick={(e) => e.stopPropagation()}>
        {/* Editor Header */}
        <div className="flex items-center justify-between px-4 py-3 border-b border-cctv-border shrink-0">
          <h3 className="text-lg font-semibold text-cctv-text">Task Description</h3>
          <div className="flex items-center gap-3">
            <span className="text-xs text-cctv-text-dim">Supports Markdown</span>
            <button
              type="button"
              onClick={onClose}
              className="text-cctv-text-dim hover:text-cctv-text transition-colors"
            >
              <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
              </svg>
            </button>
          </div>
        </div>

        {/* Editor Body: side-by-side edit + preview */}
        <div className="flex-1 flex min-h-0">
          {/* Edit pane */}
          <div className="flex-1 flex flex-col border-r border-cctv-border min-w-0">
            <div className="px-3 py-1.5 border-b border-cctv-border shrink-0">
              <span className="text-xs font-medium text-cctv-text-dim uppercase tracking-wide">Edit</span>
            </div>
            <textarea
              data-testid="prompt-editor"
              value={prompt}
              onChange={(e) => onPromptChange(e.target.value)}
              placeholder="Describe what the agent should do...&#10;&#10;Supports **Markdown** formatting."
              autoFocus
              className="flex-1 w-full bg-cctv-bg px-4 py-3 text-sm text-cctv-text placeholder-cctv-text-dim resize-none focus:outline-none font-mono"
            />
          </div>

          {/* Preview pane */}
          <div className="flex-1 flex flex-col min-w-0">
            <div className="px-3 py-1.5 border-b border-cctv-border shrink-0">
              <span className="text-xs font-medium text-cctv-text-dim uppercase tracking-wide">Preview</span>
            </div>
            <div className="flex-1 overflow-y-auto px-4 py-3">
              {prompt ? (
                <div className="prose prose-invert prose-sm max-w-none">
                  <ReactMarkdown>{prompt}</ReactMarkdown>
                </div>
              ) : (
                <span className="text-sm text-cctv-text-dim italic">Nothing to preview</span>
              )}
            </div>
          </div>
        </div>

        {/* Editor Footer */}
        <div className="flex justify-end px-4 py-3 border-t border-cctv-border shrink-0">
          <button
            type="button"
            onClick={onClose}
            className="px-4 py-2 bg-cctv-accent text-cctv-bg font-medium text-sm rounded hover:bg-cctv-accent-dim transition-colors"
          >
            Done
          </button>
        </div>
      </div>
    </div>
  );
}
