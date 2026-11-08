# Bundled Drop source

Copied from the owner's existing Zentr Drop project:
- `cli/drop.mjs`
- `src/frontend/crypto.js`

Bundled on November 1, 2026. Adaptations: the crypto import is relative to the
bundled `crypto.mjs`, and help examples use `zentr drop`. Encryption, upload,
download, status, and shortening behavior are preserved. Node.js 20.11+ is required.
The original Drop README's warning about sending fragments to the shortener is
outdated: the current implementation strips the fragment and reattaches it locally.
