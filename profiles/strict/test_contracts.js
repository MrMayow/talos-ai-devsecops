const fs = require('fs');
const path = require('path');

const root = __dirname;
const workflowsDir = path.join(root, 'workflows');

function assert(condition, message) {
  if (!condition) throw new Error(message);
}

function load(prefix) {
  const file = fs.readdirSync(workflowsDir).find((name) => name.startsWith(`${prefix}-`));
  assert(file, `Workflow ${prefix} not found`);
  return JSON.parse(fs.readFileSync(path.join(workflowsDir, file), 'utf8'));
}

function blocks(workflow) {
  return Object.values(workflow.state.blocks);
}

function getBlock(workflow, name) {
  const matches = blocks(workflow).filter((item) => item.name === name);
  assert(matches.length === 1, `${name}: expected one block, got ${matches.length}`);
  return matches[0];
}

function startFields(workflow) {
  const start = blocks(workflow).find((item) => item.type === 'start_trigger');
  assert(start, 'Start block not found');
  return (start.subBlocks.inputFormat.value ?? []).map((item) => item.name);
}

function assertContainsFields(text, fields, label) {
  for (const field of fields) {
    assert(new RegExp(`(?:^|[,{\\s])['\"]?${field}['\"]?\\s*:`, 'm').test(text), `${label}: missing ${field}`);
  }
}

const w1 = load('01');
const w2 = load('02');
const w3 = load('03');
const w4 = load('04');

const w1Start = blocks(w1).find((item) => item.type === 'start_trigger');
const artifactOwnerDefault = w1Start.subBlocks.inputFormat.value.find((item) => item.name === 'artifact_owner')?.value;
assert(artifactOwnerDefault === 'labadmin', 'W1 package owner must match the production Gitea owner');

// Workflow 01 -> Workflow 02 contract, including the user-driven revision path.
const w2Inputs = startFields(w2);
assertContainsFields(getBlock(w1, 'Build Approved Result').subBlocks.code.value, w2Inputs, 'W1 approved -> W2');
assertContainsFields(getBlock(w2, 'Trigger Workflow 02 Revision').subBlocks.body.value, w2Inputs, 'W2 revision -> W2');
const requirementsProducer = getBlock(w1, 'Build Approved Result').subBlocks.code.value;
const requirementsConsumer = getBlock(w2, 'Validate Requirements Input').subBlocks.code.value;
assert(requirementsProducer.includes("schema_version: '3.0'"), 'W1 does not emit requirements schema 3.0');
assert(requirementsConsumer.includes("artifact.schema_version !== '3.0'"), 'W2 does not accept requirements schema 3.0');

// Workflow 02 -> Workflow 03 contract and Workflow 03 self-revision contract.
const w3Inputs = startFields(w3);
assertContainsFields(getBlock(w2, 'Trigger Workflow 03').subBlocks.body.value, w3Inputs, 'W2 -> W3');
assertContainsFields(getBlock(w3, 'Trigger Workflow 03 Revision').subBlocks.body.value, w3Inputs, 'W3 revision -> W3');
const architectureProducer = getBlock(w2, 'Build Architecture Result').subBlocks.code.value;
const architectureConsumer = getBlock(w3, 'Validate Implementation Input').subBlocks.code.value;
assert(architectureProducer.includes("schema_version: '2.0'"), 'W2 does not emit architecture schema 2.0');
assert(architectureConsumer.includes("artifact.schema_version !== '2.0'"), 'W3 does not accept architecture schema 2.0');

// Workflow 02 quality-gate UX must explain why approve can be rejected.
const architectureApproval = getBlock(w2, 'Architecture Approval');
const architectureApprovalInputs = architectureApproval.subBlocks.inputFormat.value;
assert(
  architectureApprovalInputs.find((item) => item.name === 'decision')?.description.includes('review_passed=true'),
  'W2 HITL does not explain the closed architecture quality gate'
);
assert(
  architectureApproval.subBlocks.builderData.value.some((item) => item.name === 'approval_available'),
  'W2 HITL does not expose approval_available'
);
for (const name of ['Check Architecture Publication', 'Check Architecture Revision Publication']) {
  assert(getBlock(w2, name).subBlocks.code.value.includes('[200, 201, 204, 409]'), `${name}: immutable replay is not accepted`);
}

