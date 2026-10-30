use std::process::ExitCode;
fn main() -> ExitCode {
    let parent = unsafe { libc::getppid() };
    if unsafe { libc::prctl(libc::PR_SET_PDEATHSIG, libc::SIGKILL) } != 0
        || unsafe { libc::getppid() } != parent
    {
        return ExitCode::FAILURE;
    }
    match ken_checks_application::worker_main(std::io::stdin().lock(), std::io::stdout().lock()) {
        Ok(()) => ExitCode::SUCCESS,
        Err(error) => {
            eprintln!("native check worker: {error}");
            ExitCode::FAILURE
        }
    }
}
