const test=require('node:test');const assert=require('node:assert/strict');const runtime=require('./runtime.cjs');
const valid={version:'funnel-v2-independent-trust-low-position',universe:7,instrumentExcluded:2,growthCoverageVersion:'growth-coverage-v1',growthInputComplete:2,growthValuationComplete:2,growthThresholdCandidates:1,growthHealthCandidates:1,growthCandidates:1,growthMissingReasons:[{reason:'missing_dividend',count:1}],growthEvaluationState:'partial',growthTerminalOutcomes:{universe:5,missing:1,knownInvalid:1,extreme:1,belowThreshold:1,healthBlocked:0,selected:1}};
test('modern coverage validates independent input count and exclusive disposition conservation',()=>{
 assert.equal(typeof runtime.validateGrowthCoverage,'function');
 assert.equal(runtime.validateGrowthCoverage(valid),undefined);
 assert.equal(runtime.validateGrowthCoverage({...valid,growthInputComplete:4}),undefined);
});
test('modern coverage matches Python denominator, exact fields, input completeness and reason constraints',()=>{
 const invalid=[{version:'future'},{universe:8},{universe:undefined},{instrumentExcluded:8},{instrumentExcluded:-1},{instrumentExcluded:1.5},{growthInputComplete:1},{growthTerminalOutcomes:{...valid.growthTerminalOutcomes,extra:0}},{growthMissingReasons:[{reason:'missing',count:0}]},{growthMissingReasons:[{reason:'missing',count:1},{reason:'missing',count:2}]}];
 for(const changes of invalid)assert.throws(()=>runtime.validateGrowthCoverage({...valid,...changes}),/growth_coverage/);
});
test('modern coverage rejects missing version/count, inflated terminal totals and mixed evaluation state',()=>{
 assert.equal(typeof runtime.validateGrowthCoverage,'function');
 for(const changes of [{growthCoverageVersion:undefined},{growthInputComplete:null},{growthMissingReasons:[{reason:'missing',count:-1}]},{growthTerminalOutcomes:{...valid.growthTerminalOutcomes,selected:2}},{growthEvaluationState:'evaluated'},{growthValuationComplete:3},{growthThresholdCandidates:2},{growthHealthCandidates:2}])assert.throws(()=>runtime.validateGrowthCoverage({...valid,...changes}),/growth_coverage/);
 assert.throws(()=>runtime.validateGrowthCoverage({}),/growth_coverage/);
});
