//! Integer-token ownership; foreign handles are never interpreted as pointers.
use crate::{ApiError, KenBuffer, MAX_PAYLOAD};
use std::collections::BTreeMap;

/// A backend serializes access to its registry around its own model state.
/// Tokens increase monotonically; a closed handle cannot select a later model.
pub struct HandleRegistry<T> {
    next: u64,
    values: BTreeMap<u64, T>,
}

impl<T> Default for HandleRegistry<T> {
    fn default() -> Self {
        Self {
            next: 1,
            values: BTreeMap::new(),
        }
    }
}

impl<T> HandleRegistry<T> {
    pub fn insert(&mut self, value: T) -> Result<u64, ApiError> {
        let handle = self.next;
        self.next = handle
            .checked_add(1)
            .ok_or_else(|| ApiError::Invalid("native handle space exhausted".into()))?;
        self.values.insert(handle, value);
        Ok(handle)
    }

    pub fn get(&self, handle: u64) -> Result<&T, ApiError> {
        self.values
            .get(&handle)
            .ok_or_else(|| ApiError::Invalid("unknown or closed native handle".into()))
    }

    pub fn remove(&mut self, handle: u64) -> Result<T, ApiError> {
        self.values
            .remove(&handle)
            .ok_or_else(|| ApiError::Invalid("unknown or closed native handle".into()))
    }

    pub fn len(&self) -> usize {
        self.values.len()
    }

    pub fn is_empty(&self) -> bool {
        self.values.is_empty()
    }
}

/// Allocations remain in the backend allocator until its release entry point
/// validates both the token and the original pointer/length. Empty cleanup is
/// harmless; releasing a copied stale nonempty descriptor is an error.
#[derive(Default)]
pub struct BufferRegistry {
    allocations: HandleRegistry<Box<[u8]>>,
}

impl BufferRegistry {
    pub fn publish(&mut self, payload: Vec<u8>, limit: usize) -> Result<KenBuffer, ApiError> {
        if payload.len() > limit.min(MAX_PAYLOAD) {
            return Err(ApiError::Invalid("native output exceeds bound".into()));
        }
        if payload.is_empty() {
            return Ok(KenBuffer::EMPTY);
        }
        let payload = payload.into_boxed_slice();
        let ptr = payload.as_ptr();
        let len = payload.len();
        let allocation = self.allocations.insert(payload)?;
        Ok(KenBuffer {
            ptr,
            len,
            allocation,
        })
    }

    pub fn release(&mut self, buffer: &mut KenBuffer) -> Result<(), ApiError> {
        if buffer.ptr.is_null() && buffer.len == 0 && buffer.allocation == 0 {
            return Ok(());
        }
        let allocation = self.allocations.get(buffer.allocation)?;
        if allocation.as_ptr() != buffer.ptr || allocation.len() != buffer.len {
            return Err(ApiError::Invalid("foreign native output descriptor".into()));
        }
        drop(self.allocations.remove(buffer.allocation)?);
        *buffer = KenBuffer::EMPTY;
        Ok(())
    }

    pub fn len(&self) -> usize {
        self.allocations.len()
    }

    pub fn is_empty(&self) -> bool {
        self.allocations.is_empty()
    }
}
