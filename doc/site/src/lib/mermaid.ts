import {createHash} from 'node:crypto';
import type {SatteriProcessorOptions} from '@astrojs/markdown-satteri';
import {createNodeEngine} from '@mermanjs/node';

export async function renderMermaidSvg(source: string, id: string): Promise<string> {
  const engine = await createNodeEngine();
  try {
    return await engine.renderSvg(source.trim(), {
      optionsJson: JSON.stringify({
        version: 3,
        site_config: {
          theme: 'base',
          htmlLabels: false,
          themeVariables: {
            fontFamily: 'system-ui, sans-serif',
            primaryColor: '#f2f0e5',
            primaryTextColor: '#100f0f',
            primaryBorderColor: '#878580',
            lineColor: '#575653',
            edgeLabelBackground: '#fffcf0',
          },
        },
        svg: {
          diagram_id: id,
          root_background_color: '#fffcf0',
        },
      }),
    });
  } finally {
    await engine.dispose();
  }
}

export const mermaidMarkdown = {
  name: 'mermaid-diagrams',
  options: {position: true},
  async code(node, context) {
    if (node.lang !== 'mermaid') return;

    // Scope each SVG's styles and markers to its own diagram.
    const hash = createHash('sha256')
      .update(context.fileURL?.href ?? context.source)
      .update(String(node.position?.start.offset ?? 0))
      .digest('hex').slice(0, 16);
    const svg = await renderMermaidSvg(node.value, `mermaid-${hash}`);
    context.replaceNode(node, {
      type: 'html',
      value: `<figure class="mermaid-diagram">${svg}</figure>`,
    });
  },
} satisfies NonNullable<SatteriProcessorOptions['mdastPlugins']>[number];
