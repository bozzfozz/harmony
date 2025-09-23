import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import DarkModeToggle from "../DarkModeToggle";

describe("DarkModeToggle", () => {
  beforeEach(() => {
    document.documentElement.classList.remove("dark");
    document.documentElement.style.removeProperty("color-scheme");
    window.localStorage.clear();
  });

  it("renders the toggle button with light mode active by default", () => {
    render(<DarkModeToggle />);

    const button = screen.getByRole("button", { name: /light mode aktiv/i });
    expect(button).toBeInTheDocument();
    expect(button).toHaveAttribute("aria-pressed", "false");
    expect(document.documentElement.classList.contains("dark")).toBe(false);
    expect(document.documentElement.style.getPropertyValue("color-scheme")).toBe("light");
  });

  it("toggles the theme and persists the choice", async () => {
    const user = userEvent.setup();
    render(<DarkModeToggle />);

    const button = screen.getByRole("button", { name: /light mode aktiv/i });
    await user.click(button);

    expect(document.documentElement.classList.contains("dark")).toBe(true);
    expect(document.documentElement.style.getPropertyValue("color-scheme")).toBe("dark");
    expect(window.localStorage.getItem("theme")).toBe("dark");
    expect(button).toHaveAttribute("aria-pressed", "true");
    expect(button).toHaveAttribute("aria-label", "Dark Mode aktiv");
  });

  it("initialises with a stored dark theme", () => {
    window.localStorage.setItem("theme", "dark");
    render(<DarkModeToggle />);

    const button = screen.getByRole("button", { name: /dark mode aktiv/i });
    expect(document.documentElement.classList.contains("dark")).toBe(true);
    expect(document.documentElement.style.getPropertyValue("color-scheme")).toBe("dark");
    expect(button).toHaveAttribute("aria-pressed", "true");
  });
});
