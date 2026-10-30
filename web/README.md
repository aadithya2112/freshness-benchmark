# Astro website

A statically rendered Astro site with a combined overview/results homepage, methodology,
datasets, reproduction instructions, and a page for each recorded trial.
It uses system fonts and plain JavaScript for the comparison controls.

Use Node 24+ and the committed lockfile:

```sh
npm ci --prefix web
npm run build --prefix web
```

The standalone build reads `results/mixed-v2/results.json`. To select another
exported experiment, set `FRESHNESS_RESULTS_FILE` to its absolute results path.
The complete preview/deployment build preserves the existing evidence directory:

```sh
.venv/bin/python scripts/build_website.py artifacts/publication-v2
python3 -m http.server 4173 --bind 127.0.0.1 --directory website/dist
```

`npm run dev --prefix web` serves layout changes quickly, but the full evidence
files are only present in the complete preview build above. Reference evidence
and release assets are immutable; a layout rebuild does not regenerate them.

Page content is rendered at build time. Only the small aggregate comparison
payload reaches the comparison script; individual trial pages work without
client-side JavaScript. Original hash-based comparison links redirect to the
new results route. The versioned 0.5.0 source download retains the original UI;
current Astro source lives on the repository's main branch.
