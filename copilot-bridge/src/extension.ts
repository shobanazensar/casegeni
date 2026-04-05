import * as vscode from 'vscode';
import * as http from 'http';

const PORT = 3100;
let server: http.Server | undefined;

interface ChatMessage {
  role: string;
  content: string;
}

interface CompletionRequest {
  model?: string;
  messages: ChatMessage[];
  temperature?: number;
  max_tokens?: number;
  response_format?: { type: string };
}

/**
 * Map system messages into User messages with a [SYSTEM] prefix because
 * the VS Code LM API only supports User and Assistant turn types.
 */
function buildVsMessages(messages: ChatMessage[]): vscode.LanguageModelChatMessage[] {
  const result: vscode.LanguageModelChatMessage[] = [];
  for (const msg of messages) {
    if (msg.role === 'system') {
      result.push(
        vscode.LanguageModelChatMessage.User(`[SYSTEM INSTRUCTIONS]\n${msg.content}`)
      );
    } else if (msg.role === 'user') {
      result.push(vscode.LanguageModelChatMessage.User(msg.content));
    } else if (msg.role === 'assistant') {
      result.push(vscode.LanguageModelChatMessage.Assistant(msg.content));
    }
  }
  return result;
}

async function handleChatCompletion(
  body: CompletionRequest,
  res: http.ServerResponse,
  outputChannel: vscode.OutputChannel
): Promise<void> {
  // Discover available Copilot models
  const models = await vscode.lm.selectChatModels({ vendor: 'copilot' });
  if (models.length === 0) {
    throw new Error(
      'No GitHub Copilot language model available. ' +
      'Make sure you are signed in to GitHub Copilot in VS Code.'
    );
  }

  // Try to honour the model name the user typed in the Streamlit UI.
  // Fall back to the first available Copilot model.
  const requestedModel = (body.model || '').trim().toLowerCase();
  let chosenModel = models[0];
  if (requestedModel && requestedModel !== 'copilot') {
    const match = models.find(
      m =>
        m.id.toLowerCase().includes(requestedModel) ||
        m.family.toLowerCase().includes(requestedModel)
    );
    if (match) {
      chosenModel = match;
    }
  }

  outputChannel.appendLine(
    `[Bridge] Using model: ${chosenModel.id} (family: ${chosenModel.family})`
  );

  const vsMessages = buildVsMessages(body.messages);
  const tokenSource = new vscode.CancellationTokenSource();

  // Build options — only pass supported keys
  const sendOptions: vscode.LanguageModelChatRequestOptions = {};
  if (body.max_tokens !== undefined) {
    sendOptions.modelOptions = { max_tokens: body.max_tokens };
  }

  const response = await chosenModel.sendRequest(vsMessages, sendOptions, tokenSource.token);

  let text = '';
  for await (const chunk of response.stream) {
    if (chunk instanceof vscode.LanguageModelTextPart) {
      text += chunk.value;
    }
  }

  const result = {
    id: `chatcmpl-copilot-${Date.now()}`,
    object: 'chat.completion',
    created: Math.floor(Date.now() / 1000),
    model: chosenModel.id,
    choices: [
      {
        index: 0,
        message: { role: 'assistant', content: text },
        finish_reason: 'stop',
      },
    ],
    usage: { prompt_tokens: 0, completion_tokens: 0, total_tokens: 0 },
  };

  const json = JSON.stringify(result);
  res.writeHead(200, {
    'Content-Type': 'application/json',
    'Content-Length': Buffer.byteLength(json),
    'Access-Control-Allow-Origin': '*',
  });
  res.end(json);
  outputChannel.appendLine(`[Bridge] Response sent (${text.length} chars).`);
}

function startServer(outputChannel: vscode.OutputChannel): void {
  if (server) {
    outputChannel.appendLine('[Bridge] Server is already running.');
    return;
  }

  server = http.createServer((req, res) => {
    // CORS pre-flight
    if (req.method === 'OPTIONS') {
      res.writeHead(204, {
        'Access-Control-Allow-Origin': '*',
        'Access-Control-Allow-Methods': 'POST, GET, OPTIONS',
        'Access-Control-Allow-Headers': 'Content-Type, Authorization',
      });
      res.end();
      return;
    }

    // Simple health-check used by the Streamlit "Test connection" button
    if (req.method === 'GET' && req.url === '/health') {
      res.writeHead(200, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify({ status: 'ok', service: 'copilot-llm-bridge', port: PORT }));
      return;
    }

    // All other GETs / wrong paths
    if (req.method !== 'POST' || req.url !== '/v1/chat/completions') {
      res.writeHead(404, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify({ error: 'Not found' }));
      return;
    }

    let rawBody = '';
    req.on('data', (chunk: Buffer) => {
      rawBody += chunk.toString();
    });

    req.on('end', () => {
      (async () => {
        try {
          const body: CompletionRequest = JSON.parse(rawBody);
          outputChannel.appendLine(
            `[Bridge] Received request – model=${body.model ?? '(not set)'}, messages=${body.messages.length}`
          );
          await handleChatCompletion(body, res, outputChannel);
        } catch (err: unknown) {
          const message = err instanceof Error ? err.message : String(err);
          outputChannel.appendLine(`[Bridge] Error: ${message}`);
          const errJson = JSON.stringify({
            error: { message, type: 'bridge_error' },
          });
          if (!res.headersSent) {
            res.writeHead(500, { 'Content-Type': 'application/json' });
          }
          res.end(errJson);
        }
      })();
    });
  });

  server.listen(PORT, '127.0.0.1', () => {
    const msg = `Copilot LLM Bridge running on http://127.0.0.1:${PORT}`;
    outputChannel.appendLine(`[Bridge] ${msg}`);
    vscode.window.showInformationMessage(msg);
  });

  server.on('error', (err: NodeJS.ErrnoException) => {
    if (err.code === 'EADDRINUSE') {
      outputChannel.appendLine(
        `[Bridge] Port ${PORT} is already in use. ` +
        'Another instance of the bridge may already be running — that is fine.'
      );
    } else {
      outputChannel.appendLine(`[Bridge] Server error: ${err.message}`);
    }
  });
}

export function activate(context: vscode.ExtensionContext): void {
  const outputChannel = vscode.window.createOutputChannel('Copilot LLM Bridge');
  context.subscriptions.push(outputChannel);

  outputChannel.appendLine('[Bridge] Extension activated. Starting local HTTP server…');
  startServer(outputChannel);

  const startCmd = vscode.commands.registerCommand('copilotLlmBridge.start', () => {
    startServer(outputChannel);
    outputChannel.show();
  });

  const stopCmd = vscode.commands.registerCommand('copilotLlmBridge.stop', () => {
    if (server) {
      server.close();
      server = undefined;
      outputChannel.appendLine('[Bridge] Server stopped.');
      vscode.window.showInformationMessage('Copilot LLM Bridge stopped.');
    } else {
      outputChannel.appendLine('[Bridge] Server was not running.');
    }
  });

  const statusCmd = vscode.commands.registerCommand('copilotLlmBridge.status', () => {
    outputChannel.show();
    outputChannel.appendLine(
      `[Bridge] Status: ${server ? `Running on http://127.0.0.1:${PORT}` : 'Stopped'}`
    );
  });

  context.subscriptions.push(startCmd, stopCmd, statusCmd);
}

export function deactivate(): void {
  if (server) {
    server.close();
    server = undefined;
  }
}
