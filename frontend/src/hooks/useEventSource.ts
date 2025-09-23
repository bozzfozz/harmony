import { useEffect, useRef } from "react";

type EventSourceHandler<T> = (data: T) => void;

type Options = {
  event?: string;
  enabled?: boolean;
};

const useEventSource = <T,>(url: string, handler: EventSourceHandler<T>, options: Options = {}) => {
  const handlerRef = useRef(handler);
  handlerRef.current = handler;

  useEffect(() => {
    if (typeof window === "undefined" || options.enabled === false) {
      return undefined;
    }

    const source = new EventSource(url, { withCredentials: false });
    const listener = (event: MessageEvent) => {
      try {
        const payload = JSON.parse(event.data) as T;
        handlerRef.current(payload);
      } catch (error) {
        console.error("Failed to parse event source payload", error);
      }
    };

    if (options.event) {
      source.addEventListener(options.event, listener);
    } else {
      source.onmessage = listener;
    }

    source.onerror = (error) => {
      console.error("EventSource error", error);
    };

    return () => {
      if (options.event) {
        source.removeEventListener(options.event, listener);
      }
      source.close();
    };
  }, [url, options.enabled, options.event]);
};

export default useEventSource;
