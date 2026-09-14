import { Server } from "@modelcontextprotocol/sdk/server/index.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import {
  CallToolRequestSchema,
  ListToolsRequestSchema,
} from "@modelcontextprotocol/sdk/types.js";
import pg from "pg";

const { Pool } = pg;

const pool = new Pool({
  connectionString: process.env.DATABASE_URL,
  ssl: { rejectUnauthorized: false },
});

const server = new Server(
  { name: "voice-intelligence-mcp", version: "1.0.0" },
  { capabilities: { tools: {} } }
);

// ============================================================================
// TOOL DEFINITIONS
// ============================================================================

server.setRequestHandler(ListToolsRequestSchema, async () => ({
  tools: [
    {
      name: "get_voice_profile",
      description:
        "Retrieve the full voice profile and all verdicts for a writer. Use this BEFORE writing any copy to understand how this person writes. Returns their voice DNA plus specific queryable rules.",
      inputSchema: {
        type: "object",
        properties: {
          author_id: {
            type: "string",
            description: "Author identifier, e.g. 'ricardo-palma'",
          },
          categories: {
            type: "array",
            items: { type: "string" },
            description:
              "Optional: filter verdicts by category. Options: opening, closing, rhythm, humor, trust, urgency, structure, word_choice, cta, ps, objection, forbidden",
          },
        },
        required: ["author_id"],
      },
    },
    {
      name: "log_voice_verdict",
      description:
        "Log a new voice verdict — a specific, confirmed decision about how this writer writes. Use this to expand the voice model as you analyze more emails or discover new patterns.",
      inputSchema: {
        type: "object",
        properties: {
          author_id: {
            type: "string",
            description: "Author identifier, e.g. 'ricardo-palma'",
          },
          category: {
            type: "string",
            description:
              "Category: opening, closing, rhythm, humor, trust, urgency, structure, word_choice, cta, ps, objection, forbidden",
          },
          situation: {
            type: "string",
            description: "When does this rule apply?",
          },
          decision: {
            type: "string",
            description: "What does the writer do in this situation?",
          },
          example: {
            type: "string",
            description: "Verbatim quote from source material that proves this",
          },
          counter_example: {
            type: "string",
            description: "What they DON'T do (contrast helps brains apply this correctly)",
          },
          confidence: {
            type: "number",
            description: "0.0-1.0: how many examples support this verdict",
          },
          source_count: {
            type: "number",
            description: "How many source emails/documents support this verdict",
          },
        },
        required: ["author_id", "category", "situation", "decision"],
      },
    },
    {
      name: "compare_to_voice",
      description:
        "Compare a piece of copy against a writer's voice profile. Returns a verdict-by-verdict analysis of what matches, what violates, and specific rewrites for each violation. Use this to improve copy to match a writer's voice.",
      inputSchema: {
        type: "object",
        properties: {
          author_id: {
            type: "string",
            description: "Author to compare against, e.g. 'ricardo-palma'",
          },
          copy: {
            type: "string",
            description: "The copy to analyze and improve",
          },
          copy_type: {
            type: "string",
            description: "Type of copy: email, ad, landing_page, sms, social",
          },
        },
        required: ["author_id", "copy"],
      },
    },
  ],
}));

// ============================================================================
// TOOL HANDLERS
// ============================================================================

