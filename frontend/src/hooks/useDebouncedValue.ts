import { useEffect, useState } from 'react';

const useDebouncedValue = <T>(value: T, delay = 250): T => {
  const [debounced, setDebounced] = useState(value);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      setDebounced(value);
    }, delay);
    return () => window.clearTimeout(timer);
  }, [value, delay]);

  return debounced;
};

export default useDebouncedValue;
