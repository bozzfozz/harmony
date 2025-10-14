# UI Content Security Policy

## Baseline Policy
```
default-src 'self';
script-src 'self';
style-src 'self' 'unsafe-inline';
img-src 'self' data:;
connect-src 'self';
font-src 'self';
frame-ancestors 'none';
```
- Apply the policy at the FastAPI middleware or upstream proxy.
- Inline styles are limited to the CSS needed for focus rings; consider replacing them with classes before tightening the policy.

## Optional CDN Support
- Set `UI_ALLOW_CDN=true` to permit HTMX from the official CDN.
- Extend the CSP `script-src` directive to include `https://unpkg.com/htmx.org` and provide an SRI hash.

Example header snippet:
```
script-src 'self' https://unpkg.com/htmx.org;
```
Example `<script>` tag:
```html
<script src="https://unpkg.com/htmx.org@1.9.10" integrity="sha384-EXAMPLEHASH" crossorigin="anonymous"></script>
```
- Replace `EXAMPLEHASH` with the published SHA384 checksum for the exact HTMX version used.
- When CDN mode is enabled you must continue to ship a local fallback (e.g. `<script data-fallback src="/static/js/htmx.min.js"></script>`).

## Troubleshooting
- **Blocked script**: Verify that `UI_ALLOW_CDN` is set and that the CSP contains the CDN origin and matching SRI hash.
- **Inline script violations**: Avoid inline JavaScript; register HTMX configuration via a bundled module under `/static/js/ui-bootstrap.js`.
- **Third-party assets**: Additional origins (fonts, analytics) require explicit approval. Update this document before enabling them.
- **Local development**: Use the same CSP headers to catch violations early; adjust only via environment variables rather than editing templates.
