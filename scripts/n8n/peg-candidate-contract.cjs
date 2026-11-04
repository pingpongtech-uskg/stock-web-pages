'use strict';

// Validate the authenticated prepare artifact before using its roster for discovery.
function validatePreview(preview, expected) {
  if (!preview || !expected || typeof preview !== 'object' || Array.isArray(preview)) throw Error('candidate_schema');
  const keys = ['requestId', 'marketDate', 'prepareRunId', 'prepareRunAttempt', 'sourceGitCommit', 'candidateSha256'];
  if (keys.some(key => preview[key] !== expected[key]) ||
      !/^[a-zA-Z0-9_.:-]{1,160}$/.test(preview.requestId || '') ||
      !/^\d{4}-\d{2}-\d{2}$/.test(preview.marketDate || '') ||
      !/^[1-9]\d{0,23}$/.test(preview.prepareRunId || '') ||
      !Number.isSafeInteger(preview.prepareRunAttempt) || preview.prepareRunAttempt < 1 ||
      !/^[a-f0-9]{40}$/.test(preview.sourceGitCommit || '') ||
      !/^[a-f0-9]{64}$/.test(preview.candidateSha256 || '')) throw Error('candidate_lineage');
  if (!Array.isArray(preview.stocks) || preview.stocks.length !== 100) throw Error('candidate_stocks');
  const codes = new Set();
  for (const stock of preview.stocks) {
    if (!stock || !/^\d{4,6}[A-Z]?$/.test(stock.code || '') || codes.has(stock.code) ||
        typeof stock.name !== 'string' || !stock.name || !stock.pegReview ||
        typeof stock.pegReview.status !== 'string' ||
        !(stock.currentPeriod === null || typeof stock.currentPeriod === 'string')) throw Error('candidate_stocks');
    codes.add(stock.code);
  }
  return { ...preview, stocks: preview.stocks.map(stock => ({ ...stock, pegReview: { ...stock.pegReview } })) };
}

function bindManifest(manifest, preview) {
  if (!manifest || manifest.marketDate !== preview.marketDate || manifest.requestId !== preview.requestId || !Array.isArray(manifest.stocks)) throw Error('manifest_lineage');
  const eligible = new Set(preview.stocks.filter(stock => stock.pegReview.status === 'needs_review').map(stock => stock.code));
  const seen = new Set();
  for (const stock of manifest.stocks) {
    if (!stock || !eligible.has(stock.code) || seen.has(stock.code) || typeof stock.legalName !== 'string' || !Array.isArray(stock.officialDomains) || !Array.isArray(stock.results)) throw Error('manifest_stocks');
    seen.add(stock.code);
  }
  if (seen.size !== eligible.size) throw Error('manifest_stocks');
  return { ...manifest, prepareRunId: preview.prepareRunId, prepareRunAttempt: preview.prepareRunAttempt, candidateSha256: preview.candidateSha256 };
}
function validatePrepareRun(run, expected) {
  if (!run || String(run.id) !== expected.prepareRunId || run.run_attempt !== expected.prepareRunAttempt ||
      run.display_title !== `Daily PEG prepare | ${expected.requestId} | ${expected.marketDate}` ||
      run.event !== 'workflow_dispatch' || run.head_branch !== 'main' ||
      !['.github/workflows/daily.yml', '.github/workflows/daily.yml@main', '.github/workflows/daily.yml@refs/heads/main'].includes(run.path) ||
      run.head_sha !== expected.sourceGitCommit || !/^[a-f0-9]{40}$/.test(run.head_sha || '') ||
      run.status !== 'completed' || run.conclusion !== 'success') throw Error('prepare_run_lineage');
  return run;
}
function selectCandidateArtifact(body, expected) {
  if (!Array.isArray(body?.artifacts) || body.total_count !== body.artifacts.length || body.artifacts.length > 100) throw Error('candidate_artifact');
  const matches = body.artifacts.filter(artifact => artifact?.name === `peg-candidate-${expected.prepareRunId}-${expected.prepareRunAttempt}` && artifact.expired === false);
  if (matches.length !== 1) throw Error('candidate_artifact');
  const artifact = matches[0], run = artifact.workflow_run;
  if (!/^[1-9]\d{0,23}$/.test(String(artifact.id || '')) || String(run?.id) !== expected.prepareRunId ||
      run.head_sha !== expected.sourceGitCommit || String(run.repository_id) !== '1273106108' || String(run.head_repository_id) !== '1273106108') throw Error('candidate_artifact');
  return artifact;
}
module.exports = { validatePreview, bindManifest, validatePrepareRun, selectCandidateArtifact };
