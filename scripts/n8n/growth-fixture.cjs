// Local unit contracts only; never sent to production APIs.
function growthFixture(selected=0,universe=1) {
  return {version:'funnel-v2-independent-trust-low-position',universe,instrumentExcluded:0,growthCoverageVersion:'growth-coverage-v1',growthInputComplete:universe,growthValuationComplete:selected,growthThresholdCandidates:selected,growthHealthCandidates:selected,growthCandidates:selected,growthMissingReasons:[],growthEvaluationState:universe?'evaluated':'not_evaluable',growthTerminalOutcomes:{universe,missing:0,knownInvalid:universe-selected,extreme:0,belowThreshold:0,healthBlocked:0,selected}};
}
module.exports={growthFixture};
