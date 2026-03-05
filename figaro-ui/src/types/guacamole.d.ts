declare module 'guacamole-common-js' {
  namespace Guacamole {
    class Client {
      constructor(tunnel: Tunnel);
      connect(data?: string): void;
      disconnect(): void;
      getDisplay(): Display;
      sendMouseState(state: Mouse.State): void;
      sendKeyEvent(pressed: 0 | 1, keysym: number): void;
      onstatechange: ((state: number) => void) | null;
      onerror: ((status: Status) => void) | null;
      static readonly State: {
        readonly IDLE: 0;
        readonly CONNECTING: 1;
        readonly WAITING: 2;
        readonly CONNECTED: 3;
        readonly DISCONNECTING: 4;
        readonly DISCONNECTED: 5;
      };
    }

    class Display {
      getElement(): HTMLElement;
      getWidth(): number;
      getHeight(): number;
      scale(scale: number): void;
    }

    class WebSocketTunnel {
      constructor(url: string);
      onerror: ((status: Status) => void) | null;
      onstatechange: ((state: number) => void) | null;
    }

    type Tunnel = WebSocketTunnel;

    class Mouse {
      constructor(element: HTMLElement);
      onEach(events: string[], handler: (e: Mouse.Event) => void): void;
      onmousedown: ((state: Mouse.State) => void) | null;
      onmouseup: ((state: Mouse.State) => void) | null;
      onmousemove: ((state: Mouse.State) => void) | null;
    }

    namespace Mouse {
      interface State {
        x: number;
        y: number;
        left: boolean;
        middle: boolean;
        right: boolean;
        up: boolean;
        down: boolean;
      }

      interface Event {
        state: State;
      }
    }

    class Keyboard {
      constructor(element: HTMLElement | Document);
      onkeydown: ((keysym: number) => boolean | void) | null;
      onkeyup: ((keysym: number) => void) | null;
      reset(): void;
    }

    class Status {
      constructor(code: number, message?: string);
      code: number;
      message?: string;
      isError(): boolean;
    }
  }

  export default Guacamole;
}
