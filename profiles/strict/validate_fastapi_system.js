const fs = require('fs');
const path = require('path');

const root = __dirname;
const workflowDir = path.join(root, 'workflows');
const AsyncFunction = Object.getPrototypeOf(async function () {}).constructor;
const allowedModels = new Set([
  'sim-qwen25-instruct:14b',
  'sim-qwen25-coder:14b'
]);
const allowedEnvironmentVariables = new Set([
  'GITEA_URL',
  'GITEA_TOKEN',
  'SIM_INTERNAL_URL',
  'SIM_WORKFLOW01_ID',
  'SIM_WORKFLOW02_ID',
  'SIM_WORKFLOW03_ID',
  'SIM_WORKFLOW_API_KEY'
]);

function fail(message) {
  throw new Error(message);
}

function normalizeName(value) {
  return String(value).toLowerCase().replace(/[^a-z0-9]/gu, '');
}

function blockValues(workflow) {
  return Object.values(workflow.state.blocks);
}

function findBlock(workflow, name) {
  const found = blockValues(workflow).filter((item) => item.name === name);
  if (found.length !== 1) fail(`${name}: найдено блоков ${found.length}`);
  return found[0];
}

function walk(value, callback) {
  if (typeof value === 'string') callback(value);
  else if (Array.isArray(value)) value.forEach((item) => walk(item, callback));
  else if (value && typeof value === 'object') {
    Object.values(value).forEach((item) => walk(item, callback));
  }
}

function tableValue(block, table, wantedKey) {
  const row = (block.subBlocks?.[table]?.value ?? []).find(
    (item) => String(item.cells?.Key ?? '').toLowerCase() === wantedKey.toLowerCase()
  );
  return String(row?.cells?.Value ?? '');
}

