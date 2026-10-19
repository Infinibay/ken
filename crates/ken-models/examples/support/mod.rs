//! Shared post-exec measurements for native validation adapters.
pub fn peak_rss() -> Result<u64, Box<dyn std::error::Error>> {
    #[cfg(target_os = "linux")]
    {
        let status = std::fs::read_to_string("/proc/self/status")?;
        let value = status
            .lines()
            .find(|line| line.starts_with("VmHWM:"))
            .and_then(|line| line.split_whitespace().nth(1))
            .ok_or("missing post-exec VmHWM")?;
        Ok(value.parse::<u64>()? * 1024)
    }
    #[cfg(target_os = "macos")]
    {
        let mut usage = std::mem::MaybeUninit::<libc::rusage>::uninit();
        // SAFETY: the pointer is valid; getrusage initializes it on success.
        if unsafe { libc::getrusage(libc::RUSAGE_SELF, usage.as_mut_ptr()) } != 0 {
            return Err(std::io::Error::last_os_error().into());
        }
        // SAFETY: getrusage succeeded and initialized the rusage structure.
        Ok(unsafe { usage.assume_init() }.ru_maxrss as u64)
    }
    #[cfg(not(any(target_os = "linux", target_os = "macos")))]
    {
        Err("model RSS measurement supports Linux and macOS".into())
    }
}
