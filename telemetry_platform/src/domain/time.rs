use chrono::{DateTime, Utc};
use serde::{Deserialize, Serialize};
use std::collections::HashMap;
use super::evidence::{ActivityType, ConfidenceLevel};

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct TimeInterval {
    pub start_time: DateTime<Utc>,
    pub end_time: DateTime<Utc>,
    pub activity_type: ActivityType,
    pub confidence: ConfidenceLevel,
    pub source_event_ids: Vec<String>,
}

impl TimeInterval {
    pub fn duration_seconds(&self) -> i64 {
        (self.end_time - self.start_time).num_seconds().max(0)
    }
}

/// Interval Union Algorithm:
/// Merges overlapping or touching contiguous intervals of the SAME activity type.
///
/// Deterministic Touching Rule:
/// Intervals [A, B] and [B, C] where B == B have zero temporal gap.
/// Since next.start_time <= current.end_time (B <= B is true),
/// touching intervals ARE deterministically merged into [A, C].
pub fn interval_union(mut intervals: Vec<TimeInterval>) -> Vec<TimeInterval> {
    if intervals.is_empty() {
        return Vec::new();
    }

    // Sort by start_time ASC, then end_time ASC
    intervals.sort_by(|a, b| {
        a.start_time
            .cmp(&b.start_time)
            .then_with(|| a.end_time.cmp(&b.end_time))
    });

    let mut merged: Vec<TimeInterval> = Vec::new();
    let mut current = intervals[0].clone();

    for next in intervals.into_iter().skip(1) {
        if next.start_time <= current.end_time {
            // Overlapping or touching intervals
            if next.end_time > current.end_time {
                current.end_time = next.end_time;
            }
            // Append source event IDs for end-to-end traceability
            for id in next.source_event_ids {
                if !current.source_event_ids.contains(&id) {
                    current.source_event_ids.push(id);
                }
            }
            // Conservative confidence propagation
            current.confidence = current.confidence.combine(next.confidence);
        } else {
            merged.push(current);
            current = next;
        }
    }

    merged.push(current);
    merged
}

/// Groups intervals by `activity_type`, runs `interval_union` on each group,
/// and returns the combined, timeline-pure merged intervals sorted by start_time.
pub fn interval_union_by_activity(intervals: Vec<TimeInterval>) -> Vec<TimeInterval> {
    if intervals.is_empty() {
        return Vec::new();
    }

    let mut groups: HashMap<ActivityType, Vec<TimeInterval>> = HashMap::new();
    for interval in intervals {
        groups.entry(interval.activity_type.clone()).or_default().push(interval);
    }

    let mut result = Vec::new();
    for (_activity, group) in groups {
        let merged_group = interval_union(group);
        result.extend(merged_group);
    }

    result.sort_by_key(|a| a.start_time);
    result
}

#[cfg(test)]
mod tests {
    use super::*;
    use chrono::TimeZone;

    fn make_interval(
        start_min: u32,
        end_min: u32,
        activity: ActivityType,
        confidence: ConfidenceLevel,
        source_id: &str,
    ) -> TimeInterval {
        let t_start = Utc.with_ymd_and_hms(2026, 9, 16, 10, start_min, 0).unwrap();
        let t_end = Utc.with_ymd_and_hms(2026, 9, 16, 10, end_min, 0).unwrap();
        TimeInterval {
            start_time: t_start,
            end_time: t_end,
            activity_type: activity,
            confidence,
            source_event_ids: vec![source_id.to_string()],
        }
    }

    #[test]
    fn test_interval_union_empty() {
        let res = interval_union(Vec::new());
        assert!(res.is_empty());
    }

    #[test]
    fn test_interval_union_single() {
        let i = make_interval(0, 10, ActivityType::UserInteraction, ConfidenceLevel::Proven, "evt1");
        let res = interval_union(vec![i.clone()]);
        assert_eq!(res.len(), 1);
        assert_eq!(res[0], i);
    }

    #[test]
    fn test_interval_union_overlapping() {
        let i1 = make_interval(0, 20, ActivityType::AiProcessing, ConfidenceLevel::Proven, "evt_1");
        let i2 = make_interval(10, 25, ActivityType::AiProcessing, ConfidenceLevel::Proven, "evt_2");

        let union = interval_union(vec![i1, i2]);
        assert_eq!(union.len(), 1);
        assert_eq!(union[0].duration_seconds(), 25 * 60);
        assert_eq!(union[0].source_event_ids, vec!["evt_1", "evt_2"]);
    }

