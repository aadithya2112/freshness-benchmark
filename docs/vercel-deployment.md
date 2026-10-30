# Vercel hosting

Production: https://freshness-benchmark.vercel.app

The public site is a static Astro build. Vercel's project root is the repository
root, so the build can read `results/mixed-v2/results.json` outside `web/`.
`vercel.json` installs the pinned npm dependencies, prepares the evidence assets,
builds Astro, and serves `web/dist`. The project uses Node 24.x.

The preparation step downloads the immutable 0.5.0 release files and checks each
against the committed SHA-256 inventory in `web/release/SHA256SUMS`. It extracts
the complete evidence bundle into temporary storage, prepares individual gzip
traces, retains exact launch source and dataset notices, and writes a checksum
inventory for the generated public downloads. Large vector caches stay on
GitHub Releases. No benchmark experiment or embedding preparation runs at build
time. The existing Python benchmark environment is not needed for deployment.

Local production-equivalent build:

```sh
npm ci --prefix web
node scripts/prepare-vercel.mjs
npm run build --prefix web
```

The `.vercelignore` file limits CLI uploads to the Astro source, the committed
results, the preparation script, and deployment configuration. Generated data,
dependency caches, benchmark artifacts, and local environment files are excluded.

After linking the correct Vercel project, inspect the account/project before
publishing. To test a production build before assigning its public domain:

```sh
vercel project inspect --non-interactive
vercel deploy --prod --skip-domain
vercel curl / --deployment <deployment-url>
vercel promote <deployment-url>
```

The project is connected to this repository for future Git-based deployments.
Use feature branches for previews and merge reviewed changes to main for
production. Keep measurement releases immutable when changing the website.