server.setRequestHandler(CallToolRequestSchema, async (request) => {
  const { name, arguments: args } = request.params;

  try {
    switch (name) {

      case "get_voice_profile": {
        const { author_id, categories } = args as {
          author_id: string;
          categories?: string[];
        };

        // Get profile
        const profileResult = await pool.query(
          `SELECT * FROM voice_profiles WHERE author_id = $1`,
          [author_id]
        );

        if (profileResult.rows.length === 0) {
          return {
            content: [{ type: "text", text: `No voice profile found for author_id: ${author_id}` }],
          };
        }

        // Get verdicts
        let verdictsQuery = `SELECT * FROM voice_verdicts WHERE author_id = $1`;
        const verdictsParams: (string | string[])[] = [author_id];

        if (categories && categories.length > 0) {
          verdictsQuery += ` AND category = ANY($2)`;
          verdictsParams.push(categories);
        }

        verdictsQuery += ` ORDER BY category, confidence DESC`;

        const verdictsResult = await pool.query(verdictsQuery, verdictsParams);

        // Group verdicts by category for readability
        const verdictsByCategory: Record<string, any[]> = {};
        for (const verdict of verdictsResult.rows) {
          if (!verdictsByCategory[verdict.category]) {
            verdictsByCategory[verdict.category] = [];
          }
          verdictsByCategory[verdict.category].push(verdict);
        }

        return {
          content: [
            {
              type: "text",
              text: JSON.stringify({
                profile: profileResult.rows[0],
                verdicts_by_category: verdictsByCategory,
                total_verdicts: verdictsResult.rows.length,
              }, null, 2),
            },
          ],
        };
      }

      case "log_voice_verdict": {
        const {
          author_id,
          category,
          situation,
          decision,
          example,
          counter_example,
          confidence = 1.0,
          source_count = 1,
        } = args as {
          author_id: string;
          category: string;
          situation: string;
          decision: string;
          example?: string;
          counter_example?: string;
          confidence?: number;
          source_count?: number;
        };

        const result = await pool.query(
          `INSERT INTO voice_verdicts 
           (author_id, category, situation, decision, example, counter_example, confidence, source_count)
           VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
           RETURNING id, created_at`,
          [author_id, category, situation, decision, example ?? null, counter_example ?? null, confidence, source_count]
        );

        // Update sample count on profile
        await pool.query(
          `UPDATE voice_profiles SET updated_at = NOW() WHERE author_id = $1`,
          [author_id]
        );

        return {
          content: [
            {
              type: "text",
              text: JSON.stringify({
                status: "verdict_logged",
                verdict_id: result.rows[0].id,
                author_id,
                category,
                created_at: result.rows[0].created_at,
              }),
            },
          ],
        };
      }

      case "compare_to_voice": {
        const { author_id, copy, copy_type = "email" } = args as {
          author_id: string;
          copy: string;
          copy_type?: string;
        };

        // Get all verdicts for this author
        const verdictsResult = await pool.query(
          `SELECT * FROM voice_verdicts WHERE author_id = $1 ORDER BY category`,
          [author_id]
        );

        const profileResult = await pool.query(
          `SELECT author_name, brand, language FROM voice_profiles WHERE author_id = $1`,
          [author_id]
        );

        if (profileResult.rows.length === 0) {
          return {
            content: [{ type: "text", text: `No voice profile found for: ${author_id}` }],
          };
        }

        const profile = profileResult.rows[0];
        const verdicts = verdictsResult.rows;

        // Return structured data for the AI brain to do the comparison
        return {
          content: [
            {
              type: "text",
              text: JSON.stringify({
                instruction: "Compare the submitted copy against each verdict below. For each verdict, state: PASS, VIOLATION, or PARTIAL. For each VIOLATION or PARTIAL, provide a specific rewrite of the offending line/section. Return your analysis as structured JSON.",
                author: profile,
                copy_type,
                copy_to_analyze: copy,
                verdicts_to_check: verdicts,
                output_format: {
                  summary: "Overall assessment",
                  score: "0-10 voice match score",
                  violations: [
                    {
                      verdict_id: "number",
                      category: "string",
                      what_violated: "quote from submitted copy",
                      why: "which verdict rule was broken",
                      rewrite: "exact replacement in Ricardo's voice",
                    }
                  ],
                  passes: ["list of verdict categories that passed"],
                  revised_copy: "full rewritten copy incorporating all fixes",
                },
              }, null, 2),
            },
          ],
        };
      }

      default:
        throw new Error(`Unknown tool: ${name}`);
    }
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    return {
      content: [{ type: "text", text: `Error: ${message}` }],
      isError: true,
    };
  }
});

// ============================================================================
// START
// ============================================================================

async function main() {
  const transport = new StdioServerTransport();
  await server.connect(transport);
  console.error("Voice Intelligence MCP server running");
}

main().catch((err) => {
  console.error("Fatal:", err);
  process.exit(1);
});
