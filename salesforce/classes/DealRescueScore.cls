/**
 * Deterministic deal-health rubric, computed in the org.
 *
 * This is the same rubric as scoring.py in the orchestrator, and deliberately
 * so: the org is the better place to own the deterministic half because it can
 * score EVERY deal continuously, not only the ones an agent happens to visit.
 *
 * What Apex adds over the Rescue_Health_Score__c formula is history. Close-date
 * pushes and stage regressions live in OpportunityHistory, which formulas
 * cannot read, and activity slope needs aggregation over Tasks and Events,
 * which has no roll-up to Opportunity.
 *
 * What it deliberately does NOT do is judgement. The +/-15 adjustment, the
 * signals drawn from outside the org, the email draft -- those stay with the
 * agent, which writes Rescue_Score__c. Two fields, two owners, no fight.
 *
 * Stage order comes from the org's own picklist rather than a hardcoded list,
 * so renaming or reordering stages does not silently stop regression detection.
 */
public with sharing class DealRescueScore {

    // Mirrors ScoreWeights in the orchestrator's settings module.
    public static final Integer START = 100;
    public static final Integer DAYS_SILENT_CAP = 45;
    public static final Integer CLOSE_DATE_PUSH_WEIGHT = 8;
    public static final Integer STAGE_REGRESSION_WEIGHT = 15;
    public static final Integer ACTIVITY_SLOPE_WEIGHT = 10;
    public static final Integer ACTIVITY_WINDOW_DAYS = 30;

    public class ScoreResult {
        public Integer base;
        public Integer daysSilent;
        public Integer closeDatePushes;
        public Integer stageRegressions;
        public Boolean activitySlopeNegative;
        public List<String> signals = new List<String>();
    }

    /** Stage pipeline order, straight from the picklist definition. */
    public static Map<String, Integer> stageOrder() {
        Map<String, Integer> order = new Map<String, Integer>();
        Integer index = 0;
        for (Schema.PicklistEntry entry :
                Opportunity.StageName.getDescribe().getPicklistValues()) {
            if (entry.isActive()) {
                order.put(entry.getValue(), index);
                index++;
            }
        }
        return order;
    }

    /**
     * Score a set of opportunities. Bulk-safe: four queries regardless of size.
     */
    public static Map<Id, ScoreResult> compute(Set<Id> opportunityIds) {
        Map<Id, ScoreResult> results = new Map<Id, ScoreResult>();
        if (opportunityIds == null || opportunityIds.isEmpty()) {
            return results;
        }

        Map<String, Integer> order = stageOrder();
        Date today = Date.today();
        Date recentStart = today.addDays(-ACTIVITY_WINDOW_DAYS);
        Date priorStart = today.addDays(-ACTIVITY_WINDOW_DAYS * 2);

        Map<Id, Opportunity> opps = new Map<Id, Opportunity>([
            SELECT Id, CreatedDate, CloseDate, LastActivityDate, StageName
            FROM Opportunity
            WHERE Id IN :opportunityIds
            WITH USER_MODE
        ]);

        // OpportunityHistory stores SNAPSHOTS, not before/after pairs -- each
        // row is the state after a change. Deltas come from diffing
        // consecutive rows, which is why this is ordered.
        Map<Id, List<OpportunityHistory>> historyByOpp =
            new Map<Id, List<OpportunityHistory>>();
        for (OpportunityHistory row : [
            SELECT OpportunityId, StageName, CloseDate, CreatedDate
            FROM OpportunityHistory
            WHERE OpportunityId IN :opportunityIds
            WITH USER_MODE
            ORDER BY OpportunityId, CreatedDate ASC
        ]) {
            if (!historyByOpp.containsKey(row.OpportunityId)) {
                historyByOpp.put(row.OpportunityId, new List<OpportunityHistory>());
            }
            historyByOpp.get(row.OpportunityId).add(row);
        }

        Map<Id, Integer> recentActivity = countActivity(opportunityIds, recentStart, today);
        Map<Id, Integer> priorActivity = countActivity(opportunityIds, priorStart, recentStart);

        for (Id oppId : opportunityIds) {
            Opportunity opp = opps.get(oppId);
            if (opp == null) {
                continue;
            }
            results.put(oppId, scoreOne(
                opp,
                historyByOpp.containsKey(oppId)
                    ? historyByOpp.get(oppId)
                    : new List<OpportunityHistory>(),
                order,
                recentActivity.containsKey(oppId) ? recentActivity.get(oppId) : 0,
                priorActivity.containsKey(oppId) ? priorActivity.get(oppId) : 0,
                today
            ));
        }
        return results;
    }

    private static Map<Id, Integer> countActivity(Set<Id> oppIds, Date fromDate, Date toDate) {
        Map<Id, Integer> counts = new Map<Id, Integer>();

        for (AggregateResult row : [
            SELECT WhatId whatId, COUNT(Id) total
            FROM Task
            WHERE WhatId IN :oppIds AND ActivityDate > :fromDate AND ActivityDate <= :toDate
            WITH USER_MODE
            GROUP BY WhatId
        ]) {
            counts.put((Id) row.get('whatId'), (Integer) row.get('total'));
        }

        for (AggregateResult row : [
            SELECT WhatId whatId, COUNT(Id) total
            FROM Event
            WHERE WhatId IN :oppIds AND ActivityDate > :fromDate AND ActivityDate <= :toDate
            WITH USER_MODE
            GROUP BY WhatId
        ]) {
            Id key = (Id) row.get('whatId');
            Integer running = counts.containsKey(key) ? counts.get(key) : 0;
            counts.put(key, running + (Integer) row.get('total'));
        }
        return counts;
    }

    private static ScoreResult scoreOne(
        Opportunity opp,
        List<OpportunityHistory> history,
        Map<String, Integer> order,
        Integer recentCount,
        Integer priorCount,
        Date today
    ) {
        ScoreResult result = new ScoreResult();

        Date lastTouch = opp.LastActivityDate != null
            ? opp.LastActivityDate
            : opp.CreatedDate.date();
        result.daysSilent = Math.max(lastTouch.daysBetween(today), 0);

        result.closeDatePushes = 0;
        result.stageRegressions = 0;

        for (Integer i = 1; i < history.size(); i++) {
            OpportunityHistory previous = history[i - 1];
            OpportunityHistory current = history[i];

            // A close date moving LATER is a push. Pulling one in is not.
            if (previous.CloseDate != null && current.CloseDate != null
                    && current.CloseDate > previous.CloseDate) {
                result.closeDatePushes++;
            }

            if (previous.StageName != current.StageName
                    && order.containsKey(previous.StageName)
                    && order.containsKey(current.StageName)
                    && order.get(current.StageName) < order.get(previous.StageName)) {
                result.stageRegressions++;
                result.signals.add('stage regression: ' + previous.StageName
                    + ' → ' + current.StageName
                    + ' on ' + String.valueOf(current.CreatedDate.date()));
            }
        }

        result.activitySlopeNegative = recentCount < priorCount;

        Integer deductions =
            Math.min(result.daysSilent, DAYS_SILENT_CAP)
            + (result.closeDatePushes * CLOSE_DATE_PUSH_WEIGHT)
            + (result.stageRegressions * STAGE_REGRESSION_WEIGHT)
            + (result.activitySlopeNegative ? ACTIVITY_SLOPE_WEIGHT : 0);

        result.base = Math.max(0, Math.min(100, START - deductions));

        // Signals are ordered the way the orchestrator orders them, so the two
        // implementations can be compared line for line.
        List<String> ordered = new List<String>();
        if (result.daysSilent > 0) {
            ordered.add(result.daysSilent + ' days silent');
        }
        if (result.closeDatePushes > 0) {
            ordered.add(result.closeDatePushes + ' close-date push'
                + (result.closeDatePushes == 1 ? '' : 'es'));
        }
        ordered.addAll(result.signals);
        if (result.activitySlopeNegative) {
            ordered.add('declining activity over trailing '
                + (ACTIVITY_WINDOW_DAYS * 2) + ' days');
        }
        result.signals = ordered;

        return result;
    }

    /** Compute and persist. Returns how many opportunities were updated. */
    public static Integer recalculate(Set<Id> opportunityIds) {
        Map<Id, ScoreResult> scores = compute(opportunityIds);
        List<Opportunity> updates = new List<Opportunity>();

        for (Id oppId : scores.keySet()) {
            ScoreResult result = scores.get(oppId);
            updates.add(new Opportunity(
                Id = oppId,
                Rescue_Base_Score__c = result.base,
                Rescue_Base_Signals__c = String.join(result.signals, '\n')
            ));
        }

        if (!updates.isEmpty()) {
            update updates;
        }
        return updates.size();
    }
}
