// @ts-check
import starlight from '@astrojs/starlight';
import {defineConfig} from 'astro/config';
import starlightPydocs, {pydocsSidebarGroup} from 'starlight-pydocs';
import flexoki from 'starlight-theme-flexoki';

const repository = 'messier-42/pyrophone';

export default defineConfig({
  site: 'https://pyrophone.dev',
  publicDir: '../logo',
  trailingSlash: 'always',
  integrations: [
    starlight({
      title: 'Pyrophone',
      description: 'A Python DSL for message processing.',
      expressiveCode: {defaultProps: {wrap: true}},
      logo: {src: '../logo/pyrophone-logo.svg', replacesTitle: true},
      favicon: '/pyrophone-logo.svg',
      social: [{icon: 'github', label: 'GitHub', href: `https://github.com/${repository}`}],
      editLink: {baseUrl: `https://github.com/${repository}/edit/master/doc/site/`},
      plugins: [
        flexoki(),
        starlightPydocs({
          pythonInventory: false,
          runner: {command: ['uvx', '--python', '3.12', '--from', 'griffe==2.4.1', 'griffe']},
          packages: [{
            name: 'pyrophone',
            search: ['../../src'],
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
          label: 'Examples',
          items: [
            {autogenerate: {directory: 'examples'}},
          ],
        },
        {label: 'Python API', items: [pydocsSidebarGroup]},
      ],
    }),
  ],
});
