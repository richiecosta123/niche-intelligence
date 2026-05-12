// MCP Skill Template - Brain Pattern
// Use this as the base structure for all 9 brain skills

import Anthropic from "@anthropic-ai/sdk";
import { Client } from 'pg';

// ============================================
// CONFIGURATION
// ============================================

const NEON_DB_URL = process.env.NEON_DB_URL;
const ANTHROPIC_API_KEY = process.env.ANTHROPIC_API_KEY;

const anthropic = new Anthropic({ apiKey: ANTHROPIC_API_KEY });

// ============================================
// DATABASE HELPER
// ============================================

async function queryDatabase(sql: string, params: any[] = []) {
  const client = new Client({ connectionString: NEON_DB_URL });
  
  try {
    await client.connect();
    const result = await client.query(sql, params);
    return result.rows;
  } catch (error) {
    console.error('Database query error:', error);
    throw error;
  } finally {
    await client.end();
  }
}

// ============================================
// BRAIN SKILL TEMPLATE
// ============================================

export const brainSkillTemplate = {
  
  // Metadata
  name: 'brain_name', // e.g., 'research_analyst', 'persona_architect'
  description: 'What this brain does', // e.g., 'Extract insights from raw Reddit data'
  
  // System prompt (from brain-prompts.md)
  systemPrompt: `
    You are a [ROLE]. Your job is to [TASK].
    
    [DETAILED INSTRUCTIONS FROM BRAIN-PROMPTS.MD]
    
    OUTPUT FORMAT: JSON matching [TABLE_NAME] schema
  `,
  
  // Input parameters
  parameters: {
    nicheId: { type: 'number', required: true, description: 'ID of the niche to process' },
    // Add other params as needed per brain
  },
  
  // Main execution function
  async execute(params: { nicheId: number; [key: string]: any }) {
    
    console.log(`[${this.name}] Starting execution for nicheId=${params.nicheId}`);
    
    try {
      
      // STEP 1: Query database for input data
      const inputData = await this.fetchInputData(params);
      
      if (!inputData || inputData.length === 0) {
        console.log(`[${this.name}] No input data found`);
        return { status: 'skipped', reason: 'No input data available' };
      }
      
      // STEP 2: Format input for Claude API
      const formattedInput = this.formatInput(inputData);
      
      // STEP 3: Call Claude API with brain's system prompt
      console.log(`[${this.name}] Calling Claude API...`);
      const aiResponse = await anthropic.messages.create({
        model: 'claude-sonnet-4-20250514',
        max_tokens: 8000,
        system: this.systemPrompt,
        messages: [
          {
            role: 'user',
            content: formattedInput
          }
        ]
      });
      
      const rawOutput = aiResponse.content[0].type === 'text' 
        ? aiResponse.content[0].text 
        : '';
      
      // STEP 4: Parse and validate output
      console.log(`[${this.name}] Parsing output...`);
      const parsedOutput = this.parseOutput(rawOutput);
      
      if (!parsedOutput || parsedOutput.length === 0) {
        console.log(`[${this.name}] No valid output generated`);
        return { status: 'failed', reason: 'AI generated no valid output' };
      }
      
      // STEP 5: Save to database
      console.log(`[${this.name}] Saving ${parsedOutput.length} records to database...`);
      await this.saveToDatabase(params.nicheId, parsedOutput);
      
      // STEP 6: Return success summary
      return {
        status: 'success',
        recordsCreated: parsedOutput.length,
        summary: `Processed ${inputData.length} inputs, created ${parsedOutput.length} outputs`
      };
      
    } catch (error) {
      console.error(`[${this.name}] Execution error:`, error);
      return {
        status: 'error',
        error: error.message
      };
    }
  },
  
  // STEP 1 HELPER: Fetch input data from database
  async fetchInputData(params: any) {
    // OVERRIDE THIS IN EACH BRAIN
    // Example for Research Analyst:
    // const sql = `SELECT * FROM rawSourceData WHERE niche_id = $1 AND processed = false`;
    // return await queryDatabase(sql, [params.nicheId]);
    
    throw new Error('fetchInputData() must be overridden in brain implementation');
  },
  
  // STEP 2 HELPER: Format data for Claude
  formatInput(data: any[]): string {
    // OVERRIDE THIS IN EACH BRAIN
    // Example:
    // return `Analyze these ${data.length} Reddit posts:\n\n${JSON.stringify(data, null, 2)}`;
    
    throw new Error('formatInput() must be overridden in brain implementation');
  },
  
  // STEP 4 HELPER: Parse Claude's JSON output
  parseOutput(rawOutput: string): any[] {
    // OVERRIDE THIS IN EACH BRAIN
    // Common pattern:
    try {
      // Remove markdown code fences if present
      const cleaned = rawOutput.replace(/```json\n?/g, '').replace(/```\n?/g, '').trim();
      const parsed = JSON.parse(cleaned);
      
      // Validate structure
      if (!Array.isArray(parsed)) {
        throw new Error('Output must be an array');
      }
      
      return parsed;
    } catch (error) {
      console.error('Parse error:', error);
      console.error('Raw output:', rawOutput);
      return [];
    }
  },
  
  // STEP 5 HELPER: Save parsed output to database
  async saveToDatabase(nicheId: number, records: any[]) {
    // OVERRIDE THIS IN EACH BRAIN
    // Example for insights:
    // for (const record of records) {
    //   const sql = `INSERT INTO insights (niche_id, category, title, content, ...) VALUES ($1, $2, $3, $4, ...)`;
    //   await queryDatabase(sql, [nicheId, record.category, record.title, ...]);
    // }
    
    throw new Error('saveToDatabase() must be overridden in brain implementation');
  }
};