// A missing target branch is an expected first-run state. It must be probed via
// the 200-returning branch list rather than a concrete-branch GET that yields 404.
const targetBranchProbe = getBlock(w3, 'Get Target Branch');
assert(targetBranchProbe.subBlocks.url.value.endsWith('/branches'), 'W3 target branch probe can still fail with 404');
const targetBranchParams = Object.fromEntries(
  targetBranchProbe.subBlocks.params.value
    .filter((item) => item.cells.Key)
    .map((item) => [item.cells.Key, item.cells.Value])
);
assert(targetBranchParams.page === '1' && targetBranchParams.limit === '100', 'W3 branch-list probe is not bounded');
const branchExistsCondition = JSON.parse(getBlock(w3, 'Target Branch Exists').subBlocks.conditions.value)[0].value;
assert(branchExistsCondition.includes('Array.isArray(<gettargetbranch.data>)'), 'W3 branch existence does not inspect the list');
assert(branchExistsCondition.includes('.some((item)'), 'W3 branch existence does not match the exact branch name');
const createdBranchCheck = getBlock(w3, 'Check Created Branch').subBlocks.code.value;
assert(createdBranchCheck.includes('listed.find((item)'), 'W3 cannot recover an existing branch from the list');
assert(
  getBlock(w3, 'Create Branch').subBlocks.body.value.includes('<validateimplementationinput.result.base_branch>'),
  'W3 branch creation hardcodes the base branch'
);
assert(
  getBlock(w3, 'Create PR').subBlocks.body.value.includes('"base": "<validateimplementationinput.result.base_branch>"'),
  'W3 pull request hardcodes the base branch'
);
const contractPublication = getBlock(w3, 'Check Contract Publication').subBlocks.code.value;
assert(contractPublication.includes('[200, 201, 204, 409]'), 'W3 cannot resume after publishing its immutable contract');
assert(contractPublication.includes('newly_created: status !== 409'), 'W3 does not distinguish a reused contract');

// Gitea CI -> Workflow 04 contract.
const callbackInputs = [
  'run_id', 'owner', 'repo', 'branch', 'commit_sha', 'pr_number',
  'artifact_owner', 'artifact_package', 'artifact_version',
  'context_owner', 'context_package', 'context_version', 'attempt', 'dry_run'
];
assert(JSON.stringify(startFields(w4)) === JSON.stringify(callbackInputs), 'W4 Start fields differ from CI callback contract');

const notify = fs.readFileSync(path.join(root, '..', '..', 'platform', 'ci', 'notify-workflow04.sh'), 'utf8');
assertContainsFields(notify, callbackInputs, 'CI callback -> W4');
assert(!notify.includes('architecture_artifact_json'), 'Obsolete architecture_artifact_json remains in callback');
assert(notify.includes('AI_MAX_REPAIR_ATTEMPTS:-5'), 'CI callback has no default repair limit');
assert(notify.includes('ATTEMPT" -gt "$MAX_REPAIR_ATTEMPTS'), 'CI callback does not stop after max attempts');
assert(notify.includes('Quality gate passed; Workflow 04 callback is not required.'), 'Green CI still calls W4');

const w4Validator = getBlock(w4, 'Validate Input').subBlocks.code.value;
assert(w4Validator.includes('const runId = text(<start.run_id>)'), 'W4 does not read run_id');
assert(w4Validator.includes('run_id: runId'), 'W4 does not preserve run_id');
assert(w4Validator.includes('attempt > 5'), 'W4 does not reject attempt > 5');

// Workflow 04 -> Gitea workflow_dispatch contract.
const dispatchFields = ['pr_number', 'context_version', 'repair_attempt', 'run_id'];
const dispatchBody = getBlock(w4, 'Trigger Recheck CI').subBlocks.body.value;
assertContainsFields(dispatchBody, dispatchFields, 'W4 -> Gitea dispatch');
assert(dispatchBody.includes('"run_id": "<validateinput.result.run_id>"'), 'W4 substitutes context_version for run_id');
assert(dispatchBody.includes('"ref": "<validateinput.result.branch>"'), 'W4 dispatch ref is not a documented branch name');
const dispatchCheck = getBlock(w4, 'Check Recheck CI Dispatch').subBlocks.code.value;
assert(dispatchCheck.includes('[200, 204]'), 'W4 does not validate both documented dispatch success statuses');
assert(dispatchCheck.includes('data?.id ?? data?.workflow_run_id'), 'W4 does not capture the dispatched CI run id');
const w4NamesById = Object.fromEntries(blocks(w4).map((item) => [item.id, item.name]));
const w4Edges = new Set(w4.state.edges.map((edge) => `${w4NamesById[edge.source]} -> ${w4NamesById[edge.target]}`));
assert(w4Edges.has('Trigger Recheck CI -> Check Recheck CI Dispatch'), 'W4 reports success before checking dispatch');
assert(w4Edges.has('Check Recheck CI Dispatch -> Revision Written'), 'W4 dispatch check is not connected to the response');
const pipeline = fs.readFileSync(path.join(root, '..', '..', 'platform', '.gitea', 'workflows', 'pipeline.yml'), 'utf8');
for (const field of dispatchFields) {
  assert(new RegExp(`^\\s{6}${field}:\\s*$`, 'm').test(pipeline), `pipeline.yml: missing dispatch input ${field}`);
}
assert(!pipeline.includes('synchronized'), 'pipeline.yml must not react to each repair commit');
assert(pipeline.includes('timeout-minutes: 90'), 'Gitea job timeout must be explicit');
assert(pipeline.includes('integer from 0 to 5'), 'Gitea dispatch attempt range drifted');
assert(!/vars\.CI_/u.test(pipeline), 'Gitea Variables cannot start with CI');
assert(pipeline.includes('secrets.AI_GITEA_TOKEN'), 'Gitea runner secret name drifted');

