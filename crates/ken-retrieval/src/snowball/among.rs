use super::SnowballEnv;

type AmongPredicate<T> = dyn Fn(&mut SnowballEnv<'_>, &mut T) -> bool + Sync;
pub struct Among<T: 'static>(
    pub &'static str,
    pub i32,
    pub i32,
    pub Option<&'static AmongPredicate<T>>,
);
