# Radix UI Compatibility Matrix

| Package | Version Range |
| --- | --- |
| @radix-ui/react-dismissable-layer | 1.1.11 |
| @radix-ui/react-label | ^2.1.7 |
| @radix-ui/react-progress | ^1.1.7 |
| @radix-ui/react-scroll-area | ^1.2.10 |
| @radix-ui/react-select | ^2.2.5 |
| @radix-ui/react-slot | ^1.2.3 |
| @radix-ui/react-switch | ^1.2.6 |
| @radix-ui/react-tabs | ^1.1.13 |
| @radix-ui/react-toast | 1.2.15 |
| @radix-ui/react-tooltip | ^1.2.7 |
| tslib (transitive runtime helper) | ^2.8.1 |

## Runtime Compatibility

- React: ^18.2.0
- TypeScript: ^5.9.2
- Vite: ^5.4.20
- ESLint: ^8.57.1

## Verification Steps

```bash
npm -C frontend ci --no-audit --no-fund
npm -C frontend run lint
npm -C frontend test -- --runInBand
npm -C frontend run build
npm -C frontend run preview -- --host 0.0.0.0 --port 4173
```

Ensure the downloads page and activity feed render with interactive Radix components (Select, Tabs, Tooltip, Switch) without runtime errors.