    #[test]
    fn test_interval_union_disjoint() {
        let i1 = make_interval(0, 10, ActivityType::UserInteraction, ConfidenceLevel::Proven, "evt_1");
        let i2 = make_interval(20, 30, ActivityType::UserInteraction, ConfidenceLevel::Proven, "evt_2");

        let union = interval_union(vec![i1, i2]);
        assert_eq!(union.len(), 2);
        assert_eq!(union[0].duration_seconds(), 10 * 60);
        assert_eq!(union[1].duration_seconds(), 10 * 60);
    }

    #[test]
    fn test_interval_union_nested() {
        // [10:00, 10:30] completely encloses [10:10, 10:20]
        let outer = make_interval(0, 30, ActivityType::AiProcessing, ConfidenceLevel::Proven, "outer");
        let inner = make_interval(10, 20, ActivityType::AiProcessing, ConfidenceLevel::Proven, "inner");

        let union = interval_union(vec![outer, inner]);
        assert_eq!(union.len(), 1);
        assert_eq!(union[0].duration_seconds(), 30 * 60);
        assert_eq!(union[0].source_event_ids, vec!["outer", "inner"]);
    }

    #[test]
    fn test_interval_union_identical() {
        let i1 = make_interval(10, 20, ActivityType::Typing, ConfidenceLevel::Proven, "e1");
        let i2 = make_interval(10, 20, ActivityType::Typing, ConfidenceLevel::Proven, "e2");

        let union = interval_union(vec![i1, i2]);
        assert_eq!(union.len(), 1);
        assert_eq!(union[0].duration_seconds(), 10 * 60);
        assert_eq!(union[0].source_event_ids, vec!["e1", "e2"]);
    }

    #[test]
    fn test_interval_union_touching() {
        // [10:00, 10:10] and [10:10, 10:20] must be deterministically merged into [10:00, 10:20]
        let i1 = make_interval(0, 10, ActivityType::Reading, ConfidenceLevel::Proven, "r1");
        let i2 = make_interval(10, 20, ActivityType::Reading, ConfidenceLevel::Proven, "r2");

        let union = interval_union(vec![i1, i2]);
        assert_eq!(union.len(), 1);
        assert_eq!(union[0].duration_seconds(), 20 * 60);
        assert_eq!(union[0].source_event_ids, vec!["r1", "r2"]);
    }

    #[test]
    fn test_interval_union_unsorted() {
        let i1 = make_interval(20, 30, ActivityType::ExternalApp, ConfidenceLevel::Proven, "e3");
        let i2 = make_interval(0, 10, ActivityType::ExternalApp, ConfidenceLevel::Proven, "e1");
        let i3 = make_interval(5, 15, ActivityType::ExternalApp, ConfidenceLevel::Proven, "e2");

        let union = interval_union(vec![i1, i2, i3]);
        assert_eq!(union.len(), 2);
        assert_eq!(union[0].duration_seconds(), 15 * 60); // [0, 15]
        assert_eq!(union[1].duration_seconds(), 10 * 60); // [20, 30]
    }

    #[test]
    fn test_interval_union_zero_length() {
        let point = make_interval(10, 10, ActivityType::UserInteraction, ConfidenceLevel::Proven, "click");
        let span = make_interval(5, 15, ActivityType::UserInteraction, ConfidenceLevel::Proven, "span");

        let union = interval_union(vec![point, span]);
        assert_eq!(union.len(), 1);
        assert_eq!(union[0].duration_seconds(), 10 * 60);
        assert_eq!(union[0].source_event_ids, vec!["span", "click"]);
    }

    #[test]
    fn test_interval_union_multiple_categories() {
        let ai = make_interval(0, 20, ActivityType::AiProcessing, ConfidenceLevel::Proven, "ai1");
        let user = make_interval(5, 15, ActivityType::UserInteraction, ConfidenceLevel::Proven, "u1");

        let union = interval_union_by_activity(vec![ai, user]);
        // Two separate timelines must NOT merge together!
        assert_eq!(union.len(), 2);
        assert_eq!(union[0].activity_type, ActivityType::AiProcessing);
        assert_eq!(union[1].activity_type, ActivityType::UserInteraction);
    }

    #[test]
    fn test_confidence_propagation() {
        let proven = make_interval(0, 10, ActivityType::Reading, ConfidenceLevel::Proven, "p");
        let estimated = make_interval(5, 15, ActivityType::Reading, ConfidenceLevel::Estimated, "e");

        let union = interval_union(vec![proven, estimated]);
        assert_eq!(union.len(), 1);
        // Conservative propagation: Estimated downgrades Proven
        assert_eq!(union[0].confidence, ConfidenceLevel::Estimated);
    }
}
