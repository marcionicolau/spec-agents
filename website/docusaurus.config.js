// @ts-check
// The guide site lives at the root of GitHub Pages; the MkDocs site (guides for contributors + generated API
// reference) is built into <root>/reference/ by `just docs-all`.

/** @type {import('@docusaurus/types').Config} */
const config = {
  title: "spec-agents",
  tagline: "Spec-driven pipelines and hierarchical agents; LLMs plan, code computes.",
  url: "https://marcionicolau.github.io",
  baseUrl: "/spec-agents/",
  organizationName: "marcionicolau",
  projectName: "spec-agents",
  onBrokenLinks: "throw",
  markdown: {
    hooks: { onBrokenMarkdownLinks: "throw" },
  },
  i18n: { defaultLocale: "en", locales: ["en"] },

  presets: [
    [
      "classic",
      /** @type {import('@docusaurus/preset-classic').Options} */
      ({
        docs: {
          routeBasePath: "/", // the docs are the site: no separate landing page
          sidebarPath: "./sidebars.js",
          editUrl: "https://github.com/marcionicolau/spec-agents/edit/main/website/",
        },
        blog: false,
        theme: { customCss: "./src/css/custom.css" },
      }),
    ],
  ],

  themeConfig:
    /** @type {import('@docusaurus/preset-classic').ThemeConfig} */
    ({
      navbar: {
        title: "spec-agents",
        items: [
          { type: "docSidebar", sidebarId: "guide", position: "left", label: "Guide" },
          // built by MkDocs into the same Pages artifact; not a Docusaurus route, so a full URL (the link checker ignores external links)
          { href: "https://marcionicolau.github.io/spec-agents/reference/", label: "API reference & contributing", position: "left", target: "_self" },
          { href: "https://github.com/marcionicolau/spec-agents", label: "GitHub", position: "right" },
        ],
      },
      footer: {
        style: "dark",
        copyright: "MIT licensed. Built with Docusaurus and MkDocs.",
      },
      prism: { additionalLanguages: ["bash", "yaml", "python"] },
    }),
};

export default config;
