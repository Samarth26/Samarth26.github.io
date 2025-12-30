# Portfolio Site

Static portfolio website built with HTML, CSS, and vanilla JS.

## Quick start

1. Open `index.html` in a browser to preview locally.
2. Customize text, links, and project details directly in `index.html`.
3. Adjust colors or layout in `styles/main.css`.

## Deploy to GitHub Pages

1. Create a GitHub repository (for example `portfolio`).
2. Push this folder to the repository root (where `index.html` sits at the top level).
3. In GitHub, go to **Settings → Pages**.
4. Under **Source**, choose **Deploy from a branch** and pick `main` (or `master`) with the root folder (`/`).
5. Save. Pages will build and give you a URL like `https://<username>.github.io/portfolio/`.

### Custom domain (optional)

1. In **Settings → Pages**, add your domain (e.g., `www.example.com`).
2. Create DNS records: `CNAME` pointing `www` to `<username>.github.io` and `A` records to GitHub IPs if you need apex support.
3. Wait for DNS to propagate, then enable HTTPS.

## Customize further

- Swap palette by editing CSS variables in `styles/main.css`.
- Add more projects or sections by duplicating existing cards/blocks in `index.html`.
- If you prefer a framework or build tooling, we can layer in Vite/React or a static site generator later.
