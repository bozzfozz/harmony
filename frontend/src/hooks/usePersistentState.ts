import { Dispatch, SetStateAction, useCallback, useEffect, useRef, useState } from 'react';

type InitialValue<T> = T | (() => T);

const getStorage = (): Storage | null => {
  if (typeof window === 'undefined') {
    return null;
  }
  try {
    return window.localStorage;
  } catch (error) {
    return null;
  }
};

const resolveInitialValue = <T,>(value: InitialValue<T>): T => {
  return typeof value === 'function' ? (value as () => T)() : value;
};

const readStoredValue = <T,>(storage: Storage | null, key: string, fallback: InitialValue<T>): T => {
  if (!storage) {
    return resolveInitialValue(fallback);
  }
  try {
    const rawValue = storage.getItem(key);
    if (rawValue === null) {
      return resolveInitialValue(fallback);
    }
    return JSON.parse(rawValue) as T;
  } catch (error) {
    return resolveInitialValue(fallback);
  }
};

export const usePersistentState = <T,>(
  key: string,
  initialValue: InitialValue<T>
): [T, Dispatch<SetStateAction<T>>] => {
  const initialValueRef = useRef(initialValue);
  const storageRef = useRef<Storage | null>(null);

  const [value, setValue] = useState<T>(() => {
    const storage = getStorage();
    storageRef.current = storage;
    return readStoredValue(storage, key, initialValueRef.current);
  });

  useEffect(() => {
    const storage = getStorage();
    storageRef.current = storage;
    const storedValue = readStoredValue(storage, key, initialValueRef.current);
    setValue((previous) => (Object.is(previous, storedValue) ? previous : storedValue));
  }, [key]);

  const persistValue = useCallback(
    (newValue: SetStateAction<T>) => {
      setValue((previous) => {
        const resolvedValue =
          typeof newValue === 'function' ? (newValue as (current: T) => T)(previous) : newValue;

        const storage = storageRef.current ?? getStorage();
        storageRef.current = storage;

        if (storage) {
          try {
            storage.setItem(key, JSON.stringify(resolvedValue));
          } catch (error) {
            // Swallow storage errors to keep UI responsive when persistence fails.
          }
        }

        return resolvedValue;
      });
    },
    [key]
  );

  return [value, persistValue];
};
