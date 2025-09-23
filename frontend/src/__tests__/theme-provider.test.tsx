import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { ThemeProvider } from '../components/theme-provider';
import { useTheme } from '../hooks/useTheme';

const ThemeConsumer = () => {
  const { theme, setTheme } = useTheme();
  return (
    <button type="button" onClick={() => setTheme(theme === 'light' ? 'dark' : 'light')}>
      Current: {theme}
    </button>
  );
};

describe('ThemeProvider', () => {
  it('toggles the theme and updates document class', async () => {
    render(
      <ThemeProvider>
        <ThemeConsumer />
      </ThemeProvider>
    );
    const button = screen.getByRole('button');
    await waitFor(() => {
      expect(document.documentElement.classList.contains('light')).toBe(true);
    });
    act(() => {
      fireEvent.click(button);
    });
    await waitFor(() => {
      expect(document.documentElement.classList.contains('dark')).toBe(true);
    });
  });
});
