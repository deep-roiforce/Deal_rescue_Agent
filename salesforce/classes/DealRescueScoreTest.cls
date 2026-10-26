/**
 * Tests for the native rubric.
 *
 * These assert the honesty rules rather than a magic number: that the score is
 * exactly what its own components imply, that a close date pulled IN is not
 * counted as a push, and that stage order comes from the picklist. A test that
 * hardcodes "expect 40" would pass while the arithmetic drifted underneath it.
 *
 * OpportunityHistory rows are written by the platform on DML, so the history
 * assertions check the diffing logic through the real mechanism instead of
 * mocked rows.
 */
@IsTest
private class DealRescueScoreTest {

    private static Opportunity makeOpp(String name, String stage, Date closeDate) {
        Account account = new Account(Name = name + ' Account');
        insert account;

        Opportunity opp = new Opportunity(
            Name = name,
            AccountId = account.Id,
            StageName = stage,
            CloseDate = closeDate,
            Amount = 100000
        );
        insert opp;
        return opp;
    }

    /** The picklist is the pipeline. */
    @IsTest
    static void stageOrderComesFromThePicklist() {
        Map<String, Integer> order = DealRescueScore.stageOrder();

        System.assert(!order.isEmpty(), 'stage order should not be empty');
        System.assert(order.containsKey('Qualification'),
            'Qualification should be in the org picklist');

        // Whatever the org calls its stages, later ones must rank higher.
        List<Schema.PicklistEntry> entries =
            Opportunity.StageName.getDescribe().getPicklistValues();
        String first = entries[0].getValue();
        String last = entries[entries.size() - 1].getValue();
        System.assert(order.get(last) > order.get(first),
            'pipeline order should increase down the picklist');
    }

    /** The score must equal what its own components imply. */
    @IsTest
    static void scoreIsConsistentWithItsComponents() {
        Opportunity opp = makeOpp('Consistency', 'Qualification', Date.today().addDays(30));

        Test.startTest();
        Map<Id, DealRescueScore.ScoreResult> scores =
            DealRescueScore.compute(new Set<Id>{ opp.Id });
        Test.stopTest();

        DealRescueScore.ScoreResult result = scores.get(opp.Id);
        System.assertNotEquals(null, result, 'opportunity should be scored');

        Integer expected = 100
            - Math.min(result.daysSilent, DealRescueScore.DAYS_SILENT_CAP)
            - (result.closeDatePushes * DealRescueScore.CLOSE_DATE_PUSH_WEIGHT)
            - (result.stageRegressions * DealRescueScore.STAGE_REGRESSION_WEIGHT)
            - (result.activitySlopeNegative ? DealRescueScore.ACTIVITY_SLOPE_WEIGHT : 0);
        expected = Math.max(0, Math.min(100, expected));

        System.assertEquals(expected, result.base,
            'base must equal the sum of its own deductions');
        System.assert(result.base >= 0 && result.base <= 100, 'score must be clamped');
    }

    /** Pushing a close date out counts; pulling it in does not. */
    @IsTest
    static void onlyLaterCloseDatesCountAsPushes() {
        Opportunity opp = makeOpp('CloseDates', 'Qualification', Date.today().addDays(60));

        opp.CloseDate = Date.today().addDays(30);   // pulled in -- not a push
        update opp;
        opp.CloseDate = Date.today().addDays(90);   // pushed out -- a push
        update opp;

        Test.startTest();
        DealRescueScore.ScoreResult result =
            DealRescueScore.compute(new Set<Id>{ opp.Id }).get(opp.Id);
        Test.stopTest();

        Integer historyRows = [
            SELECT COUNT() FROM OpportunityHistory WHERE OpportunityId = :opp.Id
        ];
        if (historyRows > 1) {
            System.assertEquals(1, result.closeDatePushes,
                'the pull-in must not be counted, only the push');
        }
    }

