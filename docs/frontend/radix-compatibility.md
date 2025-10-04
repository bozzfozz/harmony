# Radix UI Compatibility Matrix

| Package | Version Range |
| --- | --- |
| @radix-ui/react-label | ^2.1.7 |
| @radix-ui/react-progress | ^1.1.0 |
| @radix-ui/react-scroll-area | ^1.2.0 |
| @radix-ui/react-select | ^2.2.4 |
| @radix-ui/react-slot | ^1.2.2 |
| @radix-ui/react-switch | ^1.2.0 |
| @radix-ui/react-tabs | ^1.1.0 |
| @radix-ui/react-tooltip | ^1.2.6 |
| tslib (transitive runtime helper) | ^2.8.1 |

## Runtime Compatibility

- React: ^18.2.0
- TypeScript: ^5.4.2
- Vite: ^5.1.5
- ESLint: ^8.57.0

## Verification Steps

```bash
npm -C frontend ci
npm -C frontend run lint
npm -C frontend run build
npm -C frontend run preview -- --host 0.0.0.0 --port 4173
```

Ensure the downloads page and activity feed render with interactive Radix components (Select, Tabs, Tooltip, Switch) without runtime errors.
