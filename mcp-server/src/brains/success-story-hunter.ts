import { readFileSync } from 'fs';
import { fileURLToPath } from 'url';
import path from 'path';

const __dirname = path.dirname(fileURLToPath(import.meta.url));

const systemPrompt = readFileSync(
  path.join(__dirname, 'prompts/success-story-hunter.md'),
  'utf-8'
);

export const successStoryHunterTool = {
  name: 'success_story_hunter' as const,
  description: 'Find money-making stories with revenue proof',
  inputSchema: {
    type: 'object' as const,
    properties: {
      nicheId: { type: 'number', description: 'ID of the niche to scan for success stories' },
    },
    required: ['nicheId'],
  },
  async handler({ nicheId }: { nicheId: number }) {
    return {
      status: 'ready_to_hunt',
      nicheId,
      systemPrompt,
      instruction:
        'Query raw_source_data for this niche, score each post using the credibility rubric, ' +
        'then save qualifying stories (credibilityScore >= 0.5) via save_success_story.',
      saveSchema: {
        tool: 'save_success_story',
        columns: {
          niche_id:            'number',
          '"storyTitle"':      'string — compelling headline summarising the story',
          summary:             'string — one-sentence brief',
          revenue:             'object — { amount: number, timeframe: string, proof_type: string }',
          method:              'string — exactly what they did to earn money',
          platform:            'string — optional (e.g. "reddit", "turo")',
          '"credibilityScore"':'number 0.0–1.0 per rubric',
          '"proofLinks"':      'string[] — URLs to screenshots, dashboards, invoices',
          '"sourceUrl"':       'string — URL of the original post',
          '"sourceType"':      'string — reddit | youtube | blog | forum | other',
        },
        required: ['niche_id', '"storyTitle"', 'summary', 'method', '"credibilityScore"', '"sourceUrl"'],
      },
    };
  },
};