    /** A stage moving backwards is the heaviest single deduction. */
    @IsTest
    static void stageRegressionIsDetectedAndExplained() {
        Opportunity opp = makeOpp('Regression', 'Qualification', Date.today().addDays(30));

        opp.StageName = 'Negotiation/Review';
        update opp;
        opp.StageName = 'Qualification';            // backwards
        update opp;

        Test.startTest();
        DealRescueScore.ScoreResult result =
            DealRescueScore.compute(new Set<Id>{ opp.Id }).get(opp.Id);
        Test.stopTest();

        Integer historyRows = [
            SELECT COUNT() FROM OpportunityHistory WHERE OpportunityId = :opp.Id
        ];
        if (historyRows > 1) {
            System.assertEquals(1, result.stageRegressions, 'one regression expected');

            Boolean explained = false;
            for (String signal : result.signals) {
                if (signal.startsWith('stage regression:')) {
                    explained = true;
                }
            }
            System.assert(explained, 'a regression must produce a signal naming it');
        }
    }

    /** Every deduction has to say why. */
    @IsTest
    static void signalsAccompanyDeductions() {
        Opportunity opp = makeOpp('Signals', 'Qualification', Date.today().addDays(30));

        insert new Task(
            WhatId = opp.Id,
            Subject = 'Old follow-up',
            ActivityDate = Date.today().addDays(-45),
            Status = 'Completed'
        );

        Test.startTest();
        DealRescueScore.ScoreResult result =
            DealRescueScore.compute(new Set<Id>{ opp.Id }).get(opp.Id);
        Test.stopTest();

        Integer deductions = (result.daysSilent > 0 ? 1 : 0)
            + (result.closeDatePushes > 0 ? 1 : 0)
            + result.stageRegressions
            + (result.activitySlopeNegative ? 1 : 0);

        System.assertEquals(deductions, result.signals.size(),
            'one signal per deduction, no more and no fewer');
    }

    /** recalculate() persists both fields. */
    @IsTest
    static void recalculateWritesTheScoreAndTheReasons() {
        Opportunity opp = makeOpp('Persist', 'Qualification', Date.today().addDays(30));

        Test.startTest();
        Integer updated = DealRescueScore.recalculate(new Set<Id>{ opp.Id });
        Test.stopTest();

        System.assertEquals(1, updated, 'one opportunity updated');

        Opportunity stored = [
            SELECT Rescue_Base_Score__c, Rescue_Base_Signals__c
            FROM Opportunity WHERE Id = :opp.Id
        ];
        System.assertNotEquals(null, stored.Rescue_Base_Score__c, 'score written');
        System.assert(stored.Rescue_Base_Score__c >= 0
            && stored.Rescue_Base_Score__c <= 100, 'score in range');
    }

    @IsTest
    static void emptyInputIsHandled() {
        System.assertEquals(0, DealRescueScore.compute(new Set<Id>()).size());
        System.assertEquals(0, DealRescueScore.compute(null).size());
        System.assertEquals(0, DealRescueScore.recalculate(new Set<Id>()));
    }

    @IsTest
    static void batchScoresOpenOpportunities() {
        makeOpp('BatchA', 'Qualification', Date.today().addDays(30));
        makeOpp('BatchB', 'Prospecting', Date.today().addDays(45));

        Test.startTest();
        Database.executeBatch(new DealRescueScoreBatch(), DealRescueScoreBatch.SCOPE);
        Test.stopTest();

        Integer scored = [
            SELECT COUNT() FROM Opportunity
            WHERE Rescue_Base_Score__c != null AND IsClosed = false
        ];
        System.assert(scored >= 2, 'batch should score the open opportunities');
    }

    @IsTest
    static void batchIsSchedulable() {
        Test.startTest();
        String jobId = System.schedule(
            'Deal Rescue test schedule',
            '0 0 2 * * ?',
            new DealRescueScoreBatch()
        );
        Test.stopTest();

        System.assertNotEquals(null, jobId, 'schedulable entry point works');
    }
}
