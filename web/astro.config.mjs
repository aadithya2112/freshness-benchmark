import { defineConfig } from "astro/config";
export default defineConfig({
  output: "static",
  site: process.env.SITE_URL || (process.env.VERCEL_PROJECT_PRODUCTION_URL ? `https://${process.env.VERCEL_PROJECT_PRODUCTION_URL}` : "https://freshness-benchmark-aadithya2112s-projects.vercel.app"),
  trailingSlash: "always",
});
