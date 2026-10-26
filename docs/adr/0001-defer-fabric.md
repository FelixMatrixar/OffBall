# 1. Defer Microsoft Fabric

Date: 26 October 2026. Status: accepted.

## Context

PRD 17.4 plans Fabric Real-Time Intelligence for KQL views, dashboards and Activator alerts, and milestones M2 and M3 list them. Fabric needs a trial capacity started from a work account in the same tenant as the Azure subscription (open question 17), and nothing the viewer sees depends on it: the live view reads its numbers from the `live` service, and the Engineer and the interpret service cover anything time-critical (PRD section 24).

## Decision

Fabric is left out of this build. The `alert` contract (`contracts/alert.schema.json`) is published so Activator alerts can join later without changing the Engineer or the producer console.

## Consequences

- No KQL views, Real-Time Dashboards or Activator alerts; M2's "KQL views update live" exit criterion is not met.
- The Pundit answers from the match tools only, without season-scale KQL.
- Adding Fabric later needs the trial, an Eventstream reading the `feed` and `insights` hubs, and the items in `fabric/`. Nothing in the services changes.
