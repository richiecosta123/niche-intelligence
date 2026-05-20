import { readFileSync } from 'fs';
import { fileURLToPath } from 'url';
import path from 'path';

const __dirname = path.dirname(fileURLToPath(import.meta.url));

const systemPrompt = readFileSync(
  path.join(__dirname, 'prompts/persona-architect.md'),
  'utf-8'
);

export const personaArchitectTool = {
  name: 'persona_architect' as const,
  description: 'Build psychologically rich customer personas from raw community data',
  inputSchema: {
    type: 'object' as const,
    properties: {
      nicheId: { type: 'number', description: 'ID of the niche to generate personas for' },
    },
    required: ['nicheId'],
  },
  async handler({ nicheId }: { nicheId: number }) {
    return {
      status: 'ready_to_build',
      nicheId,
      systemPrompt,
      instruction:
        'Audit raw_source_data, call expand_research to fill gaps, execute web searches, ' +
        'then save 3–5 distinct personas via save_persona.',
      saveSchema: {
        tool: 'save_persona',
        columns: {
          niche_id:           'number',
          name:               'string — memorable archetype label, e.g. "The Vegas Splurger"',
          avatar_type:        'string — segment label, e.g. "high-roller"',
          age_range:          'string — e.g. "28-42"',
          income_range:       'string — e.g. "$150k-$500k"',
          psychographics:     'object — values, lifestyle, personality traits',
          pain_points:        'string[] — real hesitations from source data',
          desires:            'string[] — motivations and aspirations',
          objections:         'string[] — buying hesitations with source language',
          empathy_map:        'object — { thinks, feels, sees, hears, says, does }',
          buying_triggers:    'string[] — specific moments that push them to buy',
          preferred_channels: 'string[] — where they consume content and decide',
          is_primary:         'boolean — true for highest-volume / highest-revenue segment',
        },
        required: ['niche_id', 'name'],
      },
    };
  },
};
