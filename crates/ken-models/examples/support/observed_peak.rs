//! Keep the reported kernel high-water mark alongside its observed envelope.
//! Linux documents VmHWM as approximate: individual reports can decrease.
//! This is the maximum of retained reports, not an exact allocation peak.
#[derive(Default)]
pub struct ObservedPeak(u64);

pub struct PeakSample {
    pub reported_hwm_bytes: u64,
    pub observed_peak_bytes: u64,
}

impl ObservedPeak {
    pub fn record(&mut self, reported_hwm_bytes: u64) -> Result<PeakSample, &'static str> {
        if reported_hwm_bytes == 0 {
            return Err("positive reported process high-water mark required");
        }
        self.0 = self.0.max(reported_hwm_bytes);
        Ok(PeakSample {
            reported_hwm_bytes,
            observed_peak_bytes: self.0,
        })
    }
}
