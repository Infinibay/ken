#[path = "../examples/support/observed_peak.rs"]
mod observed_peak;
use observed_peak::ObservedPeak;

#[test]
fn observed_peak_retains_every_reported_sample_and_its_exact_running_maximum() {
    let mut peak = ObservedPeak::default();
    // Actual Linux6.12.67 VmHWM trace from the failed Ettin process.
    for (reported, wanted) in [
        (836571136, 836571136),
        (842493952, 842493952),
        (842113024, 842493952),
        (919941120, 919941120),
        (919535616, 919941120),
    ] {
        let sample = peak.record(reported).unwrap();
        assert_eq!(sample.reported_hwm_bytes, reported);
        assert_eq!(sample.observed_peak_bytes, wanted);
    }
}

#[test]
fn zero_report_is_an_error_and_does_not_reset_the_observed_peak() {
    let mut peak = ObservedPeak::default();
    assert_eq!(peak.record(100).unwrap().observed_peak_bytes, 100);
    assert!(peak.record(0).is_err());
    let sample = peak.record(90).unwrap();
    assert_eq!(sample.reported_hwm_bytes, 90);
    assert_eq!(sample.observed_peak_bytes, 100);
}
