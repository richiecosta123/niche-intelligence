import { readFileSync } from 'fs';
import { fileURLToPath } from 'url';
import path from 'path';

const __dirname = path.dirname(fileURLToPath(import.meta.url));

const systemPrompt = readFileSync(
  path.join(__dirname, 'prompts/competitive-intelligence.md'),
  'utf-8'
);

export const competitiveIntelligenceTool = {
  name: 'competitive_intelligence' as const,
  description: 'Dissect competitors to find weaknesses and actionable gaps',
  inputSchema: {
    type: 'object' as const,
    properties: {
      nicheId: { type: 'number', description: 'ID of the niche to analyse competitors for' },
    },
    required: ['nicheId'],
  },
  async handler({ nicheId }: { nicheId: number }) {
    return {
      status: 'ready_to_analyse',
      nicheId,
      systemPrompt,
      instruction:
        'Query query_insights (competitor_gap), query_success_stories, and query_personas for this niche. ' +
        'Identify all named competitors, analyse each using the rubric, then save one record per competitor via save_competitor_analysis.',
      saveSchema: {
        tool: 'save_competitor_analysis',
        columns: {
          niche_id:               'number',
          competitor_name:        'string — company or brand name (required)',
          positioning:            'string — how they position themselves and their core message',
          strengths:              'string[] — genuine advantages that are hard to compete with',
          weaknesses:             'string[] — pain points customers raise, ignored segments, vulnerabilities',
          gaps_and_opportunities: 'string[] — unclaimed segments, missing features, open messaging angles',
          market_share_estimate:  'string — estimated share, e.g. "~35% of organic search traffic"',
          strategy:               'string — go-to-market and growth strategy summary',
        },
        required: ['niche_id', 'competitor_name'],
      },
    };
  },
};
