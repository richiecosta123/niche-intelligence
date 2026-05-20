export interface BrainInput {
  nicheId: number;
}

export interface Brain {
  execute(input: BrainInput): Promise<unknown>;
}

export const researchAnalystBrain: Brain = {
  async execute({ nicheId }) {
    // TODO: implement with Anthropic SDK + MCP tool calls
    return { brain: 'research_analyst', nicheId, status: 'stub — not yet implemented' };
  },
};
