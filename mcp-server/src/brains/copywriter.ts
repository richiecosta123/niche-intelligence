import { readFileSync } from 'fs';
import { fileURLToPath } from 'url';
import path from 'path';

const __dirname = path.dirname(fileURLToPath(import.meta.url));

const systemPrompt = readFileSync(
  path.join(__dirname, 'prompts/copywriter.md'),
  'utf-8'
);

export const copywriterTool = {
  name: 'copywriter' as const,
  description: 'Build a 100+ copy asset library from authentic customer language',
  inputSchema: {
    type: 'object' as const,
    properties: {
      nicheId: { type: 'number', description: 'ID of the niche to generate copy for' },
    },
    required: ['nicheId'],
  },
  async handler({ nicheId }: { nicheId: number }) {
    return {
      status: 'ready_to_write',
      nicheId,
      systemPrompt,
      instruction:
        'Query query_insights (language_pattern), query_personas, and query_success_stories for this niche. ' +
        'Extract authentic customer language and generate 100+ copy assets. ' +
        'Save each via save_marketing_copy.',
      saveSchema: {
        tool: 'save_marketing_copy',
        columns: {
          niche_id:          'number',
          copy_type:         'string — headline | hook | cta | email_subject | body_copy',
          copy_angle:        'string — emotional angle, e.g. "fear_of_missing_out"',
          content:           'string — the actual copy text',
          target_avatar_id:  'number — optional FK to customer_avatars.id',
          performance_data:  'object — optional { impressions, clicks, ctr }',
          ai_generated:      'boolean — true (default)',
          approved:          'boolean — false until human reviewed (default)',
          tags:              'string[] — keyword tags for filtering',
        },
        required: ['niche_id', 'copy_type', 'content'],
      },
    };
  },
};
