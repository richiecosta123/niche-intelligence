import { readFileSync } from 'fs';
import { fileURLToPath } from 'url';
import path from 'path';

const __dirname = path.dirname(fileURLToPath(import.meta.url));

const systemPrompt = readFileSync(
  path.join(__dirname, 'prompts/financial-analyst.md'),
  'utf-8'
);

export const financialAnalystTool = {
  name: 'financial_analyst' as const,
  description: 'Calculate TAM, CAC, LTV and unit economics to validate market opportunities',
  inputSchema: {
    type: 'object' as const,
    properties: {
      nicheId: { type: 'number', description: 'ID of the niche to analyse' },
    },
    required: ['nicheId'],
  },
  async handler({ nicheId }: { nicheId: number }) {
    return {
      status: 'ready_to_analyse',
      nicheId,
      systemPrompt,
      instruction:
        'Query query_insights, query_success_stories, and any available trend data for this niche. ' +
        'Calculate TAM, CAC, LTV, payback period, and unit economics showing all assumptions. ' +
        'Save results via save_financial_analysis.',
      saveSchema: {
        tool: 'save_financial_analysis',
        columns: {
          niche_id:       'number',
          tam_estimate:   'string — TAM with full methodology (required)',
          average_cac:    'string — CAC with data source citations',
          average_ltv:    'string — LTV calculation with retention assumptions',
          ltv_cac_ratio:  'string — ratio, e.g. "4.2:1" (healthy = 3:1+)',
          payback_period: 'string — months to recover CAC, e.g. "8 months"',
          churn_rate:     'string — annualised churn %, e.g. "18%"',
          unit_economics: 'object — { revenue_per_customer, cost_to_serve, gross_margin, contribution_margin }',
        },
        required: ['niche_id', 'tam_estimate'],
      },
    };
  },
};
