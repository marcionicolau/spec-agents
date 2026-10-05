// @ts-check

/** @type {import('@docusaurus/plugin-content-docs').SidebarsConfig} */
const sidebars = {
  guide: [
    "intro",
    "installation",
    "quickstart",
    {
      type: "category",
      label: "Domain packs",
      link: { type: "doc", id: "packs/index" },
      items: ["packs/text", "packs/statistics", "packs/lakehouse", "packs/coworker"],
    },
    {
      type: "category",
      label: "How-to",
      items: ["how-to/handle-errors", "how-to/real-model"],
    },
  ],
};

export default sidebars;
