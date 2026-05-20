import { readFileSync } from 'fs';
import { fileURLToPath } from 'url';
import path from 'path';

const __dirname = path.dirname(fileURLToPath(import.meta.url));

const systemPrompt = readFileSync(
  path.join(__dirname, 'prompts/market-strategist.md'),
  'utf-8'
);

export const marketStrategistTool = {
  name: 'market_strategist' as const,
  description: 'Generate 20-page disruption reports synthesizing all accumulated intelligence',
  inputSchema: {
    type: 'object' as const,
    properties: {
      nicheId:      { type: 'number', description: 'ID of the niche to analyse' },
      reportPeriod: { type: 'string', description: 'e.g. "Q2_2026_Week_1"' },
    },
    required: ['nicheId'],
  },
  async handler({ nicheId, reportPeriod }: { nicheId: number; reportPeriod?: string }) {
    const period = reportPeriod ?? `Q2_2026_Week_${Math.ceil(Date.now() / (7 * 24 * 60 * 60 * 1000))}`;
    return {
      status: 'ready_to_generate',
      nicheId,
      reportPeriod: period,
      systemPrompt,
      instruction:
        'Query query_insights, query_personas, query_success_stories for this niche, ' +
        'synthesise all data into a 20-page disruption report, then call generate_disruption_report.',
      saveSchema: {
        tool: 'generate_disruption_report',
        columns: {
          niche_id:                   'number',
          report_title:               'string — descriptive title for the report',
          report_period:              'string — period identifier, e.g. "Q2_2026_Week_1"',
          disruption_signals:         'object[] — signals of market disruption with evidence',
          emerging_technologies:      'object[] — relevant tech shifts and implications',
          regulatory_changes:         'object[] — regulatory factors affecting the niche',
          consumer_behavior_shifts:   'object[] — documented shifts in buyer behaviour',
          competitive_moves:          'object[] — notable competitor actions',
          threat_level:               'string — low | medium | high | critical',
          opportunity_level:          'string — low | medium | high | exceptional',
          recommended_actions:        'object[] — prioritised next steps with owners',
          executive_summary:          'string — 2-page plain-text summary',
        },
        required: ['niche_id', 'report_title'],
      },
    };
  },
};
