/**
 * Rescores open opportunities on a schedule.
 *
 * This is what makes the native tier worth having: every open deal gets a
 * deterministic score continuously, not just the ones someone runs an agent
 * against.
 *
 * Schedule it nightly from anonymous Apex:
 *
 *   System.schedule('Deal Rescue nightly score',
 *                   '0 0 2 * * ?',
 *                   new DealRescueScoreBatch());
 */
public with sharing class DealRescueScoreBatch
        implements Database.Batchable<sObject>, Schedulable {

    // Small on purpose: each chunk runs history and activity aggregates, so
    // the SOQL-rows ceiling is the binding limit, not CPU time.
    public static final Integer SCOPE = 50;

    public Database.QueryLocator start(Database.BatchableContext context) {
        return Database.getQueryLocator([
            SELECT Id FROM Opportunity WHERE IsClosed = false
            WITH USER_MODE
        ]);
    }

    public void execute(Database.BatchableContext context, List<Opportunity> scope) {
        Set<Id> ids = new Map<Id, Opportunity>(scope).keySet();
        DealRescueScore.recalculate(ids);
    }

    public void finish(Database.BatchableContext context) {
        // Nothing to do. Failures surface in the AsyncApexJob record rather
        // than being swallowed here.
    }

    public void execute(SchedulableContext context) {
        Database.executeBatch(new DealRescueScoreBatch(), SCOPE);
    }
}
