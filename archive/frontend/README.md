# Porttracker Frontend Reference

This directory contains the archived Porttracker user interface that serves as a reference implementation for building the Harmony frontend.

## Purpose
- Provide a catalogue of reusable UI patterns, components, and hooks from the Porttracker project.
- Act as design and implementation inspiration only — this code is **not** used in production.

## Structure
- `components/` – Reusable React components grouped into `common`, `modals`, `server`, and `ui` subdirectories.
- `layouts/` – Layout building blocks such as the dashboard shell, header, and sidebar.
- `pages/` – High-level page components (currently the dashboard experience).
- `hooks/` – Custom React hooks extracted from the template.
- `utils/` – Helper utilities, constants, feature data, and API wrappers.
- `styles/` – Global styling assets including CSS files and shared style tokens.
- `tests/` – Placeholder for UI tests (copied here for completeness).

## Notes
- Keep all Porttracker UI assets inside this folder hierarchy.
- Adjust imports using the `@` alias when moving files inside the reference.
- Remember: this archive is **read-only inspiration** for Harmony — do not deploy it as-is.
