import OpenAI from 'openai';

export async function onRequest(context: any) {
  const client = new OpenAI({ apiKey: process.env.OPENAI_API_KEY || 'test-openai-key' });
  const history = await context.store.getMessages({
    conversationId: context.conversation_id,
    limit: 20,
  });
  return {
    ok: true,
    framework: 'openai-agents-sdk',
    conversation_id: context.conversation_id,
    run_id: context.run_id,
    sdk_available: Boolean(client),
    has_responses_api: typeof (client as any).responses !== 'undefined',
    memory_messages: context.store.toOpenAIInput(history).length,
  };
}
