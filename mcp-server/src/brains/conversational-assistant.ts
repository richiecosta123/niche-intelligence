import { readFileSync } from 'fs';
import { fileURLToPath } from 'url';
import path from 'path';

const __dirname = path.dirname(fileURLToPath(import.meta.url));

const systemPrompt = readFileSync(
  path.join(__dirname, 'prompts/conversational-assistant.md'),
  'utf-8'
);

export const conversationalAssistantTool = {
  name: 'conversational_assistant' as const,
  description: 'Synthesise intelligence across all 8 brains to answer user queries',
  inputSchema: {
    type: 'object' as const,
    properties: {
      nicheId:   { type: 'number', description: 'ID of the niche to query' },
      queryType: {
        type: 'string',
        description:
          'What the user wants: pain_points | personas | opportunities | offers | ' +
          'financials | competitors | copy | comprehensive',
      },
    },
    required: ['nicheId', 'queryType'],
  },
  async handler({ nicheId, queryType }: { nicheId: number; queryType: string }) {
    return {
      status: 'ready_to_synthesise',
      nicheId,
      queryType,
      systemPrompt,
      instruction:
        'Call query_all_intelligence first to get data counts, then use targeted query tools ' +
        '(query_insights, query_personas, query_success_stories, etc.) to fetch relevant data. ' +
        'Synthesise findings and respond with cited, actionable answers.',
      queryTools: {
        pain_points:    ['query_insights (category: pain_point)'],
        personas:       ['query_personas'],
        opportunities:  ['query_insights (category: competitor_gap, market_timing)', 'query_success_stories'],
        offers:         ['query_insights', 'query_personas', 'query_success_stories'],
        financials:     ['query_insights', 'query_success_stories'],
        competitors:    ['query_insights (category: competitor_gap)'],
        copy:           ['query_insights (category: language_pattern)', 'query_personas'],
        comprehensive:  ['query_all_intelligence', 'query_insights', 'query_personas', 'query_success_stories'],
      },
    };
  },
};