// One bounded FastAPI profile is shared by architecture and implementation.
for (const [workflow, name] of [
  [w2, 'Implementation Profile Catalog'],
  [w3, 'Implementation Profile Catalog']
]) {
  const code = getBlock(workflow, name).subBlocks.code.value;
  for (const expected of [
    "profile_id: 'python-fastapi-3.12'",
    'max_generated_files: 15',
    'max_file_chars: 20000',
    'max_payload_chars: 55000'
  ]) assert(code.includes(expected), `${name}: profile drift (${expected})`);
  assert(!/python-cli|demo-python-cli/iu.test(code), `${name}: CLI profile leaked into API baseline`);
}

const developer = getBlock(w3, 'Developer');
assert(Number(developer.subBlocks.maxTokens.value) === 16384, 'W3 output limit drifted');
const developerUserPrompt = developer.subBlocks.messages.value.find((item) => item.role === 'user').content;
assert(!developerUserPrompt.includes('<validateimplementationinput.result.artifact>'), 'W3 duplicates the complete architecture artifact in the model prompt');
const developerResponseFormat = JSON.parse(developer.subBlocks.responseFormat.value);
assert(developerResponseFormat.schema.properties.files.maxItems === 15, 'W3 response schema allows more files than the profile');
assert(
  getBlock(w3, 'Prepare Development Contract').subBlocks.code.value.includes('artifact_ref.owner'),
  'Development contract package owner is hardcoded instead of following the artifact chain'
);

// Large raw logs and repository files must never be injected unbounded into repair agents.
const artifactContext = getBlock(w4, 'Build Artifact Context').subBlocks.code.value;
assert((artifactContext.match(/12000\)/gu) ?? []).length === 3, 'W4 evidence caps are not 12K each');
const revisionContext = getBlock(w4, 'Build Revision Context').subBlocks.code.value;
assert(revisionContext.includes('content.length > 20000'), 'W4 per-file context cap is missing');
assert(revisionContext.includes('totalChars > 30000'), 'W4 total repository context cap is missing');
const selectPaths = getBlock(w4, 'Select Revision Paths').subBlocks.code.value;
assert(selectPaths.includes('paths.length > 5'), 'W4 file-count cap is missing');
const implementationContext = getBlock(w3, 'Build Repository Context').subBlocks.code.value;
assert(implementationContext.includes('content.length > 20000'), 'W3 repository per-file context cap is missing');
assert(implementationContext.includes('totalChars > 30000'), 'W3 total repository context cap is missing');
assert(!implementationContext.includes('600000'), 'W3 still admits an unbounded repository context');
for (const name of ['Revision Developer', 'Revision Reviewer']) {
  assert(Number(getBlock(w4, name).subBlocks.maxTokens.value) === 8192, `${name}: output cap drifted`);
}

for (const modelFile of ['Modelfile.instruct', 'Modelfile.coder']) {
  const text = fs.readFileSync(path.join(root, '..', '..', 'models', modelFile), 'utf8');
  assert(/PARAMETER num_ctx 30720/u.test(text), `${modelFile}: num_ctx must be 30720`);
}

for (const workflow of [w2, w3, w4]) {
  for (const item of blocks(workflow).filter((block) => block.type === 'api')) {
    assert(Number(item.subBlocks.timeout.value) === 30000, `${item.name}: API timeout is not explicit`);
  }
}

const manifest = JSON.parse(fs.readFileSync(path.join(root, 'manifest.json'), 'utf8'));
assert(manifest.models.context_tokens === 30720, 'Manifest model context drifted');
assert(manifest.generation_limits.max_payload_chars === 55000, 'Manifest generation limits drifted');
assert(manifest.ci_revision_context_limits.max_total_chars === 30000, 'Manifest revision limits drifted');
assert(manifest.implementation_repository_context_limits.max_total_chars === 30000, 'Manifest implementation context limits drifted');
for (const name of manifest.required_gitea_actions_variables) {
  assert(!/^(?:CI|GITHUB_|GITEA_)/u.test(name), `Invalid Gitea Variable name: ${name}`);
}

console.log(JSON.stringify({
  valid: true,
  contracts: [
    'Workflow01 -> Workflow02',
    'Workflow02 -> Workflow03',
    'Gitea CI -> Workflow04',
    'Workflow04 -> Gitea workflow_dispatch'
  ],
  repair_attempts: 5,
  profile: 'python-fastapi-3.12',
  generation_limits: {files: 15, per_file_chars: 20000, total_chars: 55000},
  revision_context_limits: {files: 5, per_file_chars: 20000, total_chars: 30000},
  model_context: 30720
}, null, 2));