function compileEmbeddedJavascript(file, blocks) {
  let functions = 0;
  let conditions = 0;
  for (const item of blocks) {
    if (item.type === 'function') {
      const code = String(item.subBlocks?.code?.value ?? '');
      for (const replacement of ['null', "'sample'"]) {
        const compilable = code.replace(/<[A-Za-z0-9_.-]+>/gu, replacement);
        try {
          new AsyncFunction(compilable);
        } catch (error) {
          fail(`${file}, ${item.name}: JavaScript after ${replacement} substitution: ${error.message}`);
        }
      }
      functions += 1;
    }
    if (item.type === 'condition') {
      let parsed;
      try {
        parsed = JSON.parse(item.subBlocks?.conditions?.value ?? '[]');
      } catch (error) {
        fail(`${file}, ${item.name}: conditions не JSON: ${error.message}`);
      }
      for (const condition of parsed.filter((entry) => entry.title !== 'else')) {
        const rawExpression = String(condition.value ?? '');
        if (/(['"])<[A-Za-z0-9_.-]+>\1/gu.test(rawExpression)) {
          fail(`${file}, ${item.name}: placeholder in Condition must not be quoted`);
        }
        for (const replacement of ['null', "'sample'"]) {
          const expression = rawExpression.replace(
            /<[A-Za-z0-9_.-]+>/gu,
            replacement
          );
          try {
            new Function(`return Boolean(${expression});`);
          } catch (error) {
            fail(`${file}, ${item.name}: condition syntax after ${replacement} substitution: ${error.message}`);
          }
        }
        conditions += 1;
      }
    }
  }
  return {functions, conditions};
}

function validateGraph(file, workflow) {
  const blocks = blockValues(workflow);
  const ids = new Set(blocks.map((item) => item.id));
  if (ids.size !== blocks.length) fail(`${file}: повторяющиеся block id`);
  for (const [key, item] of Object.entries(workflow.state.blocks)) {
    if (key !== item.id) fail(`${file}: key != id у ${item.name}`);
  }
  const starts = blocks.filter((item) => item.type === 'start_trigger');
  if (starts.length !== 1) fail(`${file}: нужен ровно один Start`);

  const conditionHandles = new Map();
  for (const item of blocks.filter((entry) => entry.type === 'condition')) {
    const parsed = JSON.parse(item.subBlocks.conditions.value);
    conditionHandles.set(
      item.id,
      new Set(parsed.map((entry) => `condition-${entry.id}`))
    );
  }
  for (const edge of workflow.state.edges) {
    if (!ids.has(edge.source) || !ids.has(edge.target)) {
      fail(`${file}: оборванное edge ${edge.id}`);
    }
    if (
      conditionHandles.has(edge.source) &&
      !conditionHandles.get(edge.source).has(edge.sourceHandle)
    ) {
      fail(`${file}: неверный condition handle ${edge.sourceHandle}`);
    }
  }
  for (const loop of Object.values(workflow.state.loops ?? {})) {
    for (const node of loop.nodes ?? []) {
      if (!ids.has(node)) fail(`${file}: loop ссылается на отсутствующий node`);
    }
  }

  const reachable = new Set([starts[0].id]);
  const queue = [starts[0].id];
  while (queue.length) {
    const current = queue.shift();
    for (const edge of workflow.state.edges.filter((entry) => entry.source === current)) {
      if (!reachable.has(edge.target)) {
        reachable.add(edge.target);
        queue.push(edge.target);
      }
    }
  }
  if (reachable.size !== blocks.length) {
    const missing = blocks.filter((item) => !reachable.has(item.id)).map((item) => item.name);
    fail(`${file}: недостижимые блоки: ${missing.join(', ')}`);
  }

  const names = new Set(blocks.map((item) => normalizeName(item.name)));
  const unresolved = new Set();
  walk(workflow.state, (text) => {
    for (const match of text.matchAll(/<([a-z0-9]+)\.[A-Za-z0-9_.-]+>/gu)) {
      if (match[1] !== 'start' && !names.has(match[1])) unresolved.add(match[1]);
    }
    for (const match of text.matchAll(/\{\{([A-Z0-9_]+)\}\}/gu)) {
      if (!allowedEnvironmentVariables.has(match[1])) {
        fail(`${file}: неизвестная environment variable ${match[1]}`);
      }
    }
  });
  if (unresolved.size) fail(`${file}: unresolved refs: ${[...unresolved].join(', ')}`);
  return blocks;
}

function validateAgents(file, blocks) {
  const agents = [];
  for (const item of blocks.filter((entry) => entry.type === 'agent')) {
    const sub = item.subBlocks;
    if (!allowedModels.has(sub.model?.value)) fail(`${file}, ${item.name}: модель не из production map`);
    if (sub.thinkingLevel?.value !== 'none') fail(`${file}, ${item.name}: thinkingLevel != none`);
    if (sub.reasoningEffort && sub.reasoningEffort.value !== 'none') {
      fail(`${file}, ${item.name}: reasoningEffort != none`);
    }
    for (const message of sub.messages?.value ?? []) {
      const content = String(message.content ?? '');
      if (/<\/?think>/iu.test(content)) fail(`${file}, ${item.name}: найден think tag`);
      if (/Here's a thinking process|Self-Correction/iu.test(content)) {
        fail(`${file}, ${item.name}: найдено рассуждение в prompt`);
      }
      if (message.role === 'user' && /^\/no_think/iu.test(content)) {
        fail(`${file}, ${item.name}: /no_think продублирован в user message`);
      }
    }
    if (item.name !== 'Solution Architect' && !sub.responseFormat?.value) {
      fail(`${file}, ${item.name}: обязательный structured response format отсутствует`);
    }
    if (item.name === 'Solution Architect' && sub.responseFormat?.value) {
      fail(`${file}, ${item.name}: Markdown architect не должен иметь JSON response format`);
    }
    agents.push({
      name: item.name,
      model: sub.model.value,
      max_tokens: Number(sub.maxTokens?.value)
    });
  }
  return agents;
}

function validateApis(file, blocks) {
  let posts = 0;
  let asyncWorkflowPosts = 0;
  for (const item of blocks.filter((entry) => entry.type === 'api')) {
    const method = String(item.subBlocks?.method?.value ?? '').toUpperCase();
    const url = String(item.subBlocks?.url?.value ?? '');
    if (method === 'POST') {
      posts += 1;
      if (Number(item.subBlocks?.retries?.value ?? 0) !== 0) {
        fail(`${file}, ${item.name}: POST retries должны быть 0`);
      }
    }
    if (method === 'POST' && /SIM_INTERNAL_URL|\/api\/workflows\//u.test(url)) {
      if (tableValue(item, 'headers', 'X-Execution-Mode').toLowerCase() !== 'async') {
        fail(`${file}, ${item.name}: workflow POST не async`);
      }
      asyncWorkflowPosts += 1;
    }
    for (const row of item.subBlocks?.headers?.value ?? []) {
      const key = String(row.cells?.Key ?? '').toLowerCase();
      const val = String(row.cells?.Value ?? '');
      if ((key === 'authorization' || key === 'x-api-key') && !/\{\{[A-Z0-9_]+\}\}/u.test(val)) {
        fail(`${file}, ${item.name}: literal secret header`);
      }
    }
  }
  return {posts, async_workflow_posts: asyncWorkflowPosts};
}

const files = fs.readdirSync(workflowDir).filter((name) => /^0[1-4]-.*\.json$/u.test(name)).sort();
if (files.length !== 4) fail(`Ожидалось 4 workflow, найдено ${files.length}`);

const workflows = new Map();
const reports = [];
for (const file of files) {
  const raw = fs.readFileSync(path.join(workflowDir, file), 'utf8');
  if (/demo-python-cli|python-cli-3\.12|qwen3-coder-next/iu.test(raw)) {
    fail(`${file}: остался CLI или нестабильная model reference`);
  }
  const workflow = JSON.parse(raw);
  const prefix = file.slice(0, 2);
  workflows.set(prefix, workflow);
  if (workflow.version !== '5.0') fail(`${file}: version != 5.0`);
  const blocks = validateGraph(file, workflow);
  const compiled = compileEmbeddedJavascript(file, blocks);
  const agents = validateAgents(file, blocks);
  const apis = validateApis(file, blocks);
  reports.push({file, blocks: blocks.length, edges: workflow.state.edges.length, ...compiled, agents, ...apis});
}

const w1 = workflows.get('01');
if (blockValues(w1).filter((item) => item.name === 'Requirements Repair').length !== 1) {
  fail('Workflow01: должен быть один re-entrant Requirements Repair');
}
if (blockValues(w1).some((item) => /Requirements Repair [1-5]/u.test(item.name))) {
  fail('Workflow01: найдены развёрнутые вручную Repair 1..5');
}
for (const name of [
  'Get Repair Checkpoint',
  'Publish Requirements Checkpoint',
  'Trigger Workflow 01 Repair',
  'Checkpoint Newly Published',
  'Requirements Quality Gate'
]) findBlock(w1, name);

const w2 = workflows.get('02');
if (findBlock(w2, 'Implementation Profile Selector').type !== 'function') {
  fail('Workflow02: profile selector должен быть deterministic Function');
}
if (!String(findBlock(w2, 'Normalize Architecture Decision').subBlocks.code.value).includes('Approve запрещён')) {
  fail('Workflow02: approve не закрыт quality gate');
}

const w3 = workflows.get('03');
for (const name of ['Get Target Branch', 'Target Branch Exists', 'Get Target Branch Tree', 'Find Existing PR', 'Select Pull Request']) {
  findBlock(w3, name);
}
if (!String(findBlock(w3, 'Validate Generated Files').subBlocks.code.value).includes('Обнаружены китайские иероглифы в файле')) {
  fail('Workflow03: language guard generated files отсутствует');
}

const w4 = workflows.get('04');
const dispatchBody = String(findBlock(w4, 'Trigger Recheck CI').subBlocks.body.value);
for (const name of ['pr_number', 'context_version', 'repair_attempt', 'run_id']) {
  if (!dispatchBody.includes(`"${name}"`)) fail(`Workflow04 dispatch: нет ${name}`);
}
if (!String(findBlock(w4, 'Validate Input').subBlocks.code.value).includes('max_attempts: 5')) {
  fail('Workflow04: max_attempts не равен 5');
}
for (const name of ['Validate Draft Revision', 'Validate Final Revision']) {
  if (!String(findBlock(w4, name).subBlocks.code.value).includes('Обнаружены китайские иероглифы в файле')) {
    fail(`Workflow04, ${name}: language guard отсутствует`);
  }
}

const manifest = JSON.parse(fs.readFileSync(path.join(root, 'manifest.json'), 'utf8'));
if (manifest.bundle_version !== '5.0') fail('manifest.bundle_version != 5.0');
if (JSON.stringify(manifest.repository_allowlist) !== JSON.stringify(['labadmin/demo-fastapi'])) {
  fail('manifest repository allowlist неверен');
}

console.log(JSON.stringify({
  valid: true,
  bundle: manifest.bundle,
  profile: manifest.application_profile,
  workflows: reports,
  repair_design: 'checkpointed async state machine; one repair block per execution',
  reasoning: 'disabled',
  cli_references: 'absent',
  literal_secrets: 'absent'
}, null, 2));
