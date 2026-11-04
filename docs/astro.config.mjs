// @ts-check
import { defineConfig } from 'astro/config';
import starlight from '@astrojs/starlight';
import starlightLlmsTxt from 'starlight-llms-txt';

const repo = 'https://github.com/sharanmahadevan/cv-cue-mcp';

export default defineConfig({
  site: 'https://sharanmahadevan.github.io',
  base: '/cv-cue-mcp',
  integrations: [
    starlight({
      title: 'CV-CUE MCP',
      description:
        'An MCP server that connects Claude to Arista CV-CUE Wi-Fi: 30 curated tools plus the full CV-CUE REST API, hosted or self-hosted.',
      social: [{ icon: 'github', label: 'GitHub', href: repo }],
      editLink: { baseUrl: `${repo}/edit/main/docs/` },
      lastUpdated: true,
      customCss: ['./src/styles/custom.css'],
      plugins: [
        starlightLlmsTxt({
          projectName: 'CV-CUE MCP',
          description:
            'MCP server for Arista CV-CUE: sign in, save an encrypted CV-CUE API key, and connect Claude with one URL. Also supports bring-your-own-key and self-hosting.',
        }),
      ],
      sidebar: [
        { label: 'What is CV-CUE MCP?', link: '/' },
        {
          label: 'Set up',
          items: [
            { label: 'Getting started', slug: 'setup/getting-started' },
            { label: 'Connecting clients', slug: 'setup/connecting' },
          ],
        },
        {
          label: 'How it works',
          items: [
            { label: 'Curated tools and API discovery', slug: 'how-it-works/api-discovery' },
            { label: 'Security model', slug: 'how-it-works/security' },
          ],
        },
        {
          label: 'Reference',
          items: [
            { label: 'Tools', slug: 'reference/tools' },
            { label: 'Headers and configuration', slug: 'reference/configuration' },
            { label: 'Limits', slug: 'reference/limits' },
            { label: 'CV-CUE API notes', slug: 'reference/api-notes' },
          ],
        },
        {
          label: 'Guides',
          items: [
            { label: 'Self-host on Fly.io', slug: 'guides/fly' },
            { label: 'Run it locally', slug: 'guides/local' },
            { label: 'Enabling writes', slug: 'guides/writes' },
          ],
        },
        { label: 'Examples', slug: 'examples' },
        { label: 'Troubleshooting', slug: 'troubleshooting' },
        { label: "What's new", slug: 'changelog' },
      ],
    }),
  ],
});
