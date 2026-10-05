// @ts-check
// The guide site lives at the root of GitHub Pages; the MkDocs site (guides for contributors + generated API
// reference) is built into <root>/reference/ by `just docs-all`.

// The MkDocs reference is a separate origin during development (`just docs-serve` serves it on port 8000) and a
// same-origin path on GitHub Pages — rewrite links accordingly so both work.
const isDev = process.env.NODE_ENV === "development";
const REFERENCE_PATH = "/spec-agents/reference/";
const referenceHref = isDev
  ? `http://127.0.0.1:8000${REFERENCE_PATH}`
  : `https://marcionicolau.github.io${REFERENCE_PATH}`;

/** @typedef {{ type: string, url?: string, children?: MdastNode[] }} MdastNode */

/** Dev-only remark plugin: `pathname:///spec-agents/reference/…` links go to the local MkDocs server. */
const rewriteReferenceLinks = () => {
  /** @param {MdastNode} node */
  const walk = (node) => {
    if (
      node.type === "link" &&
      typeof node.url === "string" &&
      node.url.startsWith(`pathname://${REFERENCE_PATH}`)
    ) {
      node.url = node.url.replace(
        `pathname://${REFERENCE_PATH}`,
        referenceHref,
      );
    }
    for (const child of node.children ?? []) walk(child);
  };
  /** @param {MdastNode} tree */
  return (tree) => walk(tree);
};

/** @type {import('@docusaurus/types').Config} */
const config = {
  title: "spec-agents",
  tagline:
    "Spec-driven pipelines and hierarchical agents; LLMs plan, code computes.",
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
          editUrl:
            "https://github.com/marcionicolau/spec-agents/edit/main/website/",
          beforeDefaultRemarkPlugins: isDev ? [rewriteReferenceLinks] : [],
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
          {
            type: "docSidebar",
            sidebarId: "guide",
            position: "left",
            label: "Guide",
          },
          // built by MkDocs into the same Pages artifact; not a Docusaurus route, so a full URL (the link checker ignores external links)
          {
            href: referenceHref,
            label: "API reference & contributing",
            position: "left",
            target: "_self",
          },
          {
            href: "https://github.com/marcionicolau/spec-agents",
            label: "GitHub",
            position: "right",
          },
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
