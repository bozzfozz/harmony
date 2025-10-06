import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { ReactNode } from 'react';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue
} from '../components/ui/select';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '../components/ui/tabs';
import * as SwitchPrimitive from '@radix-ui/react-switch';
import * as ToastPrimitive from '@radix-ui/react-toast';

const renderWithToastProvider = (ui: ReactNode) => {
  return render(
    <ToastPrimitive.Provider swipeDirection="right" duration={2000}>
      {ui}
      <ToastPrimitive.Viewport />
    </ToastPrimitive.Provider>
  );
};

describe('Radix primitives smoke tests', () => {
  it('allows selecting options via keyboard and pointer', async () => {
    const onValueChange = jest.fn();
    const user = userEvent.setup();

    render(
      <Select onValueChange={onValueChange} defaultValue="one">
        <SelectTrigger aria-label="Example select">
          <SelectValue placeholder="Select an option" />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value="one">One</SelectItem>
          <SelectItem value="two">Two</SelectItem>
          <SelectItem value="three">Three</SelectItem>
        </SelectContent>
      </Select>
    );

    const trigger = screen.getByRole('button', { name: /example select/i });
    await user.click(trigger);

    const optionTwo = await screen.findByRole('option', { name: 'Two' });
    await user.click(optionTwo);

    expect(onValueChange).toHaveBeenLastCalledWith('two');

    await user.click(trigger);
    await user.keyboard('{ArrowDown}{Enter}');
    expect(onValueChange).toHaveBeenLastCalledWith('three');
  });

  it('switches tabs via keyboard interaction', async () => {
    const user = userEvent.setup();

    render(
      <Tabs defaultValue="details">
        <TabsList aria-label="Radix tabs example">
          <TabsTrigger value="details">Details</TabsTrigger>
          <TabsTrigger value="settings">Settings</TabsTrigger>
        </TabsList>
        <TabsContent value="details">Details content</TabsContent>
        <TabsContent value="settings">Settings content</TabsContent>
      </Tabs>
    );

    screen.getByRole('tablist', { name: /radix tabs example/i });
    const [detailsTab, settingsTab] = screen.getAllByRole('tab');

    expect(detailsTab).toHaveAttribute('data-state', 'active');
    expect(screen.getByText('Details content')).toBeVisible();
    expect(screen.queryByText('Settings content')).not.toBeInTheDocument();

    await user.tab();
    await user.keyboard('{ArrowRight}{Enter}');

    expect(settingsTab).toHaveAttribute('data-state', 'active');
    expect(screen.getByText('Settings content')).toBeVisible();
  });

  it('toggles switch state and emits events', async () => {
    const handleChange = jest.fn();
    const user = userEvent.setup();

    render(
      <form>
        <SwitchPrimitive.Root aria-label="demo switch" onCheckedChange={handleChange}>
          <SwitchPrimitive.Thumb />
        </SwitchPrimitive.Root>
      </form>
    );

    const switchControl = screen.getByRole('switch');
    expect(switchControl).toHaveAttribute('aria-checked', 'false');

    await user.click(switchControl);
    expect(handleChange).toHaveBeenLastCalledWith(true);

    await user.keyboard('{Space}');
    expect(handleChange).toHaveBeenLastCalledWith(false);
  });

  it('renders and dismisses toast notifications', async () => {
    jest.useFakeTimers();

    try {
      renderWithToastProvider(
        <ToastPrimitive.Root open duration={100}>
          <ToastPrimitive.Title>Toast title</ToastPrimitive.Title>
          <ToastPrimitive.Description>Toast description</ToastPrimitive.Description>
        </ToastPrimitive.Root>
      );

      expect(screen.getByText('Toast title')).toBeVisible();
      expect(screen.getByText('Toast description')).toBeVisible();

      jest.advanceTimersByTime(150);

      expect(screen.queryByText('Toast title')).not.toBeInTheDocument();
    } finally {
      jest.useRealTimers();
    }
  });
});
