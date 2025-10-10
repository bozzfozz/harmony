# Porttracker Frontend Reference (Archived)

The Porttracker UI archive that once lived in the repository has now been removed. This page preserves the historical notes so Harmony contributors still know how to reuse ideas from that codebase when planning new UI work.

## Purpose
- Provide a catalogue of reusable UI patterns, components, and hooks from the Porttracker project.
- Serve purely as design and implementation inspiration for Harmony's frontend. The code was not shipped to production.

## Historical Structure
- `components/` – Reusable React components grouped into `common`, `modals`, `server`, and `ui` directories.
- `layouts/` – Dashboard shell, header, sidebar, and other layout primitives.
- `pages/` – High-level page components (primarily the dashboard experience).
- `hooks/` – Custom React hooks extracted from the template.
- `utils/` – Helper utilities, constants, feature data, and API wrappers.
- `styles/` – Global styling assets, CSS files, and shared style tokens.
- `tests/` – Placeholder UI test scaffolding carried over for completeness.

## Notes for Future Work
- When borrowing code snippets, double-check imports and update any `@` alias usage to match Harmony's current frontend tooling.
- Treat the historical code as read-only inspiration; new Harmony UI should follow the documented design system and coding standards rather than reintroducing the archive verbatim.
