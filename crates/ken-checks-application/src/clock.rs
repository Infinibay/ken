//! A real UTC operation timestamp and independent OS-random receipt identity.
use crate::{Error, Result};
use ken_contracts::checks::Clock;
use std::{
    io::Read,
    time::{SystemTime, UNIX_EPOCH},
};
pub(crate) struct NativeClock {
    timestamp: String,
    id: String,
}
impl NativeClock {
    pub fn new() -> Result<Self> {
        let elapsed = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .map_err(|e| Error::Invalid(e.to_string()))?;
        let seconds = libc::time_t::try_from(elapsed.as_secs())
            .map_err(|_| Error::Invalid("receipt timestamp exceeds native UTC range".into()))?;
        let mut utc = std::mem::MaybeUninit::<libc::tm>::uninit();
        if unsafe { libc::gmtime_r(&seconds, utc.as_mut_ptr()) }.is_null() {
            return Err(Error::Invalid(
                "receipt timestamp exceeds native UTC range".into(),
            ));
        }
        let utc = unsafe { utc.assume_init() };
        let timestamp = format!(
            "{:04}-{:02}-{:02}T{:02}:{:02}:{:02}.{:06}+00:00",
            utc.tm_year + 1900,
            utc.tm_mon + 1,
            utc.tm_mday,
            utc.tm_hour,
            utc.tm_min,
            utc.tm_sec,
            elapsed.subsec_micros()
        );
        let mut random = [0u8; 16];
        std::fs::File::open("/dev/urandom")?.read_exact(&mut random)?;
        let id = random.iter().map(|b| format!("{b:02x}")).collect();
        Ok(Self { timestamp, id })
    }
}
impl Clock for NativeClock {
    fn now(&self) -> String {
        self.timestamp.clone()
    }
    fn run_id(&self) -> String {
        self.id.clone()
    }
}
