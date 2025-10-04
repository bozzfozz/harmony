import * as React from 'react';

import type { ToastVariant } from './toast';

const TOAST_LIMIT = 3;
const TOAST_REMOVE_DELAY = 6000;

type ToastRecord = {
  id: string;
  title?: React.ReactNode;
  description?: React.ReactNode;
  action?: React.ReactNode;
  open?: boolean;
  duration?: number;
  variant?: ToastVariant;
  onOpenChange?: (open: boolean) => void;
};

type ToastState = {
  toasts: ToastRecord[];
};

type ToastAction =
  | { type: 'ADD_TOAST'; toast: ToastRecord }
  | { type: 'UPDATE_TOAST'; toast: Partial<ToastRecord> & { id: string } }
  | { type: 'DISMISS_TOAST'; toastId?: string }
  | { type: 'REMOVE_TOAST'; toastId?: string };

const toastTimeouts = new Map<string, ReturnType<typeof setTimeout>>();

const addToRemoveQueue = (toastId: string) => {
  if (toastTimeouts.has(toastId)) {
    return;
  }

  const timeout = setTimeout(() => {
    toastTimeouts.delete(toastId);
    dispatch({ type: 'REMOVE_TOAST', toastId });
  }, TOAST_REMOVE_DELAY);

  toastTimeouts.set(toastId, timeout);
};

const toastReducer = (state: ToastState, action: ToastAction): ToastState => {
  switch (action.type) {
    case 'ADD_TOAST':
      return {
        ...state,
        toasts: [...state.toasts, action.toast].slice(-TOAST_LIMIT)
      };
    case 'UPDATE_TOAST':
      return {
        ...state,
        toasts: state.toasts.map((toast) =>
          toast.id === action.toast.id ? { ...toast, ...action.toast } : toast
        )
      };
    case 'DISMISS_TOAST':
      return {
        ...state,
        toasts: state.toasts.map((toast) =>
          toast.id === action.toastId || action.toastId === undefined
            ? { ...toast, open: false }
            : toast
        )
      };
    case 'REMOVE_TOAST':
      if (action.toastId === undefined) {
        return { ...state, toasts: [] };
      }
      return {
        ...state,
        toasts: state.toasts.filter((toast) => toast.id !== action.toastId)
      };
    default:
      return state;
  }
};

const listeners = new Set<(state: ToastState) => void>();

let memoryState: ToastState = { toasts: [] };

const dispatch = (action: ToastAction) => {
  memoryState = toastReducer(memoryState, action);
  listeners.forEach((listener) => listener(memoryState));
};

const createToastId = () => {
  if (typeof crypto !== 'undefined' && 'randomUUID' in crypto) {
    return crypto.randomUUID();
  }
  return Math.random().toString(36).slice(2);
};

export const toast = ({ id, ...props }: Omit<ToastRecord, 'id' | 'onOpenChange'> & { id?: string }) => {
  const toastId = id ?? createToastId();

  const onOpenChange = (open: boolean) => {
    dispatch({
      type: 'UPDATE_TOAST',
      toast: { id: toastId, open }
    });
    if (!open) {
      addToRemoveQueue(toastId);
    }
  };

  dispatch({
    type: 'ADD_TOAST',
    toast: {
      ...props,
      id: toastId,
      open: true,
      variant: props.variant ?? 'default',
      onOpenChange
    }
  });

  return toastId;
};

export const dismiss = (toastId?: string) => {
  dispatch({ type: 'DISMISS_TOAST', toastId });
  if (toastId) {
    addToRemoveQueue(toastId);
  } else {
    memoryState.toasts.forEach((toast) => addToRemoveQueue(toast.id));
  }
};

export const useToast = () => {
  const [state, setState] = React.useState<ToastState>(memoryState);

  React.useEffect(() => {
    listeners.add(setState);
    return () => {
      listeners.delete(setState);
    };
  }, []);

  return {
    ...state,
    toast,
    dismiss
  };
};

export type { ToastRecord as InternalToastRecord, ToastVariant };
