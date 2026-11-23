// @ts-check
import {satteri} from '@astrojs/markdown-satteri';
import starlight from '@astrojs/starlight';
import {defineConfig} from 'astro/config';
import codeblocks from 'starlight-codeblocks';
import starlightPydocs, {pydocsSidebarGroup} from 'starlight-pydocs';
import flexoki from 'starlight-theme-flexoki';
import {mermaidMarkdown} from './src/lib/mermaid.ts';

const repository = 'messier-42/pyrophone';
const site = 'https://pyrophone.dev';
const socialImage = new URL('/pyrophone-social.png', site).href;
const socialImageAlt = 'Pyrophone logo';

export default defineConfig({
  site,
  publicDir: '../logo',
  trailingSlash: 'always',
  markdown: {processor: satteri({mdastPlugins: [mermaidMarkdown]})},
  integrations: [
    starlight({
      title: 'Pyrophone',
      description: 'A Python DSL for message processing.',
      customCss: ['./src/styles/mermaid.css'],
      expressiveCode: {defaultProps: {wrap: true}},
      logo: {
        light: '../logo/pyrophone-logo.svg',
        dark: '../logo/pyrophone-logo-dark.svg',
        replacesTitle: true,
      },
      favicon: '/pyrophone-mark.svg',
      head: [
        {tag: 'meta', attrs: {property: 'og:image', content: socialImage}},
        {tag: 'meta', attrs: {property: 'og:image:type', content: 'image/png'}},
        {tag: 'meta', attrs: {property: 'og:image:width', content: '1200'}},
        {tag: 'meta', attrs: {property: 'og:image:height', content: '630'}},
        {tag: 'meta', attrs: {property: 'og:image:alt', content: socialImageAlt}},
        {tag: 'meta', attrs: {name: 'twitter:image', content: socialImage}},
        {tag: 'meta', attrs: {name: 'twitter:image:alt', content: socialImageAlt}},
      ],
      social: [{icon: 'github', label: 'GitHub', href: `https://github.com/${repository}`}],
      editLink: {baseUrl: `https://github.com/${repository}/edit/master/doc/site/`},
      plugins: [
        flexoki(),
        codeblocks(),
        starlightPydocs({
          pythonInventory: false,
          components: {ModuleDoc: './src/components/ApiModuleDoc.astro'},
          runner: {command: ['uvx', '--python', '3.12', '--from', 'griffe==2.4.1', 'griffe']},
          packages: [{
            name: 'pyrophone',
            search: ['../../src'],
            members: {exclude: ['pyrophone.script.*']},
            sourceLink: {
              host: 'github',
              repo: repository,
              ref: process.env.GITHUB_SHA ?? 'master',
              root: '../..',
            },
          }],
        }),
      ],
      sidebar: [
        {
          label: 'Narrative Overview',
          items: [
            {
              label: 'Introduction',
              link: '/',
            },
            {autogenerate: {directory: 'overview'}},
          ],
        },
        {
          label: 'Predefined Node Types',
          items: [
            {autogenerate: {directory: 'nodes'}},
          ],
        },
        {
          label: 'Examples',
          items: [
            {label: 'Quickstart Example', link: '/examples/quickstart/'},
            {autogenerate: {directory: 'examples'}},
          ],
        },
        {label: 'Python API', items: [pydocsSidebarGroup]},
      ],
    }),
  ],
});