// ============================================
// EXAMPLE: RESEARCH ANALYST BRAIN (CONCRETE IMPLEMENTATION)
// ============================================

export const researchAnalystBrain = {
  ...brainSkillTemplate,
  
  name: 'research_analyst',
  description: 'Extract insights from raw Reddit/social media data',
  
  systemPrompt: `[FULL RESEARCH ANALYST PROMPT FROM brain-prompts.md]`,
  
  async fetchInputData(params: { nicheId: number }) {
    const sql = `
      SELECT id, content 
      FROM rawSourceData 
      WHERE niche_id = $1 AND processed = false
      LIMIT 100
    `;
    return await queryDatabase(sql, [params.nicheId]);
  },
  
  formatInput(data: any[]): string {
    return `Analyze these ${data.length} posts and extract insights:\n\n${JSON.stringify(data, null, 2)}`;
  },
  
  parseOutput(rawOutput: string): any[] {
    try {
      const cleaned = rawOutput.replace(/```json\n?/g, '').replace(/```\n?/g, '').trim();
      const parsed = JSON.parse(cleaned);
      
      // Validate each insight has required fields
      return parsed.filter((item: any) => 
        item.category && item.title && item.content
      );
    } catch (error) {
      console.error('Parse error:', error);
      return [];
    }
  },
  
  async saveToDatabase(nicheId: number, insights: any[]) {
    for (const insight of insights) {
      const sql = `
        INSERT INTO insights (
          niche_id, category, title, content, 
          structured_data, confidence, source_count
        ) VALUES ($1, $2, $3, $4, $5, $6, $7)
      `;
      
      await queryDatabase(sql, [
        nicheId,
        insight.category,
        insight.title,
        insight.content,
        JSON.stringify(insight.structuredData || {}),
        insight.confidence || 7,
        insight.sourceCount || 1
      ]);
    }
    
    // Mark raw data as processed
    const updateSql = `UPDATE rawSourceData SET processed = true WHERE niche_id = $1`;
    await queryDatabase(updateSql, [nicheId]);
  }
};

// ============================================
// USAGE IN MCP SERVER
// ============================================

/*
// In your MCP server file:

import { researchAnalystBrain, personaArchitectBrain, ... } from './brains';

const server = new Server({
  name: 'niche-intelligence-mcp',
  version: '1.0.0'
}, {
  capabilities: {
    tools: {}
  }
});

// Register each brain as a tool
server.setRequestHandler(ListToolsRequestSchema, async () => ({
  tools: [
    {
      name: researchAnalystBrain.name,
      description: researchAnalystBrain.description,
      inputSchema: {
        type: 'object',
        properties: researchAnalystBrain.parameters,
        required: ['nicheId']
      }
    },
    // ... register other brains
  ]
}));

server.setRequestHandler(CallToolRequestSchema, async (request) => {
  const { name, arguments: args } = request.params;
  
  if (name === 'research_analyst') {
    return await researchAnalystBrain.execute(args);
  }
  // ... handle other brains
});
*/