import { researchAnalystBrain } from './brains/research-analyst.js';
import { successStoryHunterTool } from './brains/success-story-hunter.js';

const brains = {
  research_analyst: { execute: researchAnalystBrain.execute.bind(researchAnalystBrain) },
  success_story_hunter: { execute: successStoryHunterTool.handler },
};

const brainName = process.argv[2];
const nicheId = parseInt(process.argv[4]);

if (!brainName || !nicheId) {
  console.error('Usage: npx tsx src/run.ts <brain_name> --niche-id <id>');
  process.exit(1);
}

const brain = brains[brainName as keyof typeof brains];
if (!brain) {
  console.error(`Unknown brain: ${brainName}`);
  console.error(`Available: ${Object.keys(brains).join(', ')}`);
  process.exit(1);
}

brain.execute({ nicheId }).then(console.log);
