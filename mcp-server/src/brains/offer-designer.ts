import { readFileSync } from 'fs';
import { fileURLToPath } from 'url';
import path from 'path';

const __dirname = path.dirname(fileURLToPath(import.meta.url));

const systemPrompt = readFileSync(
  path.join(__dirname, 'prompts/offer-designer.md'),
  'utf-8'
);

export const offerDesignerTool = {
  name: 'offer_designer' as const,
  description: 'Design 2-3 positioned offers per niche anchored to customer pain points and market gaps',
  inputSchema: {
    type: 'object' as const,
    properties: {
      nicheId: { type: 'number', description: 'ID of the niche to design offers for' },
    },
    required: ['nicheId'],
  },
  async handler({ nicheId }: { nicheId: number }) {
    return {
      status: 'ready_to_design',
      nicheId,
      systemPrompt,
      instruction:
        'Query query_personas, query_insights, and query_success_stories for this niche. ' +
        'Design 2-3 distinct offers targeting the biggest pain points and market gaps. ' +
        'Save each via save_offer.',
      saveSchema: {
        tool: 'save_offer',
        columns: {
          niche_id:        'number',
          offer_name:      'string — specific, clear name for the offer',
          competitor_name: 'string — optional competitor this undercuts or improves on',
          offer_type:      'string — service | product | saas | marketplace',
          price_point:     'number — suggested price in USD',
          pricing_model:   'string — one_time | monthly | annual | usage | tiered',
          core_promise:    'string — the #1 transformation delivered',
          unique_mechanism: 'string — what makes this different / defensible',
          bonuses:         'object[] — optional add-ons that increase perceived value',
          guarantees:      'object[] — risk-reversals, e.g. 30-day money-back',
          testimonials_summary: 'object — summary of social proof to source',
          conversion_elements: 'object[] — urgency, scarcity, social proof tactics',
          weaknesses:      'string[] — known risks or limitations',
          strengths:       'string[] — competitive advantages',
          source_url:      'string — optional reference or inspiration URL',
        },
        required: ['niche_id', 'offer_name', 'core_promise', 'unique_mechanism'],
      },
    };
  },
};
