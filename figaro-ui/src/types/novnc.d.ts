declare module '@novnc/novnc/lib/rfb.js' {
  interface RFBOptions {
    credentials?: {
      username?: string;
      password?: string;
      target?: string;
    };
    shared?: boolean;
    repeaterID?: string;
    wsProtocols?: string[];
  }

  interface RFBCapabilities {
    power: boolean;
  }

  export default class RFB extends EventTarget {
    constructor(target: HTMLElement, url: string, options?: RFBOptions);

    // Properties
    viewOnly: boolean;
    focusOnClick: boolean;
    clipViewport: boolean;
    dragViewport: boolean;
    scaleViewport: boolean;
    resizeSession: boolean;
    showDotCursor: boolean;
    background: string;
    qualityLevel: number;
    compressionLevel: number;
    capabilities: RFBCapabilities;

    // Methods
    disconnect(): void;
    sendCredentials(credentials: { username?: string; password?: string; target?: string }): void;
    sendKey(keysym: number, code: string | null, down?: boolean): void;
    sendCtrlAltDel(): void;
    focus(): void;
    blur(): void;
    machineShutdown(): void;
    machineReboot(): void;
    machineReset(): void;
    clipboardPasteFrom(text: string): void;

    // Event handling
    addEventListener(
      type: 'connect',
      listener: (e: Event) => void,
      options?: boolean | AddEventListenerOptions
    ): void;
    addEventListener(
      type: 'disconnect',
      listener: (e: { detail: { clean: boolean } }) => void,
      options?: boolean | AddEventListenerOptions
    ): void;
    addEventListener(
      type: 'credentialsrequired',
      listener: (e: Event) => void,
      options?: boolean | AddEventListenerOptions
    ): void;
    addEventListener(
      type: 'securityfailure',
      listener: (e: { detail: { status: number; reason: string } }) => void,
      options?: boolean | AddEventListenerOptions
    ): void;
    addEventListener(
      type: 'clipboard',
      listener: (e: { detail: { text: string } }) => void,
      options?: boolean | AddEventListenerOptions
    ): void;
    addEventListener(
      type: 'bell',
      listener: (e: Event) => void,
      options?: boolean | AddEventListenerOptions
    ): void;
    addEventListener(
      type: 'desktopname',
      listener: (e: { detail: { name: string } }) => void,
      options?: boolean | AddEventListenerOptions
    ): void;
    addEventListener(
      type: 'capabilities',
      listener: (e: { detail: { capabilities: RFBCapabilities } }) => void,
      options?: boolean | AddEventListenerOptions
    ): void;
  }
}
